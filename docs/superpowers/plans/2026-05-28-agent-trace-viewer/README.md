# Agent Trace Viewer — Plan Index

**Spec:** [`docs/superpowers/specs/2026-05-28-agent-trace-viewer-design.md`](../../specs/2026-05-28-agent-trace-viewer-design.md)

## Slices

Each slice ends with a green test suite and a self-contained, reviewable commit history. Slices run **in order** because each builds on the previous.

| # | Slice | What ships | DB? | UI? |
|---|---|---|---|---|
| [01](./01-trace-events-foundation.md) | Trace events foundation | Migration `011_advisory_trace_events`, `TraceRepository`, `AgentState.trace_run_id`, run_id plumbing through `RunDispatcher` → `advisory_runner` | New table + 1 column on AgentState | — |
| [02](./02-tracer-wrapper-and-extractors.md) | Tracer wrapper + extractors | `traced()` decorator, 6 stage extractors, wire into `graph.py` | Writes 6 rows per run | — |
| [03](./03-trace-api-endpoint.md) | Trace API endpoint | `GET /api/sessions/{token}/trace` with pending synthesis | Reads `advisory_trace_events` | — |
| [04](./04-debug-panel-ui.md) | Debug panel UI | 6 cards (pending/running/completed/failed), click-to-expand JSON, `?debug=1` gate, polling | — | Yes |

## Conventions for every slice

- **TDD:** write failing test → run → minimal code → run → commit. Each slice plan spells the steps out.
- **DB layer:** follow the existing `services/chat/repository.py` pattern — `connection_factory` injection, manual `cursor()` / `commit()` / `close()`. Tests use the `FakeConnection`/`FakeCursor` pattern from `tests/services/chat/test_repository.py`.
- **Migrations:** idempotent (`CREATE TABLE IF NOT EXISTS`). Verify by running `python -m db.setup_db` twice in a row.
- **Tests:**
  - Unit tests in `tests/services/tracing/...` (mirror source layout).
  - Integration tests marked `@pytest.mark.integration` — they hit a real Postgres (the one from `docker-compose.yml`).
  - Web tests in `tests/web/...`.
- **Commits:** small, conventional-style messages (`feat:`, `test:`, `chore:`). Commit after each green test, not in batches.
