# Plan 2/5 — Validate điểm theo thang phương thức (EC-04)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Điểm vượt thang của phương thức đã biết không bao giờ lọt vào profile: validate tại MỘT điểm chèn trong `handle_user_message`, trả lời từ chối đúng mẫu EC-04, và xử lý chiều ngược (chọn phương thức làm điểm cũ thành vô lệ → xoá điểm, hỏi lại).

**Architecture:** `validate_profile_delta(delta, current) → (clean_delta, rejections)` là pure function trong module mới `services/profile/validation.py`. Gọi đúng một chỗ ngay sau `_deterministic_safety_net` — cả 3 nhánh (continue-advisory / correction-rerun / advisory) dùng chung delta nên một điểm chèn phủ hết, kể cả correction "em nhầm, 35 điểm".

**Tech Stack:** Python 3.12, Pydantic v2, pytest (`python -m pytest`, KHÔNG có venv).

**Phụ thuộc:** Plan 1 đã xong (cần `SCORE_SCALES`, `method_display`, slot `admission_method`, `follow_up_for`).

**Spec:** `docs/superpowers/specs/2026-06-04-phase1-reasoning-integrity-design.md` (mục 4.1.4)

**Lưu ý commit:** không `git push`; message KHÔNG kèm Co-Authored-By / attribution AI.

---

### Task 1: `validate_profile_delta` — R1 + R2

**Files:**
- Create: `services/profile/validation.py`
- Test: `tests/services/profile/test_validation.py`

- [ ] **Step 1: Viết test fail**

```python
# tests/services/profile/test_validation.py
from services.chat.models import ChatProfileState
from services.profile.validation import validate_profile_delta


def test_r1_score_over_scale_rejected_other_fields_kept():
    # EC-04: method đã biết (thang 30), delta điểm 35 → loại điểm, giữ field khác.
    current = ChatProfileState(admission_method="thpt_score")
    delta = {"total_score": 35.0, "location_preference": "Ha Noi"}

    clean, rejections = validate_profile_delta(delta, current)

    assert "total_score" not in clean
    assert clean["location_preference"] == "Ha Noi"
    assert len(rejections) == 1
    assert rejections[0]["slot"] == "total_score"
    assert "35" in rejections[0]["message"]
    assert "thang 30" in rejections[0]["message"]
    assert "phương thức" in rejections[0]["message"]


def test_r1_uses_method_from_same_delta():
    # Method đến cùng lượt với điểm → vẫn validate được.
    current = ChatProfileState()
    delta = {"admission_method": "school_record", "total_score": 31.0}

    clean, rejections = validate_profile_delta(delta, current)

    assert clean["admission_method"] == "school_record"
    assert "total_score" not in clean
    assert rejections[0]["slot"] == "total_score"


def test_r1_score_within_scale_passes():
    current = ChatProfileState(admission_method="thpt_score")
    clean, rejections = validate_profile_delta({"total_score": 26.5}, current)
    assert clean == {"total_score": 26.5}
    assert rejections == []


def test_r1_competency_scale_allows_three_digit_score():
    current = ChatProfileState(admission_method="competency_test")
    clean, rejections = validate_profile_delta({"total_score": 105.0}, current)
    assert clean == {"total_score": 105.0}
    assert rejections == []


def test_no_validation_when_method_unknown():
    # EC-13: chưa biết phương thức → nhận tạm, KHÔNG chặn (reasoning sẽ không chấm fit).
    current = ChatProfileState()
    clean, rejections = validate_profile_delta({"total_score": 99.0}, current)
    assert clean == {"total_score": 99.0}
    assert rejections == []


def test_r2_method_change_invalidates_existing_score():
    # Điểm 99 nhận tạm trước đó; giờ user chọn thang 30 → xoá điểm + hỏi lại.
    current = ChatProfileState(total_score=99.0)
    delta = {"admission_method": "thpt_score"}

    clean, rejections = validate_profile_delta(delta, current)

    assert clean["admission_method"] == "thpt_score"
    assert clean["total_score"] is None           # apply_profile_delta sẽ xoá điểm
    assert rejections[0]["slot"] == "total_score"
    assert "99" in rejections[0]["message"]
    assert "bao nhiêu" in rejections[0]["message"]  # message tự re-ask điểm


def test_r2_not_fired_when_existing_score_fits_new_scale():
    current = ChatProfileState(total_score=27.0)
    clean, rejections = validate_profile_delta({"admission_method": "thpt_score"}, current)
    assert clean == {"admission_method": "thpt_score"}
    assert rejections == []


def test_accumulation_ops_and_non_numeric_are_ignored():
    current = ChatProfileState(admission_method="thpt_score")
    delta = {
        "explicit_preferred_majors": {"__add__": ["computer_science"]},
        "total_score": "abc",  # LLM trả rác → bỏ qua validate, giữ nguyên cho coerce hạ nguồn
    }
    clean, rejections = validate_profile_delta(delta, current)
    assert clean["explicit_preferred_majors"] == {"__add__": ["computer_science"]}
    assert rejections == []


def test_scale_none_means_no_cap():
    current = ChatProfileState(admission_method="talent_admission")
    clean, rejections = validate_profile_delta({"total_score": 120.0}, current)
    assert rejections == []
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/profile/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.profile.validation'`

