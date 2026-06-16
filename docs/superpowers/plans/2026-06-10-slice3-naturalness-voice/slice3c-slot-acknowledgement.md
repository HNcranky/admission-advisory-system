# Slice 3c — Acknowledge Captured Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before asking the next profile question, echo the value just captured;
once ≥2 critical slots are filled, lead with a one-line recap of what's
understood and what's still needed. Soften the `admission_method` prompt.

**Architecture:** A pure helper `build_slot_acknowledgement(delta, state)` lives
in `services/profile/slots.py` (the slot registry — the natural home for slot
labels). `ConversationService._advance_advisory` calls it and prepends the
result to the bare `follow_up`. The `pending_question` stored in flow state stays
the bare question; only the *appended assistant message* gains the ack/recap.

**Tech Stack:** Python, pytest (in-memory fakes — no DB).

**Spec:** `docs/superpowers/specs/2026-06-10-slice3-naturalness-voice-design.md` §3c

**Grounding (verified 2026-06-10):**
- `_advance_advisory` (`conversation_service.py:284`) has three callers (l.199,
  261, 282). Only `_handle_advisory` (l.282) has a per-turn `delta`. The new
  `delta` param defaults to `None`, so the other two callers are unaffected.
- The extractor `delta` is a dict of fields captured **this turn** (the test
  fakes return exactly the captured fields — see
  `tests/services/chat/test_conversation_service.py:270`).
- `missing_critical_slots(state)` and `_slot_present`/`_ORDERED` already exist in
  `slots.py`; `method_display` is in `services/profile/admission_methods.py:97`.
- Existing advisory-flow tests assert `pending_question` / `should_start_run`,
  **not** the exact follow-up message text, so prepending an ack won't break them.

---

### Task 1: `build_slot_acknowledgement` helper in slots.py

**Files:**
- Modify: `services/profile/slots.py`
- Test: `tests/services/profile/test_slots.py`

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/services/profile/test_slots.py`:

```python
from services.chat.models import ChatProfileState
from services.profile.slots import build_slot_acknowledgement


def test_ack_echoes_single_captured_value_when_under_two_filled():
    state = ChatProfileState(total_score=26.0)
    ack = build_slot_acknowledgement({"total_score": 26.0}, state)
    assert ack == "Mình ghi nhận mức điểm 26."


def test_ack_recaps_filled_and_missing_when_two_or_more_filled():
    state = ChatProfileState(admission_year=2026, total_score=26.0, admission_method="thpt_score")
    ack = build_slot_acknowledgement({"admission_method": "thpt_score"}, state)
    assert ack.startswith("Mình đã nắm:")
    assert "năm xét tuyển 2026" in ack
    assert "mức điểm 26" in ack
    assert "phương thức xét tuyển điểm thi tốt nghiệp THPT" in ack
    assert "Còn thiếu:" in ack
    assert "tổ hợp xét tuyển" in ack
    assert "ngành quan tâm" in ack


def test_ack_returns_none_when_nothing_captured():
    state = ChatProfileState(total_score=26.0)
    assert build_slot_acknowledgement({}, state) is None
    assert build_slot_acknowledgement({"preferred_schools": ["hust"]}, state) is None


def test_ack_dedupes_major_variants_to_one_label():
    state = ChatProfileState(preferred_majors=["computer_science"])
    ack = build_slot_acknowledgement(
        {"explicit_preferred_majors": ["computer_science"], "preferred_majors": ["computer_science"]},
        state,
    )
    assert ack == "Mình ghi nhận ngành quan tâm computer_science."
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/python -m pytest tests/services/profile/test_slots.py -q`
Expected: FAIL — `build_slot_acknowledgement` not defined.

- [ ] **Step 3: Implement the helper in `slots.py`**

Add the `method_display` import at the top (next to the existing
`parse_admission_method` import):

```python
from services.profile.admission_methods import parse_admission_method, method_display
```

Append at the end of `services/profile/slots.py`:

```python
# Nhãn slot hiển thị cho ack/recap (3c). Nguồn nhãn dùng chung với
# explanation_service (_SLOT_LABELS) nhưng dạng ngắn cho câu xác nhận.
SLOT_LABELS = {
    "admission_year": "năm xét tuyển",
    "total_score": "mức điểm",
    "admission_method": "phương thức xét tuyển",
    "preferred_majors": "ngành quan tâm",
    "subject_combination": "tổ hợp xét tuyển",
    "location_preference": "khu vực",
    "tuition_budget": "mức học phí",
}

