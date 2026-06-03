# Student Advisory Chat V1 Plan Index

This spec is split into five sequential plans so each slice can ship, pass tests, and leave the repository in a usable state before the next phase starts.

## Execution Order

1. `01-platform-and-schema-foundation.md`
   - Add the FastAPI app skeleton, dependency baseline, chat storage schema, and repository primitives.
   - No user-visible chat behavior yet.
2. `02-anonymous-session-api.md`
   - Add anonymous session lifecycle, transcript persistence, and HTTP endpoints for session bootstrap.
   - Still no profile follow-up logic or advisory runs.
3. `03-profile-state-and-follow-up-orchestration.md`
   - Add profile-state extraction, missing-slot evaluation, and one-question-at-a-time follow-up handling.
   - This phase may mark a session as ready, but it must not launch advisory runs yet.
4. `04-asynchronous-advisory-runs.md`
   - Reuse the existing advisory graph with seeded profile state, add run persistence, and dispatch background analysis.
   - No second recommendation engine is allowed in this phase.
5. `05-public-chat-ui.md`
   - Add the student/parent-facing chat page, static assets, session persistence in the browser, and product-level smoke coverage.

## Shared File Map

- `web/`
  - FastAPI application, page routes, API routes, templates, and static assets.
- `services/chat/`
  - Anonymous session models, repositories, follow-up logic, conversation orchestration, and run dispatch.
- `db/migrations/009_chat_sessions.sql`
  - Session, message, and chat-specific advisory run tables.
- `tests/web/`
  - Route and page tests for the web layer.
- `tests/services/chat/`
  - Repository, profile-state, conversation, and run-dispatch tests.
- `tests/e2e/`
  - End-to-end HTTP flows that preserve the current advisory behavior while adding the chat product layer.

## Merge Boundaries

- Plan 1 must merge before Plan 2 starts because every later phase depends on the app and schema foundation.
- Plan 2 must leave all existing advisory tests green and add isolated session API coverage.
- Plan 3 may modify chat-facing services and routes, but it must not execute the advisory graph.
- Plan 4 must reuse `graph.py`, `state.py`, and the existing agents instead of building a parallel advisor pipeline.
- Plan 5 must keep all prior API and service tests green while adding the public UI shell.
