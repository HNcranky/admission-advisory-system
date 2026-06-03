# Phase 1 — Plan 3: ConversationService Routing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `IntentRouter` into `ConversationService` — add a routing dispatcher, split each branch into a private handler, and implement flow-state tracking so the agent re-asks the pending advisory question **on the first off-topic turn**.

**Architecture:** `handle_user_message` becomes a thin dispatcher: it reads the session record (for status), profile state, and flow state, classifies intent, then delegates to one of four handlers. `_handle_advisory` keeps all existing extract→merge→follow-up logic and adds a single `update_flow_state` side-effect. The off-topic handlers (`_handle_knowledge_qa`, `_handle_out_of_scope`, `_handle_clarification`) **never mutate flow state or profile** — they only read flow state to decide whether to append the pending question. `_append_return_prompt` keys off `active_flow == "ADVISORY_FLOW" and pending_question` (not a separate flag), which is why the re-ask fires on the very first detour. `HYBRID` is routed to `_handle_knowledge_qa` in Phase 1 (a HYBRID question is well-formed and needs knowledge data — answering "no data yet" beats asking the user to clarify).

**Tech Stack:** Python 3.11, Pydantic v2, pytest

**Depends on:** Plan 1 (FlowState + `get_flow_state`/`update_flow_state`) and Plan 2 (IntentRouter + IntentResult) complete.

**Spec:** `docs/superpowers/specs/2026-05-30-phase1-intent-router-flow-state-design.md` (§5 ConversationService, §6 Error Handling, Acceptance Criteria)

---

### Task 1: Test scaffolding — FakeRepository (flow + session) + FakeIntentRouter

**Files:**
- Modify: `tests/services/chat/test_conversation_service.py` (replace whole file)

- [ ] **Step 1: Replace the test file**

The existing file has a `FakeRepository` + one test. Replace the entire `tests/services/chat/test_conversation_service.py` with the version below — it adds `flow_state`, `get_flow_state`, `update_flow_state`, `get_session_by_token`, and a `FakeIntentRouter`. The original test is preserved verbatim at the bottom.

```python
from types import SimpleNamespace

from agents.models import StudentProfile
from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, FlowState
from services.chat.intent_router import IntentResult


class FakeRepository:
    def __init__(self):
        self.profile_state = ChatProfileState()
        self.flow_state = FlowState()
        self.messages = []
        self.status = "collecting_profile"

    def append_message(self, session_token, role, content, kind="chat"):
        self.messages.append((role, kind, content))

    def get_session_by_token(self, session_token):
        # Only .status is read by ConversationService.
        return SimpleNamespace(session_token=session_token, status=self.status)

    def get_profile_state(self, session_token):
        return self.profile_state

    def update_profile_state(self, session_token, profile_state, status):
        self.profile_state = profile_state
        self.status = status
        return profile_state

    def get_flow_state(self, session_token):
        return self.flow_state

    def update_flow_state(self, session_token, flow_state):
        self.flow_state = flow_state


class FakeIntentRouter:
    def __init__(self, result: IntentResult):
        self._result = result

    def classify(self, message, profile_state):
        return self._result


def _make_service(intent_result=None, profile=None, flow=None, status=None, extract=None):
    """Build a ConversationService backed by fakes. Returns (service, repo)."""
    repo = FakeRepository()
    if profile is not None:
        repo.profile_state = profile
    if flow is not None:
        repo.flow_state = flow
    if status is not None:
        repo.status = status
    router = FakeIntentRouter(intent_result or IntentResult(route="ADVISORY_FLOW"))
    service = ConversationService(
        repository=repo,
        extract_profile=extract or (lambda text: StudentProfile()),
        intent_router=router,
    )
    return service, repo


# ─── existing test (unchanged) ───────────────────────────────────────────────

def test_handle_user_message_returns_follow_up_when_score_missing():
    repo = FakeRepository()
    service = ConversationService(
        repository=repo,
        extract_profile=lambda text: StudentProfile(
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
        intent_router=FakeIntentRouter(IntentResult(route="ADVISORY_FLOW")),
    )

    result = service.handle_user_message("session-123", "Em muon hoc CNTT tai Ha Noi nam 2026")

    assert result.session_status == "collecting_profile"
    assert result.should_start_run is False
    assert "bao nhiêu" in result.assistant_message.lower()
```

