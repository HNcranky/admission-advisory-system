# Plan 4/5 — RESET hồ sơ tư vấn (EC-22)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Xoá thông tin cũ đi, tư vấn lại cho em gái em" → hồ sơ trắng ngay lập tức, delta cùng lượt áp lên hồ sơ MỚI, hỏi slot thiếu đầu tiên. Hai lớp phát hiện: deterministic phrase check (chạy cả khi LLM chết, đặt TRƯỚC nhánh continue-advisory để chặn hijack) + route LLM `RESET_PROFILE` (bắt cách nói mềm).

**Architecture:** Theo triết lý safety-net của repo: deterministic trước, LLM bọc sau, cùng đổ về một handler `_handle_reset`. Không xoá `chat_messages`; `latest_run_id` giữ nguyên (correction detector an toàn vì sau reset mọi `previous` đều None).

**Tech Stack:** Python 3.12, pytest (`python -m pytest`, KHÔNG có venv).

**Phụ thuộc:** Plan 2 đã xong (handler dùng `validate_profile_delta`; nếu thực thi độc lập trước Plan 2, thay dòng validate bằng `clean_delta = delta` và ghi chú TODO ngược về Plan 2 — KHÔNG khuyến nghị, hãy chạy đúng thứ tự).

**Spec:** `docs/superpowers/specs/2026-06-04-phase1-reasoning-integrity-design.md` (WS3)

**Lưu ý commit:** không `git push`; message KHÔNG kèm Co-Authored-By / attribution AI.

---

### Task 1: Route `RESET_PROFILE` trong intent router

**Files:**
- Modify: `services/chat/intent_router.py:37-112` (prompt), `:115-123` (Literal)
- Test: `tests/services/chat/test_intent_router.py`

- [x] **Step 1: Viết test fail (append vào test_intent_router.py)**

```python
# --- RESET_PROFILE (reasoning-integrity plan 4) ---

def test_intent_result_accepts_reset_profile_route():
    assert IntentResult(route="RESET_PROFILE").route == "RESET_PROFILE"


def test_classify_reset_profile_passthrough():
    r = _router(parsed_data={"route": "RESET_PROFILE"})
    result = r.classify("xoá thông tin cũ đi, tư vấn lại cho em gái em", ChatProfileState())
    assert result.route == "RESET_PROFILE"


def test_intent_prompt_documents_reset_profile_route():
    from services.chat.intent_router import INTENT_SYSTEM_PROMPT
    assert "RESET_PROFILE" in INTENT_SYSTEM_PROMPT
    assert "tư vấn cho người khác" in INTENT_SYSTEM_PROMPT
```

- [x] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/chat/test_intent_router.py -v`
Expected: FAIL — `RESET_PROFILE` không nằm trong Literal → ValidationError

- [x] **Step 3: Implementation (intent_router.py)**

Trong `IntentResult.route` Literal, thêm `"RESET_PROFILE"`:

```python
    route: Literal[
        "ADVISORY_FLOW",
        "KNOWLEDGE_QA",
        "HYBRID",
        "CLARIFICATION",
        "OUT_OF_SCOPE",
        "CONVERSATIONAL",
        "RESET_PROFILE",
    ]
```

Trong `INTENT_SYSTEM_PROMPT`:
- Sửa dòng mở đầu `Phân loại tin nhắn của user vào đúng 1 trong 6 route:` → `... đúng 1 trong 7 route:`
- Thêm block sau (đặt ngay sau block CONVERSATIONAL):

```text
RESET_PROFILE — yêu cầu xoá hồ sơ tư vấn hiện tại, bắt đầu lại từ đầu, hoặc
  tư vấn cho người khác (hồ sơ mới).
  Ví dụ: "xoá thông tin cũ đi", "bắt đầu lại từ đầu", "tư vấn lại cho em gái em",
         "làm hồ sơ khác cho bạn em", "giờ tư vấn cho đứa em mình nhé"
