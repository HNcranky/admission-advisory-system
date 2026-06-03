# Phase 5d — ConversationService Hybrid Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder HYBRID handling in `ConversationService` with a real `_handle_hybrid` that gates the advisory branch on profile completeness: complete profile → dispatch an async hybrid run; incomplete profile → answer the knowledge half inline and ask the next advisory follow-up.

**Architecture:** `ConversationTurnResult` gains `run_kind` (so the web route picks the right dispatcher) and `hybrid_intent` (the serialized router payload the dispatcher replays). Completeness is checked with a fresh `missing_critical_slots()` computation (never trusting possibly-stale `missing_slots`). The incomplete path reuses the Phase 5c knowledge fan-out + deterministic formatter — no LLM synthesis, no background run.

**Tech Stack:** Python, Pydantic, pytest.

**Spec:** [`../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md`](../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md) — decisions 1, 4, 5; flow diagram.

**Depends on:** Phase 5a (`IntentResult` fields), Phase 5c (`run_knowledge_fanout`, `format_knowledge_blocks`).

---

### Task 1: `missing_critical_slots()` helper (robust completeness check)

**Files:**
- Modify: `services/chat/profile_state_service.py`
- Test: `tests/services/chat/test_profile_state_service.py` (create if absent)

Rationale: `next_follow_up_question` keys off `state.missing_slots`, which is empty on a freshly loaded profile and would falsely read as "complete". We add a pure helper that recomputes missing slots from the critical fields.

- [ ] **Step 1: Write the failing tests**

Create or extend `tests/services/chat/test_profile_state_service.py`:

```python
from services.chat.models import ChatProfileState
from services.chat.profile_state_service import missing_critical_slots


def test_missing_critical_slots_empty_profile_returns_all():
    missing = missing_critical_slots(ChatProfileState())
    assert "admission_year" in missing
    assert "total_score" in missing
    assert "preferred_majors" in missing
    assert "location_preference" in missing


def test_missing_critical_slots_complete_profile_returns_empty():
    profile = ChatProfileState(
        admission_year=2026,
        total_score=25.0,
        preferred_majors=["computer_science"],
        location_preference="Ha Noi",
    )
    assert missing_critical_slots(profile) == []


def test_missing_critical_slots_ignores_stale_missing_slots_field():
    # missing_slots says empty, but the fields are actually empty → recompute wins.
    profile = ChatProfileState(missing_slots=[])
    assert "total_score" in missing_critical_slots(profile)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_profile_state_service.py -k missing_critical_slots -v`
Expected: FAIL — `ImportError: cannot import name 'missing_critical_slots'`.

- [ ] **Step 3: Add the helper**

In `services/chat/profile_state_service.py`, add after `merge_profile_state` (before `next_follow_up_question`):

```python
def missing_critical_slots(state: ChatProfileState) -> list:
    """Recompute the missing critical slots straight from the fields.

    Independent of `state.missing_slots`, which may be empty/stale on a freshly
    loaded profile.
    """
    return [slot for slot in CRITICAL_SLOT_ORDER if not getattr(state, slot)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_profile_state_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/chat/profile_state_service.py tests/services/chat/test_profile_state_service.py
git commit -m "feat(chat): add missing_critical_slots robust completeness helper"
```

---

### Task 2: `ConversationTurnResult` gains `run_kind` and `hybrid_intent`

**Files:**
- Modify: `services/chat/models.py` (the `ConversationTurnResult` model, ~lines 41-46)
- Test: `tests/services/chat/test_conversation_turn_result.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/services/chat/test_conversation_turn_result.py` (create if absent):

