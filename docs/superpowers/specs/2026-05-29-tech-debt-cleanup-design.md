# Tech-debt cleanup & inference hardening — design

- **Date:** 2026-05-29
- **Status:** Approved (brainstorming complete)
- **Branch:** `chore/stabilize-cleanup`
- **Delivery:** one spec → one implementation plan (multiple small slices) → one PR
- **Goal:** Close the technical debt surfaced in the 2026-05-29 codebase review so the `main` branch is stable and observable, without adding user-facing features beyond activating the already-written LLM conflict tiebreaker.

## Background

The 2026-05-29 review of `advisory-agent` (a conflict-aware admission advisory assistant: LangGraph pipeline `profile → retrieve → conflict → reason → policy → explain`, FastAPI + Jinja2 + vanilla JS UI, Gemini inference gateway, Postgres) found a set of low-to-medium-risk debts. The full test suite is green (174 passed, 1 skipped). This spec turns the debt list into a precise, implementable scope.

Two debts turned out to be interlinked and are the heart of this work:

1. **The LLM conflict tiebreaker is dead code.** `services/conflict/resolution_agent.py::resolve()` has a complete LLM-tiebreaker branch (lines 50–78), but `agents/conflict_agent.py:30` calls `resolve(record, report)` **without a gateway**, so the branch is unreachable. Non-decisive conflicts always end as `unresolved`.
2. **The Gemini provider has no error handling, which also disables the gateway's retry path.** `services/inference/providers/gemini_provider.py::generate()` never sets `failure_type` and calls `json.loads(text)` with no guard. On malformed JSON it **raises and crashes the whole pipeline**, instead of returning `failure_type="STRUCTURE_FAILURE"` so `gateway.run()` (`services/inference/gateway.py:21`) can retry. The retry mechanism is therefore also partially dead.

Because the tiebreaker will lean on the gateway, the gateway must be made robust first.

## Scope

Eight items, grouped by dependency. Implementation order is **C → B → A** (lowest risk first, behaviour-changing last).

### Group C — Pure cleanup (no behaviour change)

**C1. Migrate Pydantic v1 `class Config` → v2 `model_config = ConfigDict(...)`**
- `ingestion/registry/models.py:73` — `class Config: use_enum_values = True`
- `ingestion/models/pipeline_models.py:48` — `class Config: arbitrary_types_allowed = True`
- Replace each with `model_config = ConfigDict(use_enum_values=True)` / `model_config = ConfigDict(arbitrary_types_allowed=True)`, import `ConfigDict` from `pydantic`.
- **Done when:** `pytest` runs with zero `PydanticDeprecatedSince20` warnings from these two files.

**C2. Delete the abandoned LLM-reasoning stub and its dead test**
- `services/reasoning_inference_service.py` is empty (0 bytes) and imported nowhere.
- `tests/services/test_reasoning_inference_service.py` contains only a `FakeGateway` class and a fully commented-out test referencing a never-built `reason_candidates_with_gateway`.
- Reasoning runs rule-based (`services/reasoning_service.py`) and there is no current plan to LLM-ify it. Delete both files.
- **Done when:** both files are gone, `pytest` collects and passes with no missing-import errors.

### Group B — Observability & safety logging

**B1. Warn when mock retrieval bypasses the DB**
- `services/retrieval_service.py:53` returns mock candidates when `ADVISORY_MOCK_CONFLICTS` is set, silently bypassing the real DB query.
- Add a module logger and `logger.warning(...)` stating the DB path is bypassed and results are mock conflict data. This prevents "fake admissions" going unnoticed in a misconfigured environment.
- **Done when:** enabling the flag emits exactly one warning per `fetch_candidates` call; behaviour otherwise unchanged.

**B2. Log the trace extractor-error path**
- `services/tracing/agent_tracer.py:13–18` (`_safe`) already logs persistence failures — no change needed there.
- The remaining silent path is lines 38–39: when `output_extractor` raises, the error is stuffed into `output_json["_extractor_error"]` with no log. Add `logger.warning("trace extractor failed for stage=%s: %r", stage, exc)`.
- **Done when:** a raising extractor produces both the `_extractor_error` payload (unchanged) and a warning log; the agent result is still returned.

**B3. Make SSL verification explicit and configurable for crawling**
- `ingestion/fetchers/http_fetcher.py` defaults `verify_ssl=False` and unconditionally calls `urllib3.disable_warnings(InsecureRequestWarning)` at import (line 15), actively hiding the risk.
- Add a setting `FETCH_VERIFY_SSL` in `ingestion/config/settings.py`, read from env `ADVISORY_FETCH_VERIFY_SSL` (default `false` — several official .gov.vn sources have broken certs, so current behaviour is preserved by default).
- `http_fetch` uses this setting as the default for `verify_ssl`. When verification is disabled, emit a one-time `logger.warning` per fetch noting SSL verification is off for the URL. Remove the blanket module-level `disable_warnings` so the suppression is intentional rather than global.
- **Done when:** default behaviour matches today (verify off, but now logged); setting `ADVISORY_FETCH_VERIFY_SSL=true` enables real verification and stops the warning.

### Group A — Inference / gateway hardening