> Note: the original test now passes `intent_router=FakeIntentRouter(...)` so it doesn't construct a real `IntentRouter` (which would call `build_default_gateway`). This is the only change to the original test.

- [ ] **Step 2: Run — expect a failure on the constructor**

Run: `pytest tests/services/chat/test_conversation_service.py -v`
Expected: `TypeError: ConversationService.__init__() got an unexpected keyword argument 'intent_router'` (the constructor is wired in Task 2).

- [ ] **Step 3: Commit**

```bash
git add tests/services/chat/test_conversation_service.py
git commit -m "test: extend fakes with flow_state + session + FakeIntentRouter"
```

---

### Task 2: Wire IntentRouter into the constructor

**Files:**
- Modify: `services/chat/conversation_service.py` (imports + `__init__`)

- [ ] **Step 1: Add a failing injection test**

Append to `tests/services/chat/test_conversation_service.py`:

```python
def test_conversation_service_accepts_intent_router_injection():
    repo = FakeRepository()
    router = FakeIntentRouter(IntentResult(route="ADVISORY_FLOW"))
    service = ConversationService(
        repository=repo,
        extract_profile=lambda text: StudentProfile(),
        intent_router=router,
    )
    assert service.intent_router is router
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/services/chat/test_conversation_service.py::test_conversation_service_accepts_intent_router_injection -v`
Expected: `TypeError: ... unexpected keyword argument 'intent_router'`

- [ ] **Step 3: Update imports and constructor**

Open `services/chat/conversation_service.py`. Replace the import block (lines 1-5) and the `__init__` (lines 8-9) so the top of the file reads:

```python
from services import build_default_gateway
from services.chat.intent_router import IntentRouter
from services.chat.models import ConversationTurnResult
from services.chat.profile_state_service import merge_profile_state, next_follow_up_question
from services.chat.repository import ChatSessionRepository
from services.profile_inference_service import build_profile_with_gateway


class ConversationService:
    def __init__(self, repository=None, extract_profile=None, intent_router=None):
        self.repository = repository or ChatSessionRepository()
        self.extract_profile = extract_profile or self._extract_profile
        self.intent_router = intent_router or IntentRouter()

    def _extract_profile(self, text: str):
        gateway = build_default_gateway()
        return build_profile_with_gateway(text, gateway)
```

Leave `handle_user_message` (the old linear version) untouched for now — it still works because the original test passes a fake router but the old method ignores it. It is replaced in Task 4.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/services/chat/test_conversation_service.py -v`
Expected: 2 passed (injection test + original follow-up test)

- [ ] **Step 5: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat: add intent_router injection to ConversationService"
```

---

### Task 3: _append_return_prompt helper (off-by-one fix lives here)

**Files:**
- Modify: `services/chat/conversation_service.py` (add method)
- Modify: `tests/services/chat/test_conversation_service.py` (extend)

- [ ] **Step 1: Add failing tests**

Append to `tests/services/chat/test_conversation_service.py`:

```python
def test_append_return_prompt_adds_pending_question_when_in_advisory_flow():
    service, _ = _make_service()
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Bạn học khối gì?")
    result = service._append_return_prompt("Xin lỗi, ngoài phạm vi.", flow)
    assert "Bạn học khối gì?" in result
    assert "Xin lỗi, ngoài phạm vi." in result
    assert "Nhân tiện" in result


def test_append_return_prompt_skips_when_no_active_flow():
    service, _ = _make_service()
    flow = FlowState(active_flow=None, pending_question="Bạn học khối gì?")
    result = service._append_return_prompt("Xin lỗi, ngoài phạm vi.", flow)
    assert result == "Xin lỗi, ngoài phạm vi."


def test_append_return_prompt_skips_when_no_pending_question():
    service, _ = _make_service()
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question=None)
    result = service._append_return_prompt("Xin lỗi, ngoài phạm vi.", flow)
    assert result == "Xin lỗi, ngoài phạm vi."
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/services/chat/test_conversation_service.py -k "append_return_prompt" -v`
Expected: `AttributeError: 'ConversationService' object has no attribute '_append_return_prompt'`

- [ ] **Step 3: Add the helper**

Append to the `ConversationService` class in `services/chat/conversation_service.py`:

