# Student Chat E2E Demo Phase Design

## Summary

This design defines the next implementation phase for the advisory-agent repository: make the existing student advisory chat pipeline reachable through the browser in one complete end-to-end flow.

The current codebase already contains the essential backend pieces for this experience:

- anonymous chat session persistence
- profile extraction and merge logic
- follow-up question orchestration
- background advisory run dispatch
- a browser chat shell

The immediate problem is not missing advisory logic. The immediate problem is that the frontend and backend contracts are incomplete and misaligned, so the browser cannot successfully enter the chat flow.

This phase should therefore focus on finishing the public session contract and browser transcript behavior needed to let one student complete at least one advisory cycle from first message to final recommendation.

## Problem Statement

The repository is close to a real student demo, but the chat experience is currently blocked before the advisory logic can be exercised.

Observed codebase state:

- `web/static/js/chat.js` creates sessions through `POST /api/sessions`
- `web/routes/chat_api.py` currently exposes only `POST /api/sessions/{session_token}/messages`
- the browser therefore fails on first message with `404 Not Found` for `/api/sessions`
- `services/chat/session_service.py` already provides the missing anonymous session bootstrap behavior
- `services/chat/conversation_service.py` already handles follow-up versus ready-to-run decisions
- `services/chat/run_dispatcher.py` already executes the advisory pipeline asynchronously and appends the final answer back into session history

That means the next implementation phase should not bypass the existing architecture. It should finish the last missing connection points so the student-facing flow can actually run.

## Goals

- Let a student open the public chat page and start an anonymous session successfully.
- Let the student send an initial freeform message from the browser.
- Return a follow-up question when critical profile fields are missing.
- Trigger one advisory run when the required profile fields are sufficiently complete.
- Show the resulting recommendation in the browser transcript.
- Preserve the current session-oriented architecture and Gemini-backed advisory pipeline.

## Non-Goals

- Building the internal operations console.
- Adding login, user accounts, or multi-device history.
- Replacing the current session model with a stateless chat endpoint.
- Redesigning the follow-up orchestration or advisory graph.
- Polishing the public UI beyond what is needed for the demo path.

## Recommended Approach

The system should complete the existing anonymous session API contract and make the browser transcript session-aware.

This is preferred over adding a temporary direct-to-Gemini endpoint because the advisory flow already depends on session state, profile accumulation, and asynchronous run completion. A bypass would create a second product path that would need to be removed or rewritten immediately afterward.

It is also preferred over pausing for broader refactoring because the current failure is localized: the backend already contains the right services, but the public HTTP surface is incomplete and the browser does not yet display the full conversation lifecycle.

## Architecture

### Overview

The phase should keep the current four-layer structure:

- `browser chat UI`
  - manages local session token, renders transcript, submits messages, and refreshes session state
- `session API`
  - exposes session creation, session fetch, and message submission endpoints
- `conversation and run orchestration layer`
  - decides whether to ask a follow-up question or launch a run
- `existing Gemini-backed advisory core`
  - produces the final advisory recommendation

### Required HTTP Contract

The browser and backend should converge on this public contract:

- `POST /api/sessions`
  - creates an anonymous session
  - returns session metadata and initial assistant welcome message
- `GET /api/sessions/{session_token}`
  - returns current session snapshot and transcript
  - supports page refresh and rehydration
- `POST /api/sessions/{session_token}/messages`
  - accepts one student message
  - returns the immediate conversation result
  - may also trigger a background advisory run

### Execution Flow

1. Student opens the chat page.
2. Browser loads an existing session token from local storage or creates a new session through `POST /api/sessions`.
3. Browser renders the welcome message from the returned session snapshot.
4. Student sends a freeform message.
5. Backend stores the user message, extracts and merges profile state, and decides whether a follow-up question is required.
6. If profile data is incomplete, backend stores and returns one assistant follow-up question.
7. If profile data is complete enough, backend marks the session ready and starts an advisory run in the background.
8. Browser shows an analyzing state and refreshes the session snapshot until the final assistant result is present.
9. Browser renders the final recommendation inside the transcript.

## UI Behavior

### Minimum Demo Experience

The public chat page only needs to support the critical path:

- transcript rendering for assistant and user turns
- local session token persistence
- a message composer
- a loading or analyzing state after submission
- transcript refresh after a follow-up or final result
- a visible failure state if the run fails

### Transcript Rules

- always show the assistant welcome message when a session starts
- append the user message locally only after a successful request or after reloading the transcript from the server
- show the assistant follow-up question as a normal transcript turn
- show the final recommendation as an assistant result turn
- do not assume the response to message submission contains the entire transcript; treat the session snapshot endpoint as the source of truth for rehydration

### Refresh Behavior

Because advisory execution is asynchronous, the browser needs an explicit strategy for seeing the final answer.

Recommended behavior:

- after any message submission that returns `should_start_run = true`, enter an analyzing state
- poll `GET /api/sessions/{session_token}` on a short interval until session status becomes `completed` or `failed`
- stop polling when the final assistant result or failure message is visible

This is preferred over trying to return the full final advisory payload directly from the message endpoint because the current backend already models run execution as asynchronous work.

## Error Handling

### API Errors

- if session creation fails, show a startup error and block message submission
- if message submission fails, keep the input text available so the student can retry
- if session fetch fails during polling, retry a limited number of times before showing a refresh prompt

### Advisory Failures

- if the advisory run fails, preserve the existing transcript
- show the stored assistant error message in chat
- stop the analyzing state

### Contract Safety

- the UI should not assume that `POST /api/sessions` or `GET /api/sessions/{session_token}` are optional
- the backend should return consistent snapshot shapes across session bootstrap and session fetch
- route behavior should match the existing session service models instead of inventing a second response format

## Testing Strategy

This phase should be verified at the contract and critical-path level.

Required coverage:

- API test for `POST /api/sessions`
- API test for `GET /api/sessions/{session_token}`
- API test for existing `POST /api/sessions/{session_token}/messages`
- browser-level smoke test for:
  - first load creates or restores a session
  - first message yields a follow-up when profile data is incomplete
  - subsequent message can trigger an advisory run
  - final recommendation becomes visible after polling

The important boundary is not just “route exists.” It is “a student can complete the public advisory flow without manual backend intervention.”

## Rollout Order

1. Expose session bootstrap and session snapshot endpoints from `web/routes/chat_api.py`.
2. Reuse `AnonymousSessionService` for the new endpoints rather than duplicating session logic.
3. Update the browser chat script to render session snapshots and transcript turns.
4. Add analyzing and polling behavior for asynchronous advisory runs.
5. Add end-to-end tests that prove one complete student conversation path.

## Success Criteria

- `POST /api/sessions` no longer returns `404`
- a new browser session receives a welcome message
- student messages produce follow-up questions when profile state is incomplete
- one complete profile triggers an advisory run
- the final recommendation appears in the browser transcript
- page refresh restores the same session on the same device

## Tradeoffs

### Benefits

- delivers the first real student-usable product slice
- validates the current chat architecture instead of bypassing it
- proves the Gemini-backed advisory pipeline works in the actual browser surface
- keeps future operator-console work separate from the public demo milestone

### Costs

- requires finishing both API contract work and frontend transcript behavior together
- adds polling complexity for asynchronous run completion
- may expose gaps in transcript serialization or run-status persistence that were not visible in backend-only testing

## Open Questions

No blocking product questions remain for this phase. The remaining work is implementation and verification against the existing architecture.
