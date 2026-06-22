# Langfuse Prompt Management — Design Spec

- **Date:** 2026-06-18
- **Status:** Approved (design)
- **Architecture:** C — Hybrid `PromptService` + thin gateway hook
- **Rollout:** Pilot 3 agents (`intent_router`, `knowledge_qa`, `synthesis`), then mechanically expand

## 1. Goal

Bring Langfuse prompt management into the advisory assistant so that:

1. **Edit prompts without redeploy** — change instruction text in the Langfuse UI; the app picks up the new version at runtime via label fetch.
2. **Version + rollback** — every prompt change is a Langfuse version; deploy/rollback by moving the `production` label.
3. **A/B + per-version analytics** — each LLM generation is linked to the exact prompt version that produced it, so Langfuse shows quality/latency/cost per version.
4. **Non-engineers author prompts** — advisory staff can edit the Vietnamese instruction blocks in the UI without touching code.

All of this must respect the codebase's hard rule: **LLM call sites degrade gracefully.** Langfuse being disabled or unreachable must produce behavior identical to today.

## 2. Current state (as surveyed)

- **Prompts**: ~10 LLM agents. Each *system prompt* is an inline module-level string constant, scattered across service files. No central registry, no versioning. *User prompts* are assembled dynamically in Python (f-strings / static builder methods over RAG chunks, profile state, chat history).
- **Langfuse**: SDK `langfuse>=3,<4`. Wrapper `observability/langfuse_client.py` (`get_langfuse()` singleton, gated by `ADVISORY_LANGFUSE_ENABLED`). `observability/run_trace.py` emits run/turn/stage spans and `record_generation()` for every LLM call. **No prompt linking today** — `get_prompt` / `prompt=` are unused.
- **Gateway**: every LLM call flows through `gateway.run(InferenceRequest(system_prompt, user_prompt, ...))` → `GeminiProvider` → Gemini, and the gateway already calls `record_generation()` on every attempt (primary + fallback). This is the single choke point for generation linking.

### Pilot agents — file:line

| Agent | Constant | Call site |
| --- | --- | --- |
| `intent_router` | `INTENT_SYSTEM_PROMPT` (`services/chat/intent_router.py:38`) | `services/chat/intent_router.py` (`gateway.run`, ~219) |
| `knowledge_qa` | `KNOWLEDGE_QA_SYSTEM_PROMPT` (`services/knowledge/qa_service.py:16`) | `services/knowledge/qa_service.py` (`gateway.run`, ~133) |
| `synthesis` | `SYNTHESIS_SYSTEM_PROMPT` (`services/chat/synthesis_agent.py:9`) | `services/chat/synthesis_agent.py` (`gateway.run`, ~46) |

All three system prompts are **static** (no interpolated variables), so `compile()` is a no-op for the pilot. The pilot spans both output modes: `intent_router`/`knowledge_qa` are `json`, `synthesis` is `free_text`.

## 3. Architecture — C (Hybrid)

Clean split of responsibility:

- **`PromptService` owns "what text"** — fetch, compile, cache, fallback.
- **Gateway owns "observe the call"** — forwards the prompt handle to `record_generation` for linking. One-line change.
- **Call sites** swap an inline constant for a `PromptService.get(...)` call. User-prompt assembly is untouched.

### 3.1 `PromptService` — `observability/prompts.py`

New module, sits next to `langfuse_client.py` (it depends on `get_langfuse()`).

```python
@dataclass
class CompiledPrompt:
    text: str            # resolved system-prompt text (Langfuse or fallback)
    handle: Any | None   # Langfuse prompt client for generation linking, or None
    is_fallback: bool     # True when the in-code constant was used

class PromptService:
    def get(self, name: str, *, fallback: str, variables: dict | None = None) -> CompiledPrompt: ...

def get_prompt_service() -> PromptService: ...   # module singleton, mirrors get_langfuse()
```

Resolution logic:

1. **Langfuse disabled** (`ADVISORY_LANGFUSE_ENABLED` falsy) → return `CompiledPrompt(fallback, None, True)`. No network, no behavior change vs today.
2. **Enabled** → `client.get_prompt(name, label=<LANGFUSE_PROMPT_LABEL>, cache_ttl_seconds=<LANGFUSE_PROMPT_CACHE_TTL_SECONDS>, fallback=fallback, type="text")`, then `prompt.compile(**(variables or {}))`. Return `CompiledPrompt(text=compiled, handle=prompt, is_fallback=<langfuse-reported>)`.
3. **Any exception** → `logger.warning(...)`, return `CompiledPrompt(fallback, None, True)`.

Notes:
- Prompt type is **text** (single system block). The user turn stays Python-assembled — chat-type prompts are out of scope.
- Langfuse's own `fallback=` is a second safety net (returns the fallback if its fetch fails); our try/except is the first.
- Caching is handled inside the Langfuse SDK (in-process TTL cache with background refresh). First fetch per prompt per process is a synchronous network call.

### 3.2 Generation linking — gateway + run_trace

- `services/inference/models.py`: `InferenceRequest` gains `prompt: Optional[Any] = None` (the Langfuse prompt handle; default keeps every existing caller working).
- `services/inference/gateway.py`: both `record_generation(...)` invocations (primary attempt path and fallback path) pass `prompt=request.prompt`.
- `observability/run_trace.py`: `record_generation(...)` gains a `prompt=None` parameter, forwarded to `client.start_as_current_generation(..., prompt=prompt)`. No-op when `None` or Langfuse disabled.