```python
    def _append_return_prompt(self, message: str, flow_state) -> str:
        """Re-ask the pending advisory question iff the user is mid-advisory-flow.

        Keyed off active_flow + pending_question (both persisted during the prior
        advisory turn), so the re-ask fires on the FIRST off-topic turn — no flag
        that gets set only after the response is built.
        """
        if flow_state.active_flow == "ADVISORY_FLOW" and flow_state.pending_question:
            return f"{message}\n\nNhân tiện, {flow_state.pending_question}"
        return message
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/services/chat/test_conversation_service.py -k "append_return_prompt" -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat: add _append_return_prompt (re-ask on first detour)"
```

---

### Task 4: Routing dispatcher + four branch handlers

**Files:**
- Modify: `services/chat/conversation_service.py` (replace `handle_user_message`, add handlers + `_TOPIC_LABELS`)
- Modify: `tests/services/chat/test_conversation_service.py` (extend)

- [ ] **Step 1: Add failing tests for the off-topic branches**

Append to `tests/services/chat/test_conversation_service.py`:

```python
def test_handle_out_of_scope_returns_polite_decline():
    service, _ = _make_service(intent_result=IntentResult(route="OUT_OF_SCOPE"))
    result = service.handle_user_message("tok", "thời tiết hôm nay")
    assert result.should_start_run is False
    assert "ngoài phạm vi" in result.assistant_message


def test_handle_out_of_scope_preserves_session_status():
    service, _ = _make_service(intent_result=IntentResult(route="OUT_OF_SCOPE"), status="ready")
    result = service.handle_user_message("tok", "thời tiết hôm nay")
    assert result.session_status == "ready"


def test_handle_clarification_returns_clarification_request():
    service, _ = _make_service(intent_result=IntentResult(route="CLARIFICATION"))
    result = service.handle_user_message("tok", "ý bạn là gì")
    assert result.should_start_run is False
    assert "rõ hơn" in result.assistant_message


def test_no_reask_when_not_in_advisory_flow():
    service, _ = _make_service(
        intent_result=IntentResult(route="OUT_OF_SCOPE"),
        flow=FlowState(),  # active_flow=None
    )
    result = service.handle_user_message("tok", "thời tiết hôm nay")
    assert "Nhân tiện" not in result.assistant_message
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/services/chat/test_conversation_service.py -k "out_of_scope or clarification or no_reask" -v`
Expected: failures — the old `handle_user_message` ignores intent and runs advisory logic, so assertions on the decline/clarification text fail.

- [ ] **Step 3: Replace handle_user_message and add handlers**

Open `services/chat/conversation_service.py`. Replace the entire old `handle_user_message` method with the dispatcher and handlers below (keep `_append_return_prompt` from Task 3; place these above it):

