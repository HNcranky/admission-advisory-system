# Conversation History (3 turns) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed the last 3 user/assistant turns into the intent router and knowledge QA so the assistant can resolve shortened follow-ups and pronouns.

**Architecture:** A pure `build_history_context` formatter turns stored `ChatMessageRecord`s into a capped text block. `ConversationService.handle_user_message` fetches prior messages once per turn (before appending the current one) and threads the block into the intent router and the knowledge-QA call sites. The knowledge QA service already accepts `conversation_context`; only data needs supplying.

**Tech Stack:** Python 3, Pydantic v2, pytest. No DB migration, no schema change.

**Spec:** `docs/superpowers/specs/2026-06-09-conversation-history-design.md`

**Scope note:** Tasks 1–4 cover the intent router, the direct knowledge-QA path, and the inline hybrid fan-out. The **async** (profile-complete) hybrid run path is deferred — see "Deferred" at the end; full profile already supplies rich structured context there, so it is lower value.

---

### Task 1: History builder (pure function)

**Files:**
- Create: `services/chat/history.py`
- Test: `tests/services/chat/test_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/services/chat/test_history.py
from services.chat.history import build_history_context
from services.chat.models import ChatMessageRecord


def _msg(role, content, kind="chat"):
    return ChatMessageRecord(
        id=1, session_token="t", role=role, kind=kind, content=content
    )


def test_empty_returns_empty_string():
    assert build_history_context([]) == ""


def test_formats_user_and_assistant_lines():
    msgs = [_msg("user", "chào"), _msg("assistant", "xin chào")]
    out = build_history_context(msgs)
    assert "Người dùng: chào" in out
    assert "Trợ lý: xin chào" in out


def test_keeps_only_last_three_pairs():
    msgs = []
    for i in range(5):
        msgs.append(_msg("user", f"u{i}"))
        msgs.append(_msg("assistant", f"a{i}"))
    out = build_history_context(msgs)
    # 5 pairs in, only last 3 pairs (u2..u4) survive
    assert "u1" not in out
    assert "u2" in out
    assert "u4" in out


def test_truncates_long_message_with_ellipsis():
    long = "x" * 800
    out = build_history_context([_msg("user", long)], max_chars=500)
    assert "…" in out
    assert "x" * 501 not in out


def test_skips_non_user_assistant_roles():
    msgs = [_msg("system", "secret"), _msg("user", "hỏi"), _msg("assistant", "đáp")]
    out = build_history_context(msgs)
    assert "secret" not in out
    assert "hỏi" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_history.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.chat.history'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/chat/history.py
"""Format recent chat turns into a compact text block for LLM prompts.

Pure formatting — no DB, no IO. The caller fetches messages (via
``repository.list_message``) and passes them in chronological order.
"""

_ROLE_LABELS = {"user": "Người dùng", "assistant": "Trợ lý"}


def build_history_context(messages, max_pairs: int = 3, max_chars: int = 500) -> str:
    """Render the last ``max_pairs`` user/assistant turns as labelled lines.

    - Only ``user``/``assistant`` roles are kept (other roles are skipped).
    - Keeps the last ``max_pairs * 2`` such messages.
    - Each message body is truncated to ``max_chars`` (… appended) so one long
      message cannot blow up the prompt — the single context-window guard.
    - Empty input → "" (caller treats this as "no history").
    """
    kept = [m for m in messages if m.role in _ROLE_LABELS]
    kept = kept[-(max_pairs * 2):]
    lines = []
    for m in kept:
        text = m.content or ""
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        lines.append(f"{_ROLE_LABELS[m.role]}: {text}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_history.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add services/chat/history.py tests/services/chat/test_history.py
git commit -m "feat(chat): add build_history_context formatter"
```

---

### Task 2: Intent router accepts history

**Files:**
- Modify: `services/chat/intent_router.py` (method `classify` line 206, `_build_user_prompt` line 249)
- Test: `tests/services/chat/test_intent_router.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/services/chat/test_intent_router.py
def test_build_user_prompt_includes_history_block():
    history = "Người dùng: học phí UET?\nTrợ lý: 15 triệu/năm"
    prompt = _prompt_router()._build_user_prompt(
        "còn HUST thì sao", ChatProfileState(), history=history
    )
    assert "Lịch sử hội thoại gần đây" in prompt
    assert "15 triệu/năm" in prompt


def test_build_user_prompt_omits_history_block_when_empty():
    prompt = _prompt_router()._build_user_prompt("msg", ChatProfileState(), history="")
    assert "Lịch sử hội thoại" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py -k history -q`
Expected: FAIL with `TypeError: _build_user_prompt() got an unexpected keyword argument 'history'`

- [ ] **Step 3: Write minimal implementation**

In `services/chat/intent_router.py`, change `classify` (line 206) to accept and forward `history`:

