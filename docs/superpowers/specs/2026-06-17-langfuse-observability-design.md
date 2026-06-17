# Langfuse Observability — Design Spec

- **Date:** 2026-06-17
- **Status:** Approved (design); implementation pending
- **Scope:** Phase 1 — observability/tracing. Evaluation is Phase 2 (hooks only, not built).

## 1. Motivation

Advisory runs already emit per-stage trace events to Postgres (`services/tracing/`),
surfaced in a debug panel via `GET /api/sessions/{token}/trace`. That gives stage
timings and stage outputs, but **nothing about the actual LLM calls**: no prompt,
no response, no token usage, no cost, no per-attempt retry/fallback visibility.
`InferenceTelemetry` accumulates a few fields in memory and is never persisted or
shown anywhere.

Langfuse adds an external, queryable observability layer over every advisory run:
a trace per run, a span per pipeline stage, and a generation per Gemini call with
full prompt/response and token usage. It also lays the groundwork for Phase 2
evaluation (scores, datasets, LLM-as-judge) without committing to it now.

## 2. Goals / Non-goals

**Goals (Phase 1):**

- One Langfuse trace per advisory run, correlated with the existing Postgres
  `trace_run_id`.
- A child span per pipeline stage (`profile → retrieve → conflict → reason →
  policy → explain`).
- A generation observation per Gemini call — including each retry and fallback —
  carrying model, system+user prompt, raw output, token usage, latency,
  `attempt`, `used_fallback`, `failure_type`.
- Langfuse `session_id = session_token` so all runs of one conversation group
  together in the UI.
- Self-hosted Langfuse via Docker; all data stays on the local box.
- Fully degrade-silently: Langfuse disabled by default, and any Langfuse error
  (outage, bad payload, SDK fault) never breaks an advisory run.

**Non-goals (deferred to Phase 2):**

- Scores / evaluation / datasets / LLM-as-judge / experiments. The trace shape is
  designed to support them later, but none are implemented now.
- Replacing or retiring the existing Postgres tracer / debug panel. Both keep
  running (additive integration).
- Instrumenting ingestion, RAG QA, or non-advisory paths. Phase 1 covers the
  advisory run path only (plus the hybrid path as a small follow-on).
- Redaction. Per the capture decision, payloads are sent raw; a no-op redaction
  seam is left for a future Cloud switch.