# Các key delta cùng trỏ về slot ngành (AC4): gộp về một nhãn duy nhất.
_MAJOR_KEYS = {"preferred_majors", "explicit_preferred_majors", "inferred_interest_tags"}


def _slot_label(key: str):
    if key in _MAJOR_KEYS:
        return SLOT_LABELS["preferred_majors"]
    return SLOT_LABELS.get(key)


def _fmt_slot_value(name: str, value) -> str:
    if name == "admission_method" and value:
        return method_display(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _state_slot_value(state, name: str) -> str:
    if name == "preferred_majors":
        value = (
            getattr(state, "preferred_majors", None)
            or getattr(state, "explicit_preferred_majors", None)
            or getattr(state, "inferred_interest_tags", None)
        )
    else:
        value = getattr(state, name, None)
    return _fmt_slot_value(name, value)


def _captured_pairs(delta):
    """[(label, formatted_value)] cho các slot critical vừa được set, dedupe theo nhãn."""
    pairs = []
    seen = set()
    for key, value in delta.items():
        label = _slot_label(key)
        if label is None or label in seen or _is_empty(value):
            continue
        seen.add(label)
        pairs.append((label, _fmt_slot_value(key, value)))
    return pairs


def build_slot_acknowledgement(delta, state):
    """Câu xác nhận giá trị vừa nhận (3c). Trả None khi không bắt được slot nào.

    <2 slot critical đã điền → echo riêng giá trị vừa nhận.
    ≥2 slot critical đã điền → recap: đã nắm gì + còn thiếu gì."""
    captured = _captured_pairs(delta or {})
    if not captured:
        return None

    filled = [s for s in _ORDERED if s.critical and _slot_present(s, state)]
    if len(filled) >= 2:
        filled_text = ", ".join(
            f"{_slot_label(s.name)} {_state_slot_value(state, s.name)}" for s in filled
        )
        recap = f"Mình đã nắm: {filled_text}."
        missing_text = ", ".join(
            _slot_label(m) for m in missing_critical_slots(state) if _slot_label(m)
        )
        if missing_text:
            recap += f" Còn thiếu: {missing_text}."
        return recap

    echo = ", ".join(f"{label} {value}" for label, value in captured)
    return f"Mình ghi nhận {echo}."
```

- [ ] **Step 4: Run to confirm it passes**

Run: `.venv/bin/python -m pytest tests/services/profile/test_slots.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/profile/slots.py tests/services/profile/test_slots.py
git commit -m "feat(profile): build_slot_acknowledgement (echo + recap) helper"
```

---

### Task 2: Prepend the ack in `_advance_advisory`

**Files:**
- Modify: `services/chat/conversation_service.py` (`_advance_advisory` l.284, `_handle_advisory` l.282)
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/services/chat/test_conversation_service.py`:

```python
def test_advisory_echoes_captured_value_before_next_question():
    service, repo = _make_service(
        intent_result=IntentResult(route="ADVISORY_FLOW"),
        extract=lambda text, known_state=None, active_slot=None: {"total_score": 26.0},
    )
    result = service.handle_user_message("tok", "Em được 26 điểm")
    assert "Mình ghi nhận mức điểm 26." in result.assistant_message
    assert result.assistant_message.strip().endswith("?")  # next question still asked
    # pending_question stays the bare follow-up, not the ack-decorated message
    assert "Mình ghi nhận" not in (repo.flow_state.pending_question or "")


def test_advisory_recaps_when_two_or_more_slots_filled():
    service, repo = _make_service(
        intent_result=IntentResult(route="ADVISORY_FLOW"),
        profile=ChatProfileState(admission_year=2026, total_score=26.0),
        extract=lambda text, known_state=None, active_slot=None: {"admission_method": "thpt_score"},
    )
    result = service.handle_user_message("tok", "Xét điểm thi THPT")
    assert "Mình đã nắm:" in result.assistant_message
    assert "Còn thiếu:" in result.assistant_message
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/python -m pytest tests/services/chat/test_conversation_service.py -k "echoes or recaps" -q`
Expected: FAIL — the assistant message is the bare follow-up with no ack.

- [ ] **Step 3: Thread `delta` and prepend the ack**

In `services/chat/conversation_service.py`, add to the imports from `slots`
(wherever `next_follow_up_question`/`missing_critical_slots` are imported):

```python
from services.profile.slots import build_slot_acknowledgement
```

Change `_handle_advisory` (l.280–282) to pass `delta`:

```python
    def _handle_advisory(self, session_token, profile_state, flow_state, delta):
        merged = apply_profile_delta(profile_state, delta)
        return self._advance_advisory(session_token, merged, flow_state, delta)
```

Change the `_advance_advisory` signature and the follow-up branch (l.284–301).
Replace:

```python
    def _advance_advisory(self, session_token, merged, flow_state):
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
```

with:

```python
    def _advance_advisory(self, session_token, merged, flow_state, delta=None):
        follow_up = next_follow_up_question(merged)
        if follow_up:
            ack = build_slot_acknowledgement(delta, merged)
            message = f"{ack}\n\n{follow_up}" if ack else follow_up
            self.repository.update_profile_state(session_token, merged, "collecting_profile")
            self.repository.update_flow_state(
                session_token,
                flow_state.model_copy(update={
                    "active_flow": "ADVISORY_FLOW",
                    "pending_question": follow_up,  # stays bare; ack is message-only
                }),
            )
            self.repository.append_message(session_token, "assistant", message, "assistant_follow_up")
            return ConversationTurnResult(
                session_status="collecting_profile",
                assistant_message=message,
                should_start_run=False,
                profile_state=merged,
            )
```

(The `ready_message` branch below is unchanged.)

- [ ] **Step 4: Run to confirm it passes**

Run: `.venv/bin/python -m pytest tests/services/chat/test_conversation_service.py -q`
Expected: PASS (new tests pass; existing advisory-flow tests still pass — they
assert `pending_question`/`should_start_run`, not message text).

- [ ] **Step 5: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat(chat): acknowledge captured slot + recap before next question"
```

---

### Task 3: Soften the `admission_method` prompt

**Files:**
- Modify: `services/profile/slots.py:58-60`

- [ ] **Step 1: Rewrite the prompt**

Replace:

```python
    Slot("admission_method", True, 2,
         "Bạn xét tuyển theo phương thức nào: điểm thi tốt nghiệp THPT, học bạ, đánh giá năng lực hay xét tuyển kết hợp?",
         parse_admission_method),
```

with:

```python
    Slot("admission_method", True, 2,
         "Bạn dự định xét tuyển bằng phương thức nào nhỉ? Ví dụ: điểm thi tốt nghiệp THPT, "
         "xét học bạ, đánh giá năng lực, hoặc xét tuyển kết hợp.",
         parse_admission_method),
```

- [ ] **Step 2: Run the slot + conversation suites**

Run: `.venv/bin/python -m pytest tests/services/profile/test_slots.py tests/services/chat/test_conversation_service.py -q`
Expected: PASS.

- [ ] **Step 3: Run the full suite + commit**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

```bash
git add services/profile/slots.py
git commit -m "feat(profile): soften admission_method prompt wording"
```
