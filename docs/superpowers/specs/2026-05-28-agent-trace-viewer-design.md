# Agent Trace Viewer — Design Spec

**Date:** 2026-05-28
**Status:** Approved, ready for implementation plan

## Problem

The advisory pipeline runs six LangGraph nodes (`profile → retrieve → conflict → reason → policy → explain`) but emits no per-stage telemetry. When a run produces an unexpected final answer, there is no way to inspect what each agent received or returned. Today only the final `result_json` is persisted on `chat_advisory_runs`; intermediate state is lost.

Developers need a live, per-stage view of every run so they can diagnose issues during demos and development without re-running with print statements.

## Goals

- Show each agent stage as its own card in the chat page, in execution order.
- Card collapsed: stage name + state (`pending` / `running…` spinner / duration when done).
- Card expanded (on click): full output JSON of that stage.
- Updates progress live during a run — spinner appears the moment a stage starts, duration appears the moment it finishes.
- Persist trace rows in Postgres so a run can be reviewed after server restart.
- Dev-only surface: hidden behind `?debug=1` on the chat URL or an `ADVISORY_DEBUG_UI=1` server env flag. End users running real demos do not see the panel.

## Non-goals

- LLM prompt / raw-response capture. (Output JSON only; prompts are out of scope for v1.)
- Streaming (SSE / WebSocket). Polling at 1 s is enough for runs that take a handful of seconds.
- Historical run browser (list past runs across sessions). Only the **latest run for the current session** is rendered.
- Analytics dashboards, retention policies, or aggregation. Just raw event rows.
- Production rollout to end users. The panel is dev-only behind a flag.

## Architecture

Four touchpoints:

1. **`advisory_trace_events` table** — one row per stage per run, INSERTed at stage start, UPDATEd at stage end.
2. **`traced(...)` decorator** wrapping each LangGraph node — writes rows around the agent call.
3. **`GET /api/sessions/{token}/trace`** — returns ordered events for the latest run, synthesizing `pending` for stages not yet started.
4. **Chat-page debug panel** — 6 cards, JS polls the trace endpoint every 1 s while the run is active.

```
chat UI (?debug=1)
   │ poll 1s
   ▼
GET /api/sessions/{token}/trace
   │
   ▼
advisory_trace_events  ◄── traced() wrapper INSERT/UPDATE
   ▲
   │
graph.invoke(state)  (state carries trace_run_id)
   │
   ├─ profile_agent   ── traced("profile",  0, extract_profile)
   ├─ retrieval_agent ── traced("retrieve", 1, extract_candidates)
   ├─ conflict_agent  ── traced("conflict", 2, extract_conflicts)
   ├─ reasoning_agent ── traced("reason",   3, extract_reasoning)
   ├─ policy_agent    ── traced("policy",   4, extract_policy)
   └─ explanation     ── traced("explain",  5, extract_explanation)
```

## Components

### 1. `db/migrations/011_advisory_trace_events.sql`

```sql
CREATE TABLE IF NOT EXISTS advisory_trace_events (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES chat_advisory_runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,          -- 'running' | 'completed' | 'failed'
    sequence INTEGER NOT NULL,     -- 0..5
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    output_json JSONB,
    error_text TEXT,
    UNIQUE (run_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_trace_events_run
    ON advisory_trace_events (run_id, sequence);
```

Idempotent — `setup_db` re-applies safely.

### 2. `services/tracing/trace_repository.py`

Thin DAL with three methods:

- `start_event(run_id, stage, sequence) -> event_id` — INSERT row with `status='running'`, `started_at=NOW()`.
- `complete_event(event_id, output_json: dict)` — UPDATE `status='completed'`, `completed_at=NOW()`, `duration_ms`, `output_json`.
- `fail_event(event_id, error_text: str)` — UPDATE `status='failed'`, `completed_at=NOW()`, `duration_ms`, `error_text`.

Uses the existing `ingestion.storage.db_connection.get_connection()` (the same connection helper the rest of `services/chat/repository.py` uses).

### 3. `services/tracing/agent_tracer.py`

```python
STAGE_ORDER = ["profile", "retrieve", "conflict", "reason", "policy", "explain"]

def traced(stage: str, sequence: int, output_extractor):
    def decorator(agent_fn):
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            event_id = trace_repository.start_event(run_id, stage, sequence)
            try:
                result = agent_fn(state)
                trace_repository.complete_event(event_id, output_extractor(result, state))
                return result
            except Exception as exc:
                trace_repository.fail_event(event_id, repr(exc))
                raise
        return wrapped
    return decorator
```