```python
    def classify(self, message: str, profile_state: ChatProfileState, history: str = "") -> IntentResult:
        try:
            if hasattr(self._gateway, "is_available") and not self._gateway.is_available():
                return self._fallback_classify(message)
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="intent_router",
                    task_type="intent_classification",
                    system_prompt=INTENT_SYSTEM_PROMPT,
                    user_prompt=self._build_user_prompt(message, profile_state, history),
                    output_mode="json",
                    temperature=0.0,
                )
            )
            if not result.parsed_data:
                return self._fallback_classify(message)
            return IntentResult.model_validate(result.parsed_data)
        except Exception as exc:
            logger.warning("intent classification failed, using fallback route: %r", exc)
            return self._fallback_classify(message)
```

Change `_build_user_prompt` (line 249) to accept `history` and prepend the block:

```python
    def _build_user_prompt(self, message: str, profile_state: ChatProfileState, history: str = "") -> str:
        schools = (
            ", ".join(profile_state.preferred_schools)
            if profile_state.preferred_schools
            else "chưa có"
        )
        majors = (
            ", ".join(profile_state.preferred_majors)
            if profile_state.preferred_majors
            else "chưa có"
        )
        prefix = (
            f"Lịch sử hội thoại gần đây:\n{history}\n\n" if history else ""
        )
        return (
            f"{prefix}"
            f'Tin nhắn: "{message}"\n\n'
            f"Profile hiện tại:\n"
            f"- Trường quan tâm: {schools}\n"
            f"- Ngành quan tâm: {majors}\n"
            f"- Điểm số: {profile_state.total_score or 'chưa có'}\n"
            f"- Khối thi: {profile_state.subject_combination or 'chưa có'}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py -q`
Expected: PASS (all existing + 2 new; default `history=""` keeps old tests green)

- [ ] **Step 5: Commit**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router.py
git commit -m "feat(chat): intent router accepts conversation history"
```

---

### Task 3: Thread history through handle_user_message → intent router + direct knowledge QA

**Files:**
- Modify: `services/chat/conversation_service.py` (`handle_user_message` line 67, `_handle_knowledge_qa` line 310)
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Write the failing test**

Inspect the existing `tests/services/chat/test_conversation_service.py` for its fake repository/intent-router fixtures and reuse them. Add a test asserting the intent router receives a non-empty history when prior messages exist. Pattern (adapt names to the existing fakes in that file):

```python
def test_handle_user_message_passes_history_to_intent_router(service_with_history):
    """When prior turns exist, the intent router is called with a history block
    containing the previous assistant answer."""
    service, fake_router = service_with_history  # prior messages already seeded
    service.handle_user_message("tok", "còn HUST thì sao")
    assert fake_router.last_history  # non-empty string
    assert "Trợ lý:" in fake_router.last_history
```

If the existing file has no reusable fake that records `classify` arguments, add a minimal one in the test file:

```python
class RecordingRouter:
    def __init__(self):
        self.last_history = None

    def classify(self, message, profile_state, history=""):
        self.last_history = history
        from services.chat.intent_router import IntentResult
        return IntentResult(route="CLARIFICATION")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -k history -q`
Expected: FAIL (router receives `""` because history is not yet threaded)

- [ ] **Step 3: Write minimal implementation**

In `services/chat/conversation_service.py`, add the import near the top with the other `services.chat` imports:

```python
from services.chat.history import build_history_context
```

In `handle_user_message` (line 67), fetch prior messages **before** appending the current one, build the block, and forward it. Replace the opening of the method:

```python
    def handle_user_message(self, session_token: str, content: str) -> ConversationTurnResult:
        # Build history from turns BEFORE this one — fetch prior to appending so
        # the message being processed is excluded.
        history_ctx = build_history_context(self.repository.list_message(session_token))
        self.repository.append_message(session_token, "user", content, "user_message")
        session = self.repository.get_session_by_token(session_token)
        profile_state = self.repository.get_profile_state(session_token)
        flow_state = self.repository.get_flow_state(session_token)
```

Update the intent-router call (line 105) to pass history:

```python
        intent = self.intent_router.classify(content, profile_state, history=history_ctx)
```

Update the knowledge-QA dispatch (line 110) to forward history:

```python
        if intent.route == "KNOWLEDGE_QA":
            return self._handle_knowledge_qa(session_token, content, intent, profile_state, flow_state, session_status, history_ctx)