- [ ] **Step 3: Implementation**

```python
# services/profile/validation.py
"""Validate chéo delta hồ sơ trước khi áp (EC-04).

Pure function — không I/O, không LLM. Trả (clean_delta, rejections);
mỗi rejection: {"slot", "value", "message"} với message tiếng Việt dùng được ngay.
"""
from typing import Dict, List, Tuple

from services.profile.admission_methods import SCORE_SCALES, method_display


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def validate_profile_delta(delta: dict, current) -> Tuple[dict, List[Dict]]:
    clean = dict(delta or {})
    rejections: List[Dict] = []

    delta_method = clean.get("admission_method")
    effective_method = delta_method or getattr(current, "admission_method", None)
    scale = SCORE_SCALES.get(effective_method) if effective_method else None

    # R1 — điểm mới vượt thang của phương thức hiệu lực.
    score = clean.get("total_score")
    score_value = _as_float(score) if not isinstance(score, dict) else None
    if scale is not None and score_value is not None and score_value > scale:
        clean.pop("total_score", None)
        rejections.append({
            "slot": "total_score",
            "value": score_value,
            "message": (
                f"Với phương thức {method_display(effective_method)} (thang {_fmt(scale)}), "
                f"tổng điểm {_fmt(score_value)} chưa hợp lệ. Em kiểm tra lại điểm hoặc cho mình "
                "biết em đang dùng phương thức xét tuyển nào nhé."
            ),
        })
        return clean, rejections

    # R2 — phương thức mới làm điểm ĐÃ LƯU thành vô lệ → xoá điểm, hỏi lại.
    existing_score = _as_float(getattr(current, "total_score", None))
    if (delta_method and scale is not None and existing_score is not None
            and existing_score > scale and "total_score" not in clean):
        clean["total_score"] = None  # apply_profile_delta sẽ set None → slot hỏi lại
        rejections.append({
            "slot": "total_score",
            "value": existing_score,
            "message": (
                f"Em chọn phương thức {method_display(delta_method)} (thang {_fmt(scale)}) "
                f"nhưng điểm {_fmt(existing_score)} đã ghi trước đó vượt thang này, nên mình "
                "xoá điểm cũ. Điểm của em theo phương thức này là bao nhiêu?"
            ),
        })

    return clean, rejections
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/profile/test_validation.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add services/profile/validation.py tests/services/profile/test_validation.py
git commit -m "feat: method-scale validation for profile deltas (EC-04)"
```

---

### Task 2: Hook vào ConversationService + `_handle_rejection`

**Files:**
- Modify: `services/chat/conversation_service.py` (import, `handle_user_message`, method mới)
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Viết test fail (append cuối test_conversation_service.py)**