```

- [x] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/chat/test_intent_router.py -v`
Expected: PASS toàn bộ

- [x] **Step 5: Commit**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router.py
git commit -m "feat: RESET_PROFILE intent route"
```

---

### Task 2: Deterministic pre-check + `_handle_reset` + dispatch

**Files:**
- Modify: `services/chat/conversation_service.py`
- Test: `tests/services/chat/test_conversation_service.py`

- [x] **Step 1: Viết test fail (append cuối test_conversation_service.py)**

```python
# ─── Plan reasoning-integrity 4: RESET hồ sơ (EC-22) ──────────────────────────

def _full_old_profile():
    return ChatProfileState(
        admission_year=2026, total_score=27.0, subject_combination="A01",
        admission_method="thpt_score",
        explicit_preferred_majors=["computer_science"], preferred_majors=["computer_science"],
    )


def test_ec22_deterministic_reset_clears_profile_and_asks_first_slot():
    service, repo = _make_service(
        # router cố tình trả route khác — pre-check deterministic phải thắng
        intent_result=IntentResult(route="CONVERSATIONAL", subtype="EMOTIONAL_SUPPORT"),
        profile=_full_old_profile(),
        status="completed",
        extract=lambda text, known_state=None, active_slot=None: {},
    )
    result = service.handle_user_message("tok", "Xoá thông tin cũ đi, em muốn tư vấn lại từ đầu")

    assert repo.profile_state.total_score is None         # hồ sơ cũ đã xoá
    assert repo.profile_state.preferred_majors == []
    assert "hồ sơ tư vấn mới" in result.assistant_message
    assert "năm nào" in result.assistant_message           # hỏi slot đầu tiên
    assert result.should_start_run is False
    assert repo.status == "collecting_profile"
    assert repo.flow_state.pending_question == "Bạn đang xét tuyển cho năm nào?"


def test_ec22_reset_applies_same_turn_delta_to_fresh_profile():
    """Hijack guard: đang chờ slot năm, user nói 'xoá hết..., năm 2026' —
    KHÔNG được để _maybe_continue_advisory nuốt '2026' vào hồ sơ CŨ."""
    flow = FlowState(active_flow="ADVISORY_FLOW",
                     pending_question="Bạn đang xét tuyển cho năm nào?")
    profile = _full_old_profile().model_copy(update={"admission_year": None})
    service, repo = _make_service(
        intent_result=IntentResult(route="CONVERSATIONAL", subtype="EMOTIONAL_SUPPORT"),
        profile=profile, flow=flow, status="completed",
        extract=lambda text, known_state=None, active_slot=None: {},
    )
    result = service.handle_user_message("tok", "Xoá hết đi, tư vấn cho em gái em, năm 2026")

    assert repo.profile_state.admission_year == 2026      # delta áp lên hồ sơ TRẮNG
    assert repo.profile_state.total_score is None          # điểm cũ KHÔNG còn
    assert repo.profile_state.preferred_majors == []
    assert "hồ sơ tư vấn mới" in result.assistant_message
    assert "bao nhiêu" in result.assistant_message         # hỏi tiếp slot điểm


def test_ec22_llm_routed_reset_uses_same_handler():
    """Cách nói mềm không khớp phrase deterministic → LLM route RESET_PROFILE."""
    service, repo = _make_service(
        intent_result=IntentResult(route="RESET_PROFILE"),
        profile=_full_old_profile(),
        status="completed",
        extract=lambda text, known_state=None, active_slot=None: {},
    )
    result = service.handle_user_message("tok", "giờ tư vấn cho đứa bạn của em nhé")

    assert repo.profile_state.total_score is None
    assert "hồ sơ tư vấn mới" in result.assistant_message