```

Update `_handle_knowledge_qa` (line 310) to accept and use it:

```python
    def _handle_knowledge_qa(self, session_token, content, intent, profile_state, flow_state, session_status, history_ctx=""):
        # Resolve school: router value first, else the student's top preferred school.
        school = intent.school or (
            profile_state.preferred_schools[0] if profile_state.preferred_schools else None
        )

        result = None
        try:
            result = self.knowledge_qa.answer(
                question=content,
                school=school,
                topic=intent.topic,
                conversation_context=history_ctx,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -q`
Expected: PASS (new history test + all existing conversation-service tests)

- [ ] **Step 5: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat(chat): thread history into intent router and knowledge QA"
```

---

### Task 4: Inline hybrid fan-out forwards history

**Files:**
- Modify: `services/chat/knowledge_fanout.py` (`run_knowledge_fanout` line 26)
- Modify: `services/chat/conversation_service.py` (`handle_user_message` hybrid dispatch line 112, `_handle_hybrid` line 351)
- Test: `tests/services/chat/test_knowledge_fanout.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/services/chat/test_knowledge_fanout.py
from services.chat.knowledge_fanout import run_knowledge_fanout
from services.chat.intent_router import IntentResult


class _CtxRecordingQA:
    def __init__(self):
        self.last_ctx = None

    def answer(self, question, school, topic, conversation_context=""):
        self.last_ctx = conversation_context
        from services.knowledge.models import KnowledgeQAResult
        return KnowledgeQAResult(has_data=False, confidence=0.0)


def test_run_knowledge_fanout_forwards_conversation_context():
    qa = _CtxRecordingQA()
    intent = IntentResult(route="HYBRID", topic="tuition", school="VNU-UET")
    run_knowledge_fanout(qa, intent, "ngành đó học phí?", conversation_context="Trợ lý: ...")
    assert qa.last_ctx == "Trợ lý: ..."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_fanout.py -k forwards -q`
Expected: FAIL with `TypeError: run_knowledge_fanout() got an unexpected keyword argument 'conversation_context'`

- [ ] **Step 3: Write minimal implementation**

In `services/chat/knowledge_fanout.py`, add the parameter and forward it (line 26 + the `.answer` call line 35):

```python
def run_knowledge_fanout(knowledge_qa, intent, content, school_fallback=None, conversation_context="") -> list:
    """Call the single-school KnowledgeQA once per (school, topic) pair.

    Each call swallows its own error → a no-data KnowledgeBlock; siblings survive.
    """
    blocks = []
    for school in _resolve_schools(intent, school_fallback):
        for topic in _resolve_topics(intent):
            try:
                result = knowledge_qa.answer(
                    question=content, school=school, topic=topic,
                    conversation_context=conversation_context,
                )
```

In `services/chat/conversation_service.py`, forward history into the hybrid handler. Update the hybrid dispatch (line 112):

```python
        if intent.route == "HYBRID":
            return self._handle_hybrid(session_token, content, intent, profile_state, flow_state, session_status, history_ctx)
```

Update `_handle_hybrid` (line 351) signature and the inline fan-out call (line 372):

```python
    def _handle_hybrid(self, session_token, content, intent, profile_state, flow_state, session_status, history_ctx=""):
        missing = missing_critical_slots(profile_state)

        if not missing:
            # Profile complete → dispatch an async hybrid run (advisory ∥ knowledge → synthesis).
            placeholder = (
                "Câu hỏi này cần đối chiếu cả dữ liệu tuyển sinh lẫn thông tin trường, "
                "mình đang tổng hợp, bạn chờ một chút nhé."
            )
            self.repository.append_message(session_token, "assistant", placeholder, "assistant_hybrid_pending")
            return ConversationTurnResult(
                session_status=session_status,
                assistant_message=placeholder,
                should_start_run=True,
                run_kind="hybrid",
                hybrid_intent=intent.model_dump(),
                profile_state=profile_state,
            )

        # Profile incomplete → answer the knowledge half inline, ask the next advisory follow-up.
        school_fallback = profile_state.preferred_schools[0] if profile_state.preferred_schools else None
        blocks = run_knowledge_fanout(self.knowledge_qa, intent, content, school_fallback, conversation_context=history_ctx)
        body = format_knowledge_blocks(blocks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_fanout.py tests/services/chat/test_conversation_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/knowledge_fanout.py services/chat/conversation_service.py tests/services/chat/test_knowledge_fanout.py
git commit -m "feat(chat): forward history through inline hybrid knowledge fan-out"
```

---

### Task 5: Full chat suite regression

**Files:** none (verification only)

- [ ] **Step 1: Run the chat + intent + knowledge suites**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat -q`
Expected: PASS (all green, no regressions from the default-`""` parameters)

- [ ] **Step 2: Run the knowledge QA integration test (needs Docker DB up)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_qa_integration.py -q`
Expected: PASS

- [ ] **Step 3: Commit (only if any fixup was needed)**

```bash
git commit -am "test(chat): conversation history regression pass" || echo "nothing to commit"
```

---

## Deferred (out of scope for this plan)

**Async hybrid run path (profile-complete `_handle_hybrid`).** When the profile is
complete, `_handle_hybrid` dispatches a background hybrid run (`run_kind="hybrid"`)
rather than calling knowledge QA inline. Threading history there requires passing
the block through the run dispatcher / `ThreadPoolExecutor` into the async knowledge
fan-out (or re-fetching history inside the run via the repository). This is deferred
because a complete profile already supplies rich structured context to that path, so
the marginal benefit of raw history is low. Revisit if follow-up resolution proves
weak specifically on the profile-complete hybrid branch.

## Self-review notes

- Spec coverage: history builder (Task 1), intent router (Task 2), direct knowledge
  QA (Task 3), inline hybrid (Task 4) — all spec call sites except the explicitly
  deferred async hybrid path. Regression in Task 5.
- All new parameters default to `""`, preserving existing signatures and tests.
- `ChatMessageRecord` field names (`role`, `kind`, `content`) match
  `services/chat/models.py`. `KnowledgeQAResult(has_data=, confidence=)` matches
  `services/knowledge/models.py`.