```python
# ─── Plan reasoning-integrity 2: validate thang điểm (EC-04) ──────────────────

def test_ec04_score_over_scale_is_rejected_with_explanation():
    """EC-04: 35 điểm thang 30 → không lưu, trả lời yêu cầu kiểm tra lại."""
    profile = ChatProfileState(admission_year=2026, admission_method="thpt_score")
    flow = FlowState(active_flow="ADVISORY_FLOW",
                     pending_question="Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?")
    service, repo = _make_service(
        profile=profile, flow=flow,
        extract=lambda text, known_state=None, active_slot=None: {"total_score": 35.0},
    )
    result = service.handle_user_message("tok", "Em được 35 điểm theo thang 30")

    assert repo.profile_state.total_score is None          # KHÔNG lưu điểm vô lệ
    assert "35" in result.assistant_message
    assert "chưa hợp lệ" in result.assistant_message
    assert result.should_start_run is False
    # pending_question trỏ về slot bị từ chối để bare answer lượt sau được nhận
    assert repo.flow_state.pending_question == (
        "Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?"
    )
    assert repo.messages[-1][1] == "assistant_validation"


def test_ec04_valid_fields_in_same_turn_still_applied():
    profile = ChatProfileState(admission_year=2026, admission_method="thpt_score")
    service, repo = _make_service(
        profile=profile,
        extract=lambda text, known_state=None, active_slot=None: {
            "total_score": 35.0, "location_preference": "Ha Noi",
        },
    )
    service.handle_user_message("tok", "35 điểm, muốn học ở Hà Nội")

    assert repo.profile_state.total_score is None
    assert repo.profile_state.location_preference == "Ha Noi"  # phần hợp lệ vẫn ghi


def test_ec04_correction_to_invalid_score_is_blocked():
    """Sửa điểm sau khi đã có kết quả → vẫn phải qua validation, không re-run."""
    service, repo = _make_service(
        profile=_completed_profile().model_copy(update={"admission_method": "thpt_score"}),
        flow=FlowState(active_flow="ADVISORY_FLOW", pending_question=None),
        status="completed",
        extract=lambda text, known_state=None, active_slot=None: {"total_score": 35.0},
    )
    result = service.handle_user_message("tok", "em nhầm, 35 điểm")

    assert result.should_start_run is False                 # KHÔNG re-run với điểm rác
    assert result.correction_note is None
    assert repo.profile_state.total_score == 27.0           # giữ điểm cũ


def test_r2_choosing_method_after_provisional_high_score_clears_it():
    """99 điểm nhận tạm khi chưa biết phương thức; chọn 'điểm thi THPT' → xoá, hỏi lại."""
    profile = ChatProfileState(admission_year=2026, total_score=99.0)
    flow = FlowState(active_flow="ADVISORY_FLOW",
                     pending_question="Bạn xét tuyển theo phương thức nào?")
    service, repo = _make_service(
        profile=profile, flow=flow,
        extract=lambda text, known_state=None, active_slot=None: {},
    )
    result = service.handle_user_message("tok", "điểm thi tốt nghiệp THPT")

    assert repo.profile_state.admission_method == "thpt_score"  # phương thức vẫn nhận
    assert repo.profile_state.total_score is None                # điểm vô lệ bị xoá
    assert "99" in result.assistant_message
    assert "bao nhiêu" in result.assistant_message               # re-ask điểm
```

Lưu ý: `_completed_profile()` đã có sẵn trong file (khối AC7, đã thêm `admission_method` ở Plan 1).

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -k "ec04 or r2_choosing" -v`
Expected: FAIL — điểm 35 vẫn được lưu / không có kind `assistant_validation`

- [ ] **Step 3: Implementation (conversation_service.py)**

```python
# Import: bổ sung
from services.profile.slots import (
    SLOTS, follow_up_for, missing_critical_slots, next_follow_up_question, parse_slot,
)
from services.profile.validation import validate_profile_delta
```

Trong `handle_user_message`, NGAY SAU dòng `delta = self._deterministic_safety_net(...)`:

```python
        delta, rejections = validate_profile_delta(delta, profile_state)
        if rejections:
            return self._handle_rejection(
                session_token, profile_state, flow_state, delta, rejections
            )
```

Method mới (đặt sau `_deterministic_safety_net`):

```python
    def _handle_rejection(self, session_token, profile_state, flow_state, clean_delta, rejections):
        """Giá trị vô lệ theo thang phương thức (EC-04): áp phần hợp lệ, trả lời
        từ chối kèm hướng dẫn, và trỏ pending_question về slot bị từ chối để câu
        trả lời cụt lượt sau vẫn được safety-net nhận."""
        merged = apply_profile_delta(profile_state, clean_delta)
        self.repository.update_profile_state(session_token, merged, "collecting_profile")

        rejected_slot = rejections[0]["slot"]
        pending = follow_up_for(rejected_slot) or next_follow_up_question(merged)
        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": pending,
            }),
        )
        message = rejections[0]["message"]
        self.repository.append_message(session_token, "assistant", message, "assistant_validation")
        return ConversationTurnResult(
            session_status="collecting_profile",
            assistant_message=message,
            should_start_run=False,
            profile_state=merged,
        )
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -v`
Expected: PASS toàn bộ (cả test cũ — validation không đụng delta hợp lệ)

- [ ] **Step 5: Chạy toàn bộ suite**

Run: `python -m pytest -q`
Expected: PASS (0 failed)

- [ ] **Step 6: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat: reject out-of-scale scores at conversation layer (EC-04)"
```