def test_normal_messages_do_not_trigger_deterministic_reset():
    """'tư vấn cho em' thông thường KHÔNG được reset."""
    service, repo = _make_service(
        intent_result=IntentResult(route="ADVISORY_FLOW"),
        profile=_full_old_profile(),
        extract=lambda text, known_state=None, active_slot=None: {},
    )
    service.handle_user_message("tok", "tư vấn cho em ngành phù hợp với 27 điểm")
    assert repo.profile_state.total_score == 27.0          # hồ sơ giữ nguyên
```

- [x] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -k "ec22 or deterministic_reset" -v`
Expected: FAIL — hồ sơ cũ vẫn còn / không có message "hồ sơ tư vấn mới"

- [x] **Step 3: Implementation (conversation_service.py)**

```python
# Import: bổ sung
from services.chat.models import ChatProfileState, ConversationTurnResult
from services.profile_service import normalize_text
```

Hằng class (đặt cạnh `CLARIFICATION_PROMPTS`, ngoài class hoặc class-level đều được — chọn module-level):

```python
# Cụm từ reset tường minh (đã normalize). CỐ Ý hẹp — cách nói mềm ("tư vấn cho
# em gái em") để LLM route RESET_PROFILE xử lý, tránh false positive.
_RESET_PHRASES = (
    "xoa thong tin", "xoa ho so", "xoa het",
    "bat dau lai", "lam lai tu dau", "tu van lai tu dau", "reset",
)


def _is_reset_request(content: str) -> bool:
    normalized = normalize_text(content or "")
    return any(phrase in normalized for phrase in _RESET_PHRASES)
```

Trong `handle_user_message`, NGAY SAU `_deterministic_safety_net` và TRƯỚC khối validate của Plan 2:

```python
        # EC-22: reset tường minh phải thắng mọi nhánh khác — kể cả
        # _maybe_continue_advisory (tránh "xoá hết..., năm 2026" bị nuốt vào hồ sơ cũ).
        if _is_reset_request(content):
            return self._handle_reset(session_token, delta, flow_state)
```

Trong khối dispatch route (sau nhánh CONVERSATIONAL):

```python
        if intent.route == "RESET_PROFILE":
            return self._handle_reset(session_token, delta, flow_state)
```

Method mới (đặt sau `_maybe_correction_rerun`):

```python
    def _handle_reset(self, session_token, delta, flow_state):
        """EC-22: bắt đầu hồ sơ trắng; delta của CHÍNH lượt này áp lên hồ sơ mới
        (user kèm "năm 2026" thì khỏi hỏi lại năm). Không xoá lịch sử chat."""
        fresh = ChatProfileState()
        clean_delta, _ = validate_profile_delta(delta, fresh)
        merged = apply_profile_delta(fresh, clean_delta)

        follow_up = next_follow_up_question(merged)
        if follow_up is None:
            # Hiếm: delta một lượt điền đủ slot critical → vào thẳng phân tích.
            return self._advance_advisory(session_token, merged, flow_state)

        self.repository.update_profile_state(session_token, merged, "collecting_profile")
        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": follow_up,
            }),
        )
        message = f"Mình đã bắt đầu hồ sơ tư vấn mới. {follow_up}"
        self.repository.append_message(session_token, "assistant", message, "assistant_follow_up")
        return ConversationTurnResult(
            session_status="collecting_profile",
            assistant_message=message,
            should_start_run=False,
            profile_state=merged,
        )
```

Lưu ý: `ConversationTurnResult` đã được import sẵn ở đầu file — chỉ cần thêm `ChatProfileState` vào cùng dòng import từ `services.chat.models`.

- [x] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -v`
Expected: PASS toàn bộ (test cũ không đổi hành vi — message thường không chứa phrase reset)

- [x] **Step 5: Chạy toàn bộ suite**

Run: `python -m pytest -q`
Expected: PASS (0 failed)

- [x] **Step 6: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat: reset advisory profile via deterministic phrases and RESET_PROFILE route (EC-22)"
```