```python
from services.chat.models import ChatProfileState, ConversationTurnResult


def test_turn_result_defaults_run_kind_advisory():
    r = ConversationTurnResult(
        session_status="ready", assistant_message="ok", profile_state=ChatProfileState(),
    )
    assert r.run_kind == "advisory"
    assert r.hybrid_intent is None


def test_turn_result_accepts_hybrid_kind_and_intent_payload():
    r = ConversationTurnResult(
        session_status="running",
        assistant_message="đang tổng hợp",
        should_start_run=True,
        run_kind="hybrid",
        hybrid_intent={"route": "HYBRID", "schools": ["VNU-UET", "HUST"], "needs_advisory": True},
        profile_state=ChatProfileState(),
    )
    assert r.run_kind == "hybrid"
    assert r.hybrid_intent["schools"] == ["VNU-UET", "HUST"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_conversation_turn_result.py -k "run_kind or hybrid_kind" -v`
Expected: FAIL — `ConversationTurnResult` has no `run_kind`/`hybrid_intent` fields.

- [ ] **Step 3: Add the fields**

In `services/chat/models.py`, replace the `ConversationTurnResult` class with:

```python
class ConversationTurnResult(BaseModel):
    session_status: str
    assistant_message: str
    should_start_run: bool = False
    profile_state: ChatProfileState
    citations: List[Citation] = Field(default_factory=list)
    run_kind: str = "advisory"                      # "advisory" | "hybrid"
    hybrid_intent: Optional[Dict[str, Any]] = None  # serialized IntentResult, replayed by HybridDispatcher
```