`run_id is None` short-circuits — script runs, test runs, and graph invocations outside chat skip tracing entirely. The wrapper has no behavior beyond timing + persisting; it never mutates `state`.

### 4. `AgentState.trace_run_id`

Add an `Optional[int]` field on `AgentState` (in `state.py`). `advisory_runner.run_advisory_for_session` accepts a new `trace_run_id` argument and sets it on the state. `RunDispatcher._execute` passes its `run_id` through.

### 5. Output extractors (one per stage)

Each extractor returns a `dict` that is `json.dumps`-able. Goal: capture **what that agent produced**, not the whole AgentState.

| Stage | Extractor returns |
|-------|-------------------|
| `profile`  | `{"student_profile": StudentProfile.model_dump()}` |
| `retrieve` | `{"count": N, "candidates": [c.model_dump() for c in candidates]}` |
| `conflict` | `{"resolution_outcomes": [r.model_dump() for r in outcomes]}` |
| `reason`   | `{"eligibility_checks": [...], "ranked_recommendations": [...]}` |
| `policy`   | `{"policy_decision": decision.model_dump(), "filtered_recommendations": [...]}` |
| `explain`  | `{"final_answer": "...", "evidence": [e.model_dump() for e in evidence]}` |

Pydantic models support `.model_dump(mode="json")` — that handles dates, enums, etc. Extractors live in `services/tracing/extractors.py` alongside the wrapper so they evolve together.

### 6. `graph.py` wiring

```python
from services.tracing.agent_tracer import traced
from services.tracing.extractors import (
    extract_profile, extract_candidates, extract_conflicts,
    extract_reasoning, extract_policy, extract_explanation,
)

builder.add_node("profile",  traced("profile",  0, extract_profile)(profile_agent))
builder.add_node("retrieve", traced("retrieve", 1, extract_candidates)(retrieval_agent))
builder.add_node("conflict", traced("conflict", 2, extract_conflicts)(conflict_agent))
builder.add_node("reason",   traced("reason",   3, extract_reasoning)(reasoning_agent))
builder.add_node("policy",   traced("policy",   4, extract_policy)(policy_agent))
builder.add_node("explain",  traced("explain",  5, extract_explanation)(explanation_agent))
```

### 7. API: `GET /api/sessions/{session_token}/trace`

Implemented in `web/routes/chat_api.py`. Steps:

1. Resolve session by token → 404 if missing.
2. Find session's `latest_run_id` → if `None`, return `{"run_id": null, "run_status": null, "events": []}`.
3. Query `chat_advisory_runs.status` for `run_status`.
4. Query `advisory_trace_events` for that `run_id`, sorted by `sequence`.
5. Synthesize a `pending` entry for every stage in `STAGE_ORDER` that has no row yet.

Response:

```json
{
  "run_id": 42,
  "run_status": "running",
  "events": [
    {"stage": "profile",  "sequence": 0, "status": "completed", "duration_ms": 1234,
     "started_at": "2026-05-28T03:15:01Z", "output_json": {...}},
    {"stage": "retrieve", "sequence": 1, "status": "completed", "duration_ms": 2150, ...},
    {"stage": "conflict", "sequence": 2, "status": "running",
     "started_at": "2026-05-28T03:15:04Z", "duration_ms": null, "output_json": null},
    {"stage": "reason",   "sequence": 3, "status": "pending"},
    {"stage": "policy",   "sequence": 4, "status": "pending"},
    {"stage": "explain",  "sequence": 5, "status": "pending"}
  ]
}
```

### 8. Chat-page debug panel

**Gate:** `web/app.py` reads `ADVISORY_DEBUG_UI` env at startup; template receives `debug_ui_enabled`. URL `?debug=1` also enables it client-side (JS reads `URLSearchParams`). The panel renders iff either is true.

**Markup** (`web/templates/chat.html`): new `<aside id="trace-panel">` to the right of the existing summary panel. Six cards rendered up-front with stage names from a static list — initial state all `pending`.

**Card states (CSS classes):**