### 3.3 Call-site change (pilot ×3)

Mechanical, per agent:

```python
# before
req = InferenceRequest(system_prompt=INTENT_SYSTEM_PROMPT, user_prompt=..., ...)

# after
cp = get_prompt_service().get("intent-router", fallback=INTENT_SYSTEM_PROMPT)
req = InferenceRequest(system_prompt=cp.text, prompt=cp.handle, user_prompt=..., ...)
```

The existing constant **stays in its module** as the fallback argument — always deploy-time-correct, and the diff stays small and reviewable. Prompt names (Langfuse): `intent-router`, `knowledge-qa`, `synthesis`.

### 3.4 Seeding — `scripts/seed_langfuse_prompts.py`

One-off driver (`scripts/` is not part of the test suite, per repo convention). For each managed prompt:
- If it does not yet exist in Langfuse → `client.create_prompt(name=..., prompt=CONST, labels=["production"], type="text")`.
- If it exists → skip (idempotent; avoids spurious versions on re-run).

Bootstraps Langfuse so the first runtime fetch hits a real version; the in-code fallback covers the window before seeding runs.

### 3.5 Config — `.env.example`

Add:
- `LANGFUSE_PROMPT_LABEL=production` — runtime fetch label (dev can set `latest` to see live edits immediately).
- `LANGFUSE_PROMPT_CACHE_TTL_SECONDS=300` — SDK cache TTL.

Reuses existing `ADVISORY_LANGFUSE_ENABLED`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.

## 4. Data flow

```
call site → get_prompt_service().get(name, fallback=CONST)
   ├─ disabled / error → (CONST, handle=None, is_fallback=True)
   └─ enabled → langfuse.get_prompt(label, ttl, fallback) → .compile(vars) → (text, handle)
→ InferenceRequest(system_prompt=text, prompt=handle, ...)
→ gateway.run → GeminiProvider → Gemini
→ record_generation(request, result, ..., prompt=request.prompt)
       → Langfuse generation linked to the prompt version
```

## 5. Testing

- **`PromptService`** (`tests/observability/test_prompts.py`):
  - disabled → returns fallback, `handle is None`, **no network call**;
  - enabled + hit → returns Langfuse text and a non-None handle;
  - enabled + fetch error → returns fallback, `handle is None`, warning logged;
  - `label` and `cache_ttl_seconds` are passed through to `get_prompt`;
  - `compile` applied when `variables` given.
- **`record_generation`** (extend `tests/observability/test_run_trace.py`): `prompt` forwarded to the generation; no-op when `prompt is None`.
- **Call-site characterization** (the 3 pilot sites): with Langfuse disabled, the resolved `system_prompt` is byte-identical to the previous constant — proves zero regression. Existing call-site tests must continue to pass unchanged.
- **Seed script**: manual / smoke only (not in the suite).

Tests run against the auto-created `admission_test` DB per repo convention; Langfuse is mocked/disabled in unit tests.

## 6. Scope boundaries

**In scope**
- The 3 pilot system prompts managed in Langfuse.
- `PromptService` (fetch + compile + cache + fallback), `InferenceRequest.prompt` field, gateway + `record_generation` linking.
- Seed script, `.env.example` config, tests above.

**Out of scope (follow-ups, mostly mechanical)**
- Remaining 7 agents (`profile`, `policy`, `profile_extractor`, `major_resolver`, `followup_reasoner`, `fact_extractor`, `knowledge_ocr`/`knowledge_classify`). `fact_extractor` will be the first to exercise `{{year}}` via `variables`.
- True A/B **traffic-splitting** (fetch a different label per cohort). The pilot lays the groundwork — generation linking already enables per-version *analytics*; cohort splitting is a later enhancement.
- Chat-type prompts / templating the Python-assembled user prompts.

## 7. Risks & mitigations

- **First-fetch latency** — one synchronous Langfuse call per prompt per process on a cold cache. Mitigated by the SDK TTL cache plus `fallback=` (returns instantly if Langfuse is slow/down). Optional startup warmup deferred.
- **Forgotten linking on future agents** — `prompt=cp.handle` is part of the standard migration recipe; without it a generation silently loses its prompt link. The pilot establishes the copy-paste pattern.
- **Variable-syntax drift** — Langfuse compiles with `{{double-brace}}` syntax, while existing Python user prompts use single-brace `.format()`/f-strings. Only matters when a managed prompt gains variables (none in the pilot); flagged for the `fact_extractor` migration.

## 8. Files touched

**New**
- `observability/prompts.py` — `PromptService`, `CompiledPrompt`, `get_prompt_service()`.
- `scripts/seed_langfuse_prompts.py` — seed managed prompts into Langfuse.
- `tests/observability/test_prompts.py`.

**Edited**
- `services/inference/models.py` — add `InferenceRequest.prompt`.
- `services/inference/gateway.py` — pass `prompt=request.prompt` to both `record_generation` calls.
- `observability/run_trace.py` — `record_generation(prompt=...)` → generation.
- `services/chat/intent_router.py`, `services/knowledge/qa_service.py`, `services/chat/synthesis_agent.py` — call-site swap.
- `.env.example` — new label/TTL vars.
- `tests/observability/test_run_trace.py` — linking assertions.