**A1. Harden `GeminiProvider.generate()` (minimal-correctness level)**
- Wrap the `generate_content(...)` API call and `json.loads(text)` in `try/except`.
- On **JSON parse failure** in json mode: return an `InferenceResult` with `failure_type="STRUCTURE_FAILURE"` (and the raw `content`) instead of raising, so `gateway.run()`'s existing retry loop (`gateway.py:19–22`) actually fires.
- On **empty text** in json mode: same `STRUCTURE_FAILURE` treatment (currently raises).
- On **hard API failure** (network error, auth, rate limit, 5xx surfaced by `google.genai`): raise a clean, typed `InferenceError` (new small exception in `services/inference/models.py` or a dedicated `errors.py`). No network backoff at this stage — scope deliberately excludes retry/backoff and circuit-breaker.
- **Done when:** malformed/empty JSON triggers a retry and, if retries are exhausted, returns the last `STRUCTURE_FAILURE` result (no crash); a simulated hard API error raises `InferenceError`.

**A2. Ensure every `gateway.run()` call site degrades gracefully on hard errors**
- After A1, hard failures raise `InferenceError`. Confirm/add guards at each optional-LLM call site so a hard error degrades to deterministic/default output rather than crashing the pipeline:
  - `services/conflict/resolution_agent.py::resolve()` — already wraps the gateway call in `try/except` → falls back to `unresolved`. ✅
  - `services/policy_inference_service.py::interpret_policy_ambiguity()` — currently no guard; wrap so it returns the default `{"warnings": [], "requires_human_verification": False}` on `InferenceError`.
  - `services/profile_inference_service.py::build_profile_with_gateway()` — confirm it falls back to rule-based `build_profile()` on `InferenceError` (add guard if missing).
- **Done when:** each call site has a test proving graceful degradation when the gateway raises `InferenceError`.

**A3. Wire telemetry into `gateway.run()`**
- `services/inference/telemetry.py::InferenceTelemetry.record(**event)` exists; `LLMGateway` holds `self.telemetry` (built in `factory.py:32`) but never calls it.
- In `gateway.run()`, call `self.telemetry.record(...)` (guarded for `telemetry is None`) on each attempt and on fallback, capturing at least: `agent_name`, `model`, `attempt`, `failure_type`, `used_fallback`.
- **Done when:** a run through a fake provider yields the expected ordered list of telemetry events, including a fallback event when fallback triggers.

**A4. Activate the LLM conflict tiebreaker**
- New module `services/conflict/resolution_inference_service.py`, mirroring `policy_inference_service.py`:
  - `interpret_conflict_tiebreak(record, report, gateway) -> dict` builds an `InferenceRequest(agent_name="resolution_agent", task_type="conflict_tiebreak", output_mode="json", temperature=0.0, ...)` with a system prompt that asks the model to pick the most trustworthy source and return JSON `{confidence, chosen_source_url, rationale}`. Returns `result.parsed_data` or a safe default `{"confidence": "low"}`.
  - The `resolution_agent` registry override already exists in `factory.py:23` (json mode, fallback to `gemini-2.5-flash`).
- `agents/conflict_agent.py`: when `records` is non-empty, build the gateway once via `build_default_gateway()` (matching `policy_agent`'s inline pattern) and pass a closure `lambda record, report: interpret_conflict_tiebreak(record, report, gateway)` into `resolve(record, report, gateway=...)`. `resolve()` only invokes it for non-decisive comparisons, so cost stays bounded.
- `resolve()` logic is **unchanged** — it already accepts `gateway`, guards with `try/except`, requires `confidence == "high"`, and validates `chosen_source_url`. This keeps the change additive and the existing resolution tests valid.
- **Done when:** a non-decisive conflict with a high-confidence fake-gateway response resolves via the tiebreaker (`used_llm_tiebreaker=True`, `status="resolved"`); a low-confidence or failing gateway still yields `unresolved` and marks fields uncertain (existing behaviour).

## Out of scope (explicitly deferred)

- Network retry/backoff and circuit-breaker for Gemini (only minimal-correctness error handling now).
- LLM-based reasoning agent (the deleted stub stays deleted).
- DOCX parsing, OCR for scanned PDFs, browser fetch strategy.
- Provider abstraction beyond the existing hardcoded Gemini wiring.
- Any UI / ops-console / streaming work.

## Risks & mitigations

- **A4 adds real LLM calls during conflict resolution.** Mitigation: gateway built only when conflicts exist; tiebreaker invoked only for non-decisive comparisons; `temperature=0.0`; high-confidence gate; full fallback to `unresolved`. All new behaviour is covered by unit tests using a fake gateway, so CI needs no live API key.
- **A1 changes the provider contract (raise → typed error / STRUCTURE_FAILURE result).** Mitigation: A2 audits every call site for graceful degradation before A4 relies on it.
- **B3 default unchanged** to avoid breaking existing crawls of cert-broken official sources; verification is now opt-in and logged.

## Testing strategy

- Unit tests per item, using fakes (no live Gemini, no live network).
- Reuse the existing `FakeGateway` pattern from the conflict/inference test suites.
- New tests: provider error handling (A1), call-site degradation (A2), telemetry events (A3), tiebreaker activation happy/low-confidence/failure paths (A4), mock-bypass warning (B1), extractor-error log (B2), SSL flag behaviour (B3).
- Regression gate: full `pytest` green with the Docker Postgres DB up (matches the verified baseline), and zero `PydanticDeprecatedSince20` warnings from the two migrated files.

## Acceptance criteria

1. All eight items' "Done when" conditions met.
2. `pytest` (with Docker DB) green: ≥ prior 174 passed, plus new tests; 0 unexpected warnings from migrated Pydantic models.
3. No new feature surface beyond the activated tiebreaker.
4. Delivered on `chore/stabilize-cleanup` as a single PR with commits grouped by slice (C → B → A).