| State | Left icon | Label area | Background |
|-------|-----------|-----------|-----------|
| `pending`   | `○` grey | "pending" | grey-50 |
| `running`   | `⟳` spinning | "running…" | yellow-50 |
| `completed` | `●` green | `1.2s` / `850ms` | green-50 |
| `failed`    | `✕` red  | "failed"  | red-50 |

Click on a card toggles a `.expanded` class. When expanded:
- `completed` → `<pre>` with `JSON.stringify(output_json, null, 2)`
- `failed` → `<pre>` with `error_text`
- `pending` / `running` → expand is a no-op (or shows "no output yet")

**Polling JS:**

```js
async function pollTrace() {
  const r = await fetch(`/api/sessions/${token}/trace`);
  const data = await r.json();
  renderCards(data.events);
  if (data.run_status === "running" || data.run_status === "queued") {
    setTimeout(pollTrace, 1000);
  }
}
```

Starts when session snapshot reports `status === "running"`. Stops when `run_status` is `completed` or `failed`. The expanded/collapsed state of each card is preserved across re-renders (track by stage name).

## Data flow

```
User sends final message
  → ConversationService.handle_user_message returns should_start_run=True
  → ChatSessionRepository.create_run() inserts chat_advisory_runs row (status=queued)
  → RunDispatcher.submit(... run_id ...) → executor.submit(_execute)
        _execute:
          repo.mark_run_running(run_id)
          run_advisory_for_session(profile, msg, trace_run_id=run_id)
            → state.trace_run_id = run_id
            → graph.invoke(state)
                each wrapped node:
                  trace_repo.start_event(run_id, stage, sequence) → INSERT
                  agent_fn(state)
                  trace_repo.complete_event(event_id, output) → UPDATE
          repo.complete_run(run_id, result, final_answer)

Meanwhile, chat UI (?debug=1):
  every 1s while run_status in {queued, running}:
    GET /api/sessions/{token}/trace
    re-render 6 cards
```

## Error handling

- Agent raises → wrapper writes `fail_event(event_id, repr(exc))` then re-raises. Downstream stages never run, so they remain `pending` in the UI. `RunDispatcher._execute` catches at the outer level and marks the run failed (existing behavior). UI sees `run_status="failed"` and stops polling.
- Trace DB write fails (e.g., connection lost) → log the exception, **swallow it**, let the agent continue. Tracing is observability — it must not break the run. Implemented inside `trace_repository` with a try/except + `logger.warning`.
- Extractor raises (e.g., a stage returned something unexpected) → wrapper catches inside `complete_event` path, writes `output_json={"_extractor_error": repr(exc)}` and marks completed. The run still succeeds.
- Polling endpoint called with unknown token → 404 (matches existing snapshot endpoint).

## Testing

- **Unit:** `tests/services/tracing/test_agent_tracer.py` — wrapper bypasses when `trace_run_id` is None; calls `start_event` + `complete_event` on success; calls `fail_event` and re-raises on exception; extractor errors don't break the run.
- **Unit:** `tests/services/tracing/test_extractors.py` — each extractor returns JSON-serializable dicts for representative state outputs.
- **Integration** (`@pytest.mark.integration`): end-to-end against real Postgres — `run_advisory_for_session(..., trace_run_id=X)` produces 6 rows in `advisory_trace_events` with `sequence` 0..5 and `status='completed'`; `output_json` is non-null for each.
- **API:** `tests/web/test_trace_endpoint.py` — pending synthesis when no rows exist; correct merge of DB rows + synthesized pending entries; 404 for unknown token.
- **UI:** out of scope for automated tests in v1. Manual: open chat with `?debug=1`, send a message that triggers a run, watch cards transition pending → running → completed; click a card to expand JSON.

## Migration & rollout

1. Migration `011_advisory_trace_events.sql` is idempotent (`CREATE TABLE IF NOT EXISTS`). Existing runs without trace rows simply show all 6 cards as `pending` if you re-query their trace endpoint — acceptable for v1.
2. Wrapper is no-op when `trace_run_id is None`, so existing tests, demo scripts, and any non-chat caller of the graph keep working without changes.
3. Panel is hidden by default → no UX change for the chat experience until a dev enables the flag.

## Open questions

None. Confirmed with user 2026-05-28:
- Live view in chat UI ✓
- Dev-only (hidden behind flag) ✓
- Stage name + main output + duration; full JSON on expand ✓
- Persist to DB ✓
- Card UI with collapse/expand + spinner ✓