## 3. Locked decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Observability first; eval is Phase 2 | Tracing is the foundation eval hangs scores on. |
| 2 | Self-host via Docker | Traces hold student PII + raw prompts; data must stay local. |
| 3 | Additive — both tracers run, correlate via `trace_run_id` | Cannot break the working debug-panel demo; decouple a new vendor from working code. |
| 4 | Capture everything raw + surface `usage_metadata` | Max debugging value; safe on a self-hosted box. |
| 5 | Native SDK at the 3 existing chokepoints (Approach #1) | Lowest surface, explicit control of trace id / session / payloads, reuses the `traced` decorator. |

**Rejected approaches:**

- `@observe` decorators everywhere — magic; awkward to force trace id = `run_id`
  and to attach raw payloads + usage; scatters instrumentation across 8+ files.
- LangChain `CallbackHandler` on `graph.invoke` — Gemini calls go through a custom
  `google.genai` gateway, **not** LangChain, so the handler would see node
  boundaries but miss every actual LLM call, token count, and prompt.

## 4. Architecture

### 4.1 New package `observability/`

Sibling to `services/`, mirrors the `build_default_gateway()` factory pattern.

- **`observability/langfuse_client.py`**
  - `get_langfuse() -> Langfuse | None` — lazy singleton built from env. Returns
    `None` when `ADVISORY_LANGFUSE_ENABLED` is false or keys are missing → every
    caller no-ops. Same degrade-silently spirit as `build_default_gateway()` and
    the tracer's `_safe`.
  - `flush_langfuse()` — flush/shutdown the batched client; called on app/worker
    shutdown. Non-fatal on error.

- **`observability/run_trace.py`** — thin context-manager / helper wrappers.
  **Every** body is guarded so a Langfuse error becomes a `logger.warning` and
  the run continues. Helpers:
  - `advisory_run_trace(run_id, session_token, user_message, intent=None)` —
    context manager opening the **root span/trace**. Derives the Langfuse trace id
    deterministically from `run_id` (seed) so it correlates with the Postgres
    `trace_run_id`; sets `session_id = session_token`; tags `intent`, year, etc.
  - `stage_span(stage, sequence)` — context manager for one pipeline stage; sets
    span output from the stage's `output_extractor` result.
  - `record_generation(request, result, usage, latency_ms, attempt, used_fallback, failure_type)`
    — emit one generation observation. Reads `get_langfuse()` internally and
    attaches to the currently-active span via OTEL contextvars.
  - `_redact(payload)` — **no-op passthrough** for Phase 1 (capture raw). Single
    seam so a future Cloud switch / Phase-2 masking adds redaction without
    restructuring call sites.

### 4.2 Why nesting works without manual id-passing

The whole advisory pipeline runs **synchronously on the `RunQueueWorker` daemon
thread**: `RunDispatcher.execute → run_advisory_for_session → graph.invoke → node
→ LLMGateway.run → GeminiProvider.generate`. Opening the root span in
`RunDispatcher.execute` puts it in the thread's OTEL context; stage spans and
generations opened deeper on the same thread nest automatically. No trace id is
threaded through function arguments between layers.

### 4.3 Integration chokepoints — 3 edits + 1 refactor

| # | File | Edit |
|---|------|------|
| 1 | `services/chat/run_dispatcher.py` (`RunDispatcher.execute`) | Wrap the body in `advisory_run_trace(run_id, session_token, latest_user_message, ...)`. Only spot with both `run_id` + `session_token` + message. Root of the trace. (Hybrid path: same wrap in `HybridDispatcher.execute` as a small follow-on.) |
| 2 | `services/tracing/agent_tracer.py` (`traced` → `wrapped`) | Open `stage_span(stage, sequence)` around `agent_fn(state)`; set span output from the existing `output_extractor` result. One edit covers all six nodes; **no `graph.py` change**. |
| 3 | `services/inference/gateway.py` (`LLMGateway.run`) | Time each `provider.generate(...)` call; call `record_generation(...)` per attempt (retries + fallback each become a separate generation). Auto-nests under the active stage span. |
| 4 | `services/inference/providers/gemini_provider.py` + `services/inference/models.py` | **Refactor:** stop discarding the Gemini response — read `response.usage_metadata` in `_build_result`, surface as a new `InferenceResult.usage` field. Required for token/cost in Langfuse. |

## 5. Trace shape / data flow

A single advisory run renders in Langfuse as:

```
TRACE  (id = derive(run_id),  session_id = session_token)
  └─ SPAN  advisory-run            input: user_message, intent, year
     ├─ SPAN  profile              output: {student_profile}
     │   └─ GENERATION  profile    model, prompts, output, usage, attempt, used_fallback
     ├─ SPAN  retrieve             output: {count, candidates}        (deterministic — no generation)
     ├─ SPAN  conflict             output: {resolution_outcomes}
     ├─ SPAN  reason               output: {eligibility, ranked}
     │   └─ GENERATION  reason     ...
     ├─ SPAN  policy               output: {policy_decision, filtered}
     │   └─ GENERATION  policy     ...   (0..n generations incl. retries/fallback)
     └─ SPAN  explain              output: {final_answer, evidence}
         └─ GENERATION  explain    ...
```

- **Trace id** derived deterministically from `run_id` → Postgres event row and
  Langfuse trace are cross-referenceable by the same integer.
- **`session_id = session_token`** groups every run of a conversation.
- Deterministic, retrieve, and conflict stages have a span but no generation
  (no LLM call).
- A stage with retries/fallback shows multiple generations under its span.

### 5.1 Generation fields

| Field | Source |
|-------|--------|
| `name` | `request.agent_name` / stage |
| `model` | `policy.primary_model` (or fallback model on the fallback attempt) |
| `input` | `request.system_prompt` + `request.user_prompt` (raw) |
| `output` | `result.content` (raw) |
| `usage` | `InferenceResult.usage` → `{input, output, total}` from Gemini `usage_metadata` |
| `metadata` | `attempt`, `used_fallback`, `failure_type`, `temperature`, `task_type` |
| `latency` | measured around `provider.generate(...)` |

## 6. Token-usage refactor

Gemini's `generate_content` response carries `usage_metadata` with
`prompt_token_count`, `candidates_token_count`, `total_token_count`. Currently
`_build_result` reads only `response.text` and drops the rest.

- Add `usage: Optional[Dict[str, int]] = None` to `InferenceResult`
  (`services/inference/models.py`).
- In `GeminiProvider._build_result`, read `response.usage_metadata` defensively
  (`getattr`, may be absent on error paths) and map to
  `{"input": prompt, "output": candidates, "total": total}`.
- `LLMGateway.run` passes `result.usage` into `record_generation(...)`.

This is the only change to existing inference behaviour; `usage` is additive and
optional, so every existing call site is unaffected.

## 7. Config & dependencies

**`requirements.txt`:** add `langfuse` (pin a current 3.x line; exact pin
resolved at implementation against the installed SDK).

**Env vars (add to `.env.example`):**

| Var | Default | Meaning |
|-----|---------|---------|
| `ADVISORY_LANGFUSE_ENABLED` | `false` | Master switch. Off → all helpers no-op. |
| `LANGFUSE_HOST` | `http://localhost:3000` | Self-hosted endpoint. |
| `LANGFUSE_PUBLIC_KEY` | — | From the self-hosted project. |
| `LANGFUSE_SECRET_KEY` | — | Gitignored; never committed. |

`get_langfuse()` reads these once and caches. Missing keys with the switch on →
log one warning and disable (return `None`).

## 8. Self-host (Docker)

**Decision to confirm at review:** Langfuse v3 self-host pulls in several
services (its own Postgres, ClickHouse, Redis, MinIO, plus `langfuse-web` and
`langfuse-worker`). That is heavier than the single pgvector container the app
uses today.

- **Recommended:** run the Langfuse stack from a **separate** `docker-compose.langfuse.yml`
  (or a Compose `profile: [observability]` in the existing file) so
  `docker compose up -d --wait db` for the app is unchanged, and Langfuse is
  brought up explicitly (`docker compose -f docker-compose.langfuse.yml up -d`).
  This keeps the app stack lean and lets the box run Langfuse only when needed.
- **Fallback if the box can't host ClickHouse et al.:** Langfuse v2 self-host
  (single `langfuse/langfuse` container + one Postgres) covers tracing + scores +
  datasets — enough for Phase 1 and Phase 2 — at a fraction of the footprint, at
  the cost of running an older line and SDK. Pick this only if v3's footprint is a
  problem.

QUICKSTART/README gets a short "start Langfuse" note and the env-var block.

## 9. Error handling / graceful degradation

- **Default off.** `ADVISORY_LANGFUSE_ENABLED=false` out of the box → zero runtime
  effect, suite runs with no Langfuse.
- **Null client.** `get_langfuse()` returns `None` on missing keys → every helper
  guards `if client is None: <no-op / yield plain>`.
- **Swallow all faults.** Each helper body is wrapped (a `_safe`-style guard,
  matching `agent_tracer._safe`); a Langfuse error logs a warning and the run
  proceeds. This holds for trace open, span open, generation emit, and flush.
- **Flush on shutdown.** `flush_langfuse()` registered on FastAPI shutdown and on
  worker stop so batched events aren't lost; failure is non-fatal.
- **No new failure mode in the LLM path.** `record_generation` is called after
  `provider.generate` returns or raises; an `InferenceError` still propagates /
  degrades exactly as today.

## 10. Testing strategy

Tests run with Langfuse **disabled** by default (no network, respects the
`admission_test` isolation), using a fake/mock Langfuse client to assert calls.

- **`langfuse_client`:** disabled / missing-keys → `get_langfuse()` returns `None`
  and helpers no-op without raising.
- **`run_trace` helpers:** with a fake client, assert root trace gets
  `session_id = session_token` and a derived trace id; assert a Langfuse error
  inside a helper does not propagate.
- **`traced` decorator:** assert `stage_span` opened with `(stage, sequence)` and
  span output set from the extractor; inject a raising fake client and assert the
  wrapped agent result is still returned.
- **Gateway:** assert `record_generation` called once per attempt with `usage`,
  `latency_ms`, `attempt`, `used_fallback`; assert `InferenceError` still raised
  when no fallback configured.
- **Gemini provider:** mock a `google.genai` response with `usage_metadata`;
  assert `InferenceResult.usage == {"input":…, "output":…, "total":…}`; assert a
  response with no `usage_metadata` yields `usage=None` (no crash).
- **Integration (DB up, opt-in):** run one advisory run against a fake Langfuse
  sink; assert one trace, six spans, the expected generations, correct nesting,
  and `session_id`.

## 11. Phase-2 hooks (not built now)

The Phase-1 trace shape deliberately supports later evaluation:

- Stable, deterministic trace id (`derive(run_id)`) and named generations →
  scores can attach to a specific run/stage later via `langfuse.score(...)`.
- `session_id = session_token` → dataset/experiment grouping by conversation.
- The `_redact` seam → enable masking when/if scoring data leaves the box.

No scores, datasets, judges, or experiment runners are implemented in Phase 1.

## 12. File-by-file change list

**New:**

- `observability/__init__.py`
- `observability/langfuse_client.py`
- `observability/run_trace.py`
- `docker-compose.langfuse.yml` (or an `observability` profile in the existing compose)
- `tests/observability/test_langfuse_client.py`
- `tests/observability/test_run_trace.py`

**Edited:**

- `services/chat/run_dispatcher.py` — wrap `execute` in `advisory_run_trace`
- `services/chat/hybrid_dispatcher.py` — same wrap (follow-on)
- `services/tracing/agent_tracer.py` — `stage_span` inside `traced`
- `services/inference/gateway.py` — time + `record_generation` per attempt
- `services/inference/providers/gemini_provider.py` — capture `usage_metadata`
- `services/inference/models.py` — `InferenceResult.usage`
- `requirements.txt` — add `langfuse`
- `.env.example` — new env vars
- `web/app.py` (or worker shutdown) — `flush_langfuse()` hook
- `tests/` touching gateway/tracer/provider for the new behaviour
- `QUICKSTART.md` / `README` — start-Langfuse note

## 13. Open question for review

- **Langfuse v3 (heavier, current SDK) vs v2 (lighter, older line)** for the
  self-hosted stack — §8. Recommendation: v3 in a separate compose file; fall back
  to v2-lite only if the box can't carry ClickHouse/Redis/MinIO.