(`Dict`, `Any`, `Optional`, `List`, `Field` are already imported at the top of `models.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_conversation_turn_result.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/chat/models.py tests/services/chat/test_conversation_turn_result.py
git commit -m "feat(chat): ConversationTurnResult carries run_kind + hybrid_intent"
```

---

### Task 3: `_handle_hybrid` with profile gating + route split

**Files:**
- Modify: `services/chat/conversation_service.py` (imports; `handle_user_message` route dispatch; new `_handle_hybrid`)
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/services/chat/test_conversation_service.py`:

```python
# ─── Phase 5d: HYBRID routing + profile gating ───────────────────────────────

def _complete_profile():
    return ChatProfileState(
        admission_year=2026,
        total_score=27.0,
        preferred_majors=["computer_science"],
        location_preference="Ha Noi",
        preferred_schools=["VNU-UET", "HUST"],
    )


def test_hybrid_complete_profile_dispatches_hybrid_run():
    service, repo = _make_service(
        intent_result=IntentResult(
            route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"], needs_advisory=True,
        ),
        profile=_complete_profile(),
    )
    result = service.handle_user_message("tok", "so sánh UET và HUST điểm chuẩn lẫn học phí")
    assert result.should_start_run is True
    assert result.run_kind == "hybrid"
    assert result.hybrid_intent["route"] == "HYBRID"
    assert result.hybrid_intent["schools"] == ["VNU-UET", "HUST"]
    # a pending placeholder message was posted
    assert repo.messages[-1][1] == "assistant_hybrid_pending"


def test_hybrid_incomplete_profile_answers_knowledge_and_asks_follow_up():
    qa = FakeKnowledgeQA(result=KnowledgeQAResult(
        has_data=True, answer="Học phí UET ~35 triệu/năm.",
        citations=[Citation(source_url="https://uet/hp", chunk_text="..")], confidence=0.9,
    ))
    service, repo = _make_service(
        intent_result=IntentResult(route="HYBRID", schools=["VNU-UET"], topics=["tuition"], needs_advisory=True),
        profile=ChatProfileState(preferred_majors=["computer_science"]),  # missing year/score/location
        knowledge_qa=qa,
    )
    result = service.handle_user_message("tok", "so sánh học phí và điểm chuẩn UET")
    assert result.should_start_run is False
    assert "35 triệu" in result.assistant_message
    assert "Nhân tiện" in result.assistant_message          # advisory follow-up appended
    assert repo.flow_state.active_flow == "ADVISORY_FLOW"
    assert repo.flow_state.pending_question                  # persisted for later re-ask


def test_hybrid_incomplete_profile_no_knowledge_data_still_asks_follow_up():
    service, repo = _make_service(
        intent_result=IntentResult(route="HYBRID", schools=["VNU-UET"], topics=["tuition"], needs_advisory=True),
        profile=ChatProfileState(),  # fully empty
        knowledge_qa=FakeKnowledgeQA(),  # no data
    )
    result = service.handle_user_message("tok", "so sánh UET và HUST")
    assert result.should_start_run is False
    assert "chưa có dữ liệu" in result.assistant_message.lower()
    assert "Nhân tiện" in result.assistant_message


def test_hybrid_does_not_reset_profile():
    profile = _complete_profile()
    service, repo = _make_service(
        intent_result=IntentResult(route="HYBRID", schools=["VNU-UET"], topics=["tuition"], needs_advisory=True),
        profile=profile,
    )
    result = service.handle_user_message("tok", "so sánh UET và HUST")
    assert result.profile_state.total_score == 27.0
    assert repo.profile_state.total_score == 27.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -k hybrid -v`
Expected: FAIL — HYBRID still routes to `_handle_knowledge_qa`; `run_kind`/`hybrid_intent`/`assistant_hybrid_pending` behavior absent.

- [ ] **Step 3: Wire imports + route split + `_handle_hybrid`**

In `services/chat/conversation_service.py`:

(a) Extend the imports near the top:

```python
from services.chat.knowledge_fanout import format_knowledge_blocks, run_knowledge_fanout
from services.chat.profile_state_service import (
    merge_profile_state,
    missing_critical_slots,
    next_follow_up_question,
)
```

(replacing the existing `from services.chat.profile_state_service import merge_profile_state, next_follow_up_question` line).

(b) In `handle_user_message`, replace the combined KNOWLEDGE_QA/HYBRID branch:

```python
        if intent.route == "KNOWLEDGE_QA":
            return self._handle_knowledge_qa(session_token, content, intent, profile_state, flow_state, session_status)
        if intent.route == "HYBRID":
            return self._handle_hybrid(session_token, content, intent, profile_state, flow_state, session_status)
```

(remove the old `if intent.route in ("KNOWLEDGE_QA", "HYBRID"):` block and its comment).

(c) Add the new method after `_handle_knowledge_qa`:

```python
    def _handle_hybrid(self, session_token, content, intent, profile_state, flow_state, session_status):
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
        blocks = run_knowledge_fanout(self.knowledge_qa, intent, content, school_fallback)
        body = format_knowledge_blocks(blocks)

        follow_up = next_follow_up_question(profile_state.model_copy(update={"missing_slots": missing}))
        response = f"{body}\n\nNhân tiện, {follow_up}" if follow_up else body

        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": follow_up,
            }),
        )
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )
```

- [ ] **Step 4: Run the full conversation-service suite**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -v`
Expected: PASS — new HYBRID tests green; the pre-existing `test_handle_hybrid_uses_knowledge_qa_fallback` still passes (empty profile → incomplete path → no-data fan-out fallback contains "chưa có dữ liệu", `should_start_run` False).

- [ ] **Step 5: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat(chat): real _handle_hybrid with profile gating (dispatch vs inline knowledge+follow-up)"
```

---

## Self-Review

- **Spec coverage:** Decision 1 (async dispatch on complete profile) → Task 3 `should_start_run=True, run_kind="hybrid"` + placeholder. Decision 4 (gate advisory; knowledge always answers; inline when incomplete) → Task 3 incomplete branch. Decision 5 (no auto-defer) → incomplete branch just asks the follow-up; nothing remembered. "Profile not reset" → `test_hybrid_does_not_reset_profile`. Robust completeness → Task 1.
- **Placeholder scan:** None.
- **Type consistency:** `hybrid_intent=intent.model_dump()` produces the dict Phase 5e replays via `IntentResult.model_validate(...)`. `run_knowledge_fanout(self.knowledge_qa, intent, content, school_fallback)` and `format_knowledge_blocks(blocks)` match Phase 5c signatures. `next_follow_up_question(state)` is unchanged — fed a state whose `missing_slots` we set from `missing_critical_slots`. `assistant_hybrid_pending` message kind is asserted in tests and used nowhere else.
