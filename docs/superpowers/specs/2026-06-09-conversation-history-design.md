# Conversation history (3 turns) — Design

**Date:** 2026-06-09
**Status:** Approved (design)
**Scope:** Wire recent conversation history into the intent router and knowledge QA so the assistant can resolve follow-up questions and pronouns.

## Problem

The chat system persists every user/assistant message in `chat_messages`, but
**never feeds prior turns to the LLM**. Each inference call sees only the current
message plus the accumulated structured profile. As a result:

- The intent router (`services/chat/intent_router.py`) misreads shortened
  follow-ups ("còn trường kia thì sao?") because it classifies a single message
  in isolation.
- Knowledge QA (`services/knowledge/qa_service.py`) cannot resolve pronouns
  ("ngành đó học phí bao nhiêu?") — its `conversation_context` parameter already
  exists but is hardcoded to `""` at the call site
  (`services/chat/conversation_service.py`).

The hooks to fix this are already present; they are simply not wired.

## Non-goals

- No history for the advisory pipeline. It reasons over the **structured**
  profile (scores, combination, majors); raw transcript would add noise. The
  `AgentState.chat_history` field stays unused.
- No token counting / dynamic token budgeting. Gemini's context window is far
  from the limit at this scale; a fixed turn cap plus a per-message char cap is
  sufficient.
- No cross-session (long-term) memory. Sessions are anonymous and session-scoped.

## Design

### Component 1 — History builder (pure function)

New module `services/chat/history.py`:

```python
def build_history_context(messages, max_pairs: int = 3, max_chars: int = 500) -> str
```

- Input: a list of `ChatMessageRecord` (as returned by
  `repository.list_message`), in chronological order.
- Keep only conversational user/assistant turns. Take the **last
  `max_pairs * 2 = 6` messages**.
- Truncate each message's content to `max_chars` (≈500) characters — the single
  context-window guard. Append `…` when truncated.
- Format each line as `Người dùng: <text>` / `Trợ lý: <text>`.
- Return `""` for empty input (no history → unchanged legacy behavior).

This function is pure (no DB, no IO) and is the primary unit-test target.

**Role filtering:** the builder keeps messages whose role is `user` or
`assistant`. The stored `kind` (e.g. `user_message`, `assistant_validation`) is
not filtered on — any assistant reply is valid context. Roles other than
user/assistant are skipped.

### Component 2 — Fetch history per turn

In `ConversationService.handle_user_message`
(`services/chat/conversation_service.py`):

- Fetch `prior = self.repository.list_message(session_token)` **before** the
  existing `append_message(... "user" ...)` call (currently line 68). Fetching
  before the append naturally excludes the message being processed this turn.
- Build `history_ctx = build_history_context(prior)` once and thread it into the
  intent router and knowledge QA call sites below.

### Component 3 — Intent router

`IntentRouter.classify(message, profile_state, history: str = "")`:

- Add the optional `history` parameter (default `""` keeps the existing
  signature behavior and existing callers/tests working).
- In `_build_user_prompt`, when `history` is non-empty, prepend a block:
  ```
  Lịch sử hội thoại gần đây:
  <history_ctx>

  ```
  before the current `Tin nhắn: "..."` line.
- Update the call site in `handle_user_message` to pass `history_ctx`.

### Component 4 — Knowledge QA

The QA service already accepts `conversation_context` and already renders it
(`_build_user_prompt`, line 139). Only the call sites need data:

- `_handle_knowledge_qa` → pass `conversation_context=history_ctx`.
- `_handle_hybrid` → pass `conversation_context=history_ctx` (hybrid also runs
  knowledge QA).

`history_ctx` is threaded down from `handle_user_message` into these handlers.

## Error handling / degradation

- Empty history or a failed `list_message` fetch → `history_ctx = ""`, which is
  exactly the current behavior. No new failure point is introduced.
- The per-message char cap bounds prompt growth even for pathological long
  messages.

## Testing

**Unit (`tests/...` for `build_history_context`):**
- Last 3 pairs only (given 5 pairs, returns 6 messages).
- Per-message truncation at `max_chars` with ellipsis.
- Empty list → `""`.
- Non user/assistant roles skipped.

**Integration:**
- Intent router and knowledge QA receive a non-empty `conversation_context` /
  history block when prior turns exist.
- A follow-up with a pronoun ("ngành đó học phí bao nhiêu?") routes to
  KNOWLEDGE_QA and the QA prompt contains the prior turn.

## Files touched

- `services/chat/history.py` — new (history builder).
- `services/chat/intent_router.py` — add `history` param + prompt block.
- `services/chat/conversation_service.py` — fetch history, thread into intent
  router + knowledge QA / hybrid handlers.
- `services/knowledge/qa_service.py` — no change needed (already supports
  `conversation_context`); listed only as the consumer.

No DB migration, no schema change.
