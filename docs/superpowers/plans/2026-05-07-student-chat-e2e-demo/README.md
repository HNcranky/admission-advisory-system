# Student Chat E2E Demo Plan Index

This spec is split into three consecutive plans so the unfinished student demo work can be completed in small, verifiable slices without redoing the earlier chat architecture work.

## Execution Order

1. `01-session-api-and-transcript-snapshots.md`
   - Finish the missing anonymous session API surface.
   - Fix transcript snapshot retrieval so browser refresh and polling have a reliable backend source of truth.
2. `02-browser-transcript-and-polling.md`
   - Upgrade the public chat shell from a send-only form into a snapshot-driven UI.
   - Render transcript, profile summary, status states, and background-run polling.
3. `03-demo-hardening-and-critical-path-verification.md`
   - Add stale-session recovery, recommendation-panel rendering, and a deterministic end-to-end demo-flow smoke test.

## Shared File Map

- `services/chat/repository.py`
  - Session transcript fetch and run-status persistence.
- `services/chat/session_service.py`
  - Session bootstrap and session snapshot retrieval.
- `web/routes/chat_api.py`
  - Session create/read/message endpoints.
- `web/templates/chat.html`
  - Student-facing chat shell markup.
- `web/static/js/chat.js`
  - Browser session persistence, transcript rendering, and polling behavior.
- `web/static/css/chat.css`
  - Minimal product styling for transcript, status, and summary surfaces.
- `tests/services/chat/`
  - Repository and session-service regression coverage.
- `tests/web/`
  - Route and page tests for the web layer.
- `tests/e2e/`
  - End-to-end demo smoke coverage.

## Merge Boundaries

- Plan 1 must merge before Plan 2 starts because the browser needs `POST /api/sessions` and `GET /api/sessions/{session_token}`.
- Plan 2 must leave all existing chat service and route tests green while making the public page reflect server state.
- Plan 3 must verify the student critical path without introducing a second demo-only backend path.