```python
    _TOPIC_LABELS = {
        "tuition": "học phí",
        "curriculum": "chương trình học",
        "scholarship": "học bổng",
        "dormitory": "ký túc xá",
        "career": "định hướng nghề nghiệp",
        "admission_policy": "chính sách tuyển sinh",
        "program_overview": "tổng quan chương trình",
    }

    def handle_user_message(self, session_token: str, content: str) -> ConversationTurnResult:
        self.repository.append_message(session_token, "user", content, "user_message")
        session = self.repository.get_session_by_token(session_token)
        profile_state = self.repository.get_profile_state(session_token)
        flow_state = self.repository.get_flow_state(session_token)
        intent = self.intent_router.classify(content, profile_state)
        session_status = session.status if session else "collecting_profile"

        if intent.route == "ADVISORY_FLOW":
            return self._handle_advisory(session_token, content, profile_state, flow_state)
        # HYBRID has no orchestration in Phase 1 → reuse the knowledge fallback
        # (the question is well-formed; "no data yet" beats asking to clarify).
        if intent.route in ("KNOWLEDGE_QA", "HYBRID"):
            return self._handle_knowledge_qa(session_token, intent, profile_state, flow_state, session_status)
        if intent.route == "OUT_OF_SCOPE":
            return self._handle_out_of_scope(session_token, profile_state, flow_state, session_status)
        return self._handle_clarification(session_token, profile_state, flow_state, session_status)

    def _handle_advisory(self, session_token, content, profile_state, flow_state):
        extracted = self.extract_profile(content)
        merged = merge_profile_state(profile_state, extracted, content)

        follow_up = next_follow_up_question(merged)
        if follow_up:
            self.repository.update_profile_state(session_token, merged, "collecting_profile")
            self.repository.update_flow_state(
                session_token,
                flow_state.model_copy(update={
                    "active_flow": "ADVISORY_FLOW",
                    "pending_question": follow_up,
                }),
            )
            self.repository.append_message(session_token, "assistant", follow_up, "assistant_follow_up")
            return ConversationTurnResult(
                session_status="collecting_profile",
                assistant_message=follow_up,
                should_start_run=False,
                profile_state=merged,
            )

        ready_message = "Cảm ơn bạn. Mình đã có đủ thông tin và sẽ bắt đầu phân tích."
        self.repository.update_profile_state(session_token, merged, "ready")
        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": None,  # clear: no question is pending once we run
            }),
        )
        self.repository.append_message(session_token, "assistant", ready_message, "assistant_ready")
        return ConversationTurnResult(
            session_status="ready",
            assistant_message=ready_message,
            should_start_run=True,
            profile_state=merged,
        )

    def _handle_knowledge_qa(self, session_token, intent, profile_state, flow_state, session_status):
        # Phase 1: no RAG data yet → always fallback. Do NOT touch profile or flow_state.
        topic_label = self._TOPIC_LABELS.get(intent.topic or "", "thông tin này")
        school_label = intent.school or "trường bạn hỏi"
        fallback = (
            f"Hệ thống chưa có dữ liệu về {topic_label} của {school_label}. "
            f"Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
        )
        response = self._append_return_prompt(fallback, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    def _handle_out_of_scope(self, session_token, profile_state, flow_state, session_status):
        msg = (
            "Xin lỗi, câu hỏi này nằm ngoài phạm vi tư vấn tuyển sinh của mình. "
            "Mình chỉ có thể hỗ trợ các vấn đề liên quan đến tuyển sinh đại học."
        )
        response = self._append_return_prompt(msg, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    def _handle_clarification(self, session_token, profile_state, flow_state, session_status):
        msg = "Bạn có thể nói rõ hơn câu hỏi của mình không? Mình muốn hiểu đúng để hỗ trợ tốt hơn."
        response = self._append_return_prompt(msg, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )
```

- [ ] **Step 4: Run all conversation-service tests**

Run: `pytest tests/services/chat/test_conversation_service.py -v`
Expected: all passed (original + injection + 3 append + 4 branch tests)

- [ ] **Step 5: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat: add routing dispatcher and four branch handlers"
```

---

### Task 5: KNOWLEDGE_QA + HYBRID branch tests

**Files:**
- Modify: `tests/services/chat/test_conversation_service.py` (extend)
- No production change — behavior already implemented in Task 4.

- [ ] **Step 1: Add tests**

Append to `tests/services/chat/test_conversation_service.py`:

```python
def test_handle_knowledge_qa_returns_fallback_with_topic_and_school():
    service, _ = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
    )
    result = service.handle_user_message("tok", "học phí UET bao nhiêu")
    assert result.should_start_run is False
    assert "học phí" in result.assistant_message
    assert "VNU-UET" in result.assistant_message


def test_handle_knowledge_qa_label_when_school_null():
    service, _ = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school=None),
    )
    result = service.handle_user_message("tok", "học phí bao nhiêu")
    assert "trường bạn hỏi" in result.assistant_message


def test_handle_knowledge_qa_label_when_topic_null():
    service, _ = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic=None, school="NEU"),
    )
    result = service.handle_user_message("tok", "cho mình hỏi về NEU")
    assert "thông tin này" in result.assistant_message


def test_handle_knowledge_qa_does_not_mutate_flow_state():
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Bạn học khối gì?")
    service, repo = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="NEU"),
        profile=ChatProfileState(total_score=25.0),
        flow=flow,
    )
    service.handle_user_message("tok", "học phí NEU bao nhiêu")
    assert repo.flow_state == flow  # untouched


def test_handle_knowledge_qa_does_not_reset_profile():
    original = ChatProfileState(
        total_score=25.5,
        preferred_majors=["computer_science"],
        preferred_schools=["VNU-UET"],
    )
    service, repo = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
        profile=original,
    )
    result = service.handle_user_message("tok", "học phí UET bao nhiêu")
    assert result.profile_state.total_score == 25.5
    assert result.profile_state.preferred_majors == ["computer_science"]
    assert repo.profile_state.total_score == 25.5


def test_handle_hybrid_uses_knowledge_qa_fallback():
    service, _ = _make_service(intent_result=IntentResult(route="HYBRID"))
    result = service.handle_user_message("tok", "so sánh UET và HUST về điểm chuẩn lẫn học phí")
    assert result.should_start_run is False
    assert "chưa có dữ liệu" in result.assistant_message
```

- [ ] **Step 2: Run them**

Run: `pytest tests/services/chat/test_conversation_service.py -k "knowledge_qa or hybrid" -v`
Expected: 6 passed

- [ ] **Step 3: Commit**

```bash
git add tests/services/chat/test_conversation_service.py
git commit -m "test: KNOWLEDGE_QA + HYBRID branch behavior"
```

---

### Task 6: Advisory flow-state tracking tests

**Files:**
- Modify: `tests/services/chat/test_conversation_service.py` (extend)
- No production change — implemented in Task 4.

- [ ] **Step 1: Add tests**

Append to `tests/services/chat/test_conversation_service.py`:

```python
def test_handle_advisory_saves_pending_question():
    service, repo = _make_service(
        intent_result=IntentResult(route="ADVISORY_FLOW"),
        extract=lambda text: StudentProfile(
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
    )
    service.handle_user_message("tok", "Em muon hoc CNTT tai Ha Noi nam 2026")
    assert repo.flow_state.active_flow == "ADVISORY_FLOW"
    assert repo.flow_state.pending_question  # non-empty


def test_handle_advisory_clears_pending_question_when_complete():
    service, repo = _make_service(
        intent_result=IntentResult(route="ADVISORY_FLOW"),
        flow=FlowState(active_flow="ADVISORY_FLOW", pending_question="old question"),
        extract=lambda text: StudentProfile(
            total_score=25.0,
            subject_combination="A00",
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
    )
    result = service.handle_user_message("tok", "25 điểm A00 CNTT Hà Nội 2026")
    assert result.should_start_run is True
    assert repo.flow_state.active_flow == "ADVISORY_FLOW"
    assert repo.flow_state.pending_question is None


def test_handle_advisory_preserves_existing_profile_fields():
    service, repo = _make_service(
        intent_result=IntentResult(route="ADVISORY_FLOW"),
        profile=ChatProfileState(total_score=25.0, subject_combination="A00"),
        extract=lambda text: StudentProfile(
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
    )
    result = service.handle_user_message("tok", "Em muon hoc CNTT tai Ha Noi")
    assert result.profile_state.total_score == 25.0
    assert result.profile_state.subject_combination == "A00"
    assert "computer_science" in result.profile_state.preferred_majors
```

> The "complete" test supplies all four critical slots (`admission_year` from the "2026" in the message via `_extract_admission_year`, plus `total_score`, `preferred_majors`, `location_preference`) so `next_follow_up_question` returns `None`. See `profile_state_service.CRITICAL_SLOT_ORDER`.

- [ ] **Step 2: Run them**

Run: `pytest tests/services/chat/test_conversation_service.py -k "advisory" -v`
Expected: 4 passed (3 here + the original follow-up test)

- [ ] **Step 3: Commit**

```bash
git add tests/services/chat/test_conversation_service.py
git commit -m "test: advisory flow-state tracking"
```

---

### Task 7: Acceptance-criteria tests (incl. off-by-one regression)

**Files:**
- Modify: `tests/services/chat/test_conversation_service.py` (extend)

These map 1:1 to the spec's Acceptance Criteria. The re-ask test is the regression guard for the off-by-one bug — it asserts the pending question appears on the **first** detour, with flow state seeded exactly as `_handle_advisory` would leave it (no `return_to_flow`).

- [ ] **Step 1: Add tests**

Append to `tests/services/chat/test_conversation_service.py`:

```python
# ─── Acceptance Criteria ──────────────────────────────────────────────────────

def test_ac_knowledge_qa_does_not_trigger_run():
    service, _ = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
    )
    result = service.handle_user_message("tok", "học phí UET bao nhiêu?")
    assert result.should_start_run is False


def test_ac_advisory_flow_unchanged():
    service, _ = _make_service(
        intent_result=IntentResult(route="ADVISORY_FLOW"),
        extract=lambda text: StudentProfile(
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
    )
    result = service.handle_user_message("tok", "Em 25 điểm A00 nên chọn ngành gì?")
    assert result.session_status == "collecting_profile"
    assert result.should_start_run is False


def test_ac_out_of_scope_polite():
    service, _ = _make_service(intent_result=IntentResult(route="OUT_OF_SCOPE"))
    result = service.handle_user_message("tok", "thời tiết hôm nay thế nào?")
    assert result.should_start_run is False
    assert "ngoài phạm vi" in result.assistant_message


def test_ac_knowledge_qa_fallback_format():
    service, _ = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
    )
    result = service.handle_user_message("tok", "học phí UET bao nhiêu?")
    assert "chưa có dữ liệu" in result.assistant_message
    assert "học phí" in result.assistant_message
    assert "VNU-UET" in result.assistant_message
    assert "liên hệ" in result.assistant_message


def test_ac_reask_appears_on_first_detour():
    """REGRESSION (off-by-one): flow state seeded as _handle_advisory leaves it —
    active_flow set, pending_question set, NO return_to_flow flag. The re-ask must
    appear on the very first off-topic turn."""
    flow = FlowState(
        active_flow="ADVISORY_FLOW",
        pending_question="Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?",
    )
    service, _ = _make_service(
        intent_result=IntentResult(route="OUT_OF_SCOPE"),
        profile=ChatProfileState(preferred_majors=["computer_science"]),
        flow=flow,
    )
    result = service.handle_user_message("tok", "thời tiết hôm nay thế nào?")
    assert "Tổng điểm" in result.assistant_message
    assert "Nhân tiện" in result.assistant_message


def test_ac_profile_not_reset_on_side_query():
    original = ChatProfileState(
        total_score=27.0,
        subject_combination="A00",
        preferred_majors=["computer_science"],
        preferred_schools=["VNU-UET"],
        location_preference="Ha Noi",
    )
    service, repo = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
        profile=original,
    )
    result = service.handle_user_message("tok", "học phí UET bao nhiêu?")
    assert result.profile_state.total_score == 27.0
    assert result.profile_state.location_preference == "Ha Noi"
    assert repo.profile_state.total_score == 27.0
```

- [ ] **Step 2: Run the acceptance tests**

Run: `pytest tests/services/chat/test_conversation_service.py -k "test_ac_" -v`
Expected: 6 passed

- [ ] **Step 3: Run the full conversation-service file**

Run: `pytest tests/services/chat/test_conversation_service.py -v`
Expected: all passed

- [ ] **Step 4: Commit**

```bash
git add tests/services/chat/test_conversation_service.py
git commit -m "test: Phase 1 acceptance criteria + off-by-one re-ask regression"
```

---

### Task 8: Full-suite smoke check

- [ ] **Step 1: Run every chat test together**

Run: `pytest tests/services/chat/ -v --tb=short`
Expected (minimum):
```
tests/services/chat/test_flow_state_model.py        6 passed
tests/services/chat/test_repository.py              8 passed
tests/services/chat/test_intent_router.py          32 passed
tests/services/chat/test_conversation_service.py   23 passed
```

- [ ] **Step 2: Verify the whole service layer imports cleanly**

Run:
```bash
python -c "from services.chat.models import FlowState, ChatProfileState; from services.chat.intent_router import IntentRouter, IntentResult; from services.chat.conversation_service import ConversationService; from services.chat.repository import ChatSessionRepository; print('All imports OK')"
```
Expected: `All imports OK`

- [ ] **Step 3: Run the full repo suite for regressions**

Run: `pytest --tb=short -q`
Expected: no failures, no regressions in `web/routes/chat_api.py` consumers (`should_start_run` / `profile_state` contract unchanged).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: Phase 1 complete — IntentRouter + flow-state routing in ConversationService"
```

---

## Plan 3 done — exit criteria

- `handle_user_message` dispatches by route; advisory logic unchanged except for the `update_flow_state` side-effect.
- Off-topic handlers never mutate profile or flow state; they preserve `session_status` and return a fully-populated `ConversationTurnResult`.
- Re-ask fires on the **first** detour (regression test green).
- HYBRID falls back to the knowledge handler, not clarification.
- All Phase 1 tests green; no regressions.
