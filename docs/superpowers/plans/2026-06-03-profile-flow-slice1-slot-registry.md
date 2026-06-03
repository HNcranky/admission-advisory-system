# Slice 1 — Slot Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hợp nhất ~3 định nghĩa "slot thiếu" đang lệch nhau (`missing_slots` của LLM, `build_profile`, `CRITICAL_SLOT_ORDER`) về **một** registry duy nhất, và đưa `subject_combination` vào đúng chỗ.

**Architecture:** Tạo package `services/profile/` với module `slots.py` chứa `SLOTS` (danh sách `Slot` dataclass) + các hàm `missing_critical_slots`, `next_follow_up_question`, `parse_slot`. Mọi nơi đang tính slot tự suy (`profile_state_service.py`, `profile_service.py`, `profile_inference_service.py`) **delegate** về registry. Tasks 1–6 là refactor giữ nguyên hành vi; Task 7 (cô lập) mới đổi hành vi: `subject_combination` → critical, kèm cập nhật test bị ảnh hưởng.

**Tech Stack:** Python 3, Pydantic v2, pytest, `unicodedata`/`re` (đã dùng sẵn).

**Spec:** `docs/superpowers/specs/2026-06-03-profile-flow-dst-redesign-design.md` §5.

> **Quy ước repo (CLAUDE.md):** KHÔNG `git push`. Commit message KHÔNG kèm `Co-Authored-By` / attribution AI. Pydantic v2. Chạy test bằng `.\.venv\Scripts\python.exe -m pytest`.

---

## File Structure

- **Create** `services/profile/__init__.py` — package marker (rỗng).
- **Create** `services/profile/slots.py` — registry: `Slot`, `SLOTS`, `missing_critical_slots`, `next_follow_up_question`, `parse_slot`, các parser deterministic.
- **Create** `tests/services/profile/__init__.py` — package marker.
- **Create** `tests/services/profile/test_slots.py` — unit test registry.
- **Modify** `services/chat/profile_state_service.py` — delegate về `slots.py`.
- **Modify** `services/profile_service.py` — `build_profile` tính `missing_slots` qua registry.
- **Modify** `services/profile_inference_service.py` — `_normalize_profile` dùng registry helper.
- **Modify** (Task 7) `tests/services/chat/test_profile_state_service.py`, `tests/services/chat/test_conversation_service.py` — cập nhật kỳ vọng khi `subject_combination` thành critical.

---

## Task 1: Tạo package `services/profile` và parser deterministic

**Files:**
- Create: `services/profile/__init__.py`
- Create: `services/profile/slots.py`
- Create: `tests/services/profile/__init__.py`
- Create: `tests/services/profile/test_slots.py`

- [ ] **Step 1: Tạo package markers**

Tạo `services/profile/__init__.py` rỗng và `tests/services/profile/__init__.py` rỗng.

- [ ] **Step 2: Viết test thất bại cho các parser**

Create `tests/services/profile/test_slots.py`:

```python
from services.profile.slots import parse_score, parse_admission_year, parse_subject_combination


def test_parse_score_bare_number_in_range():
    assert parse_score("29") == 29.0
    assert parse_score("27,5") == 27.5


def test_parse_score_out_of_range_returns_none():
    assert parse_score("99") is None
    assert parse_score("không có") is None


def test_parse_admission_year_extracts_four_digit_year():
    assert parse_admission_year("mình xét tuyển năm 2026") == 2026
    assert parse_admission_year("không nhắc năm") is None


def test_parse_subject_combination_valid_code():
    assert parse_subject_combination("em thi khối A00") == "A00"


def test_parse_subject_combination_unknown_returns_none():
    assert parse_subject_combination("em thi khối Z99") is None
```

- [ ] **Step 3: Chạy test để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_slots.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.profile.slots'`.

- [ ] **Step 4: Viết parser trong `services/profile/slots.py`**

Create `services/profile/slots.py`:

```python
import re
from typing import Optional

from services.profile_service import extract_score, extract_subject_combination, normalize_text


def parse_score(raw_message: str) -> Optional[float]:
    """Bare-answer parser cho total_score: một số trong [0, 40]."""
    match = re.search(r"\d{1,2}(?:[.,]\d+)?", raw_message or "")
    if not match:
        return None
    value = float(match.group(0).replace(",", "."))
    return value if 0 <= value <= 40 else None


def parse_admission_year(raw_message: str) -> Optional[int]:
    match = re.search(r"\b20\d{2}\b", raw_message or "")
    return int(match.group(0)) if match else None


def parse_subject_combination(raw_message: str) -> Optional[str]:
    # extract_subject_combination kỳ vọng text đã normalize (đối chiếu subjects.json).
    return extract_subject_combination(normalize_text(raw_message or ""))
```

> `extract_score`, `extract_subject_combination`, `normalize_text` đã tồn tại trong `services/profile_service.py`. `parse_score` ở đây dùng regex riêng (giống `parse_pending_slot_answer` cũ) vì nhận raw message, không cần keyword "diem".

- [ ] **Step 5: Chạy test để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_slots.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add services/profile/__init__.py services/profile/slots.py tests/services/profile/__init__.py tests/services/profile/test_slots.py
git commit -m "feat(profile): add slot deterministic parsers (slice 1)"
```

---

## Task 2: Thêm `Slot`, `SLOTS` và `missing_critical_slots` (giữ nguyên hành vi)

**Files:**
- Modify: `services/profile/slots.py`
- Test: `tests/services/profile/test_slots.py`

> Critical set ban đầu = đúng hành vi hiện tại: `admission_year, total_score, preferred_majors, location_preference`. `subject_combination` để `critical=False` (Task 7 mới đổi).

- [ ] **Step 1: Viết test thất bại cho registry**

Append vào `tests/services/profile/test_slots.py`:

```python
from types import SimpleNamespace

from services.profile.slots import (
    SLOTS, missing_critical_slots, next_follow_up_question, parse_slot,
)


def _state(**kwargs):
    base = dict(
        admission_year=None, total_score=None, subject_combination=None,
        preferred_majors=[], preferred_schools=[], location_preference=None,
        tuition_budget=None, constraints=[],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_missing_critical_slots_empty_state_returns_current_critical_set():
    missing = missing_critical_slots(_state())
    assert missing == ["admission_year", "total_score", "preferred_majors", "location_preference"]


def test_missing_critical_slots_complete_returns_empty():
    state = _state(
        admission_year=2026, total_score=25.0,
        preferred_majors=["computer_science"], location_preference="Ha Noi",
    )
    assert missing_critical_slots(state) == []


def test_next_follow_up_question_returns_first_missing_prompt():
    assert next_follow_up_question(_state()) == "Bạn đang xét tuyển cho năm nào?"
    assert next_follow_up_question(_state(
        admission_year=2026, total_score=25.0,
        preferred_majors=["x"], location_preference="Ha Noi",
    )) is None


def test_parse_slot_dispatches_to_named_parser():
    assert parse_slot("total_score", "29") == 29.0
    assert parse_slot("admission_year", "năm 2026") == 2026
    assert parse_slot("preferred_majors", "bất kỳ") is None  # không có parser
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_slots.py -v`
Expected: FAIL — `ImportError: cannot import name 'SLOTS'`.

- [ ] **Step 3: Thêm registry vào `services/profile/slots.py`**

Thêm vào đầu file (sau các import) và cuối file:

```python
from dataclasses import dataclass, field
from typing import Any, Callable, List


@dataclass(frozen=True)
class Slot:
    name: str
    critical: bool
    order: int
    follow_up: str
    parser: Callable[[str], Any] | None = None


# Nguồn DUY NHẤT cho định nghĩa slot. critical=True nghĩa là phải có trước khi
# chạy advisory. subject_combination để False ở slice 1 (Task 7 sẽ bật critical).
SLOTS: List[Slot] = [
    Slot("admission_year", True, 0, "Bạn đang xét tuyển cho năm nào?", parse_admission_year),
    Slot("total_score", True, 1, "Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?", parse_score),
    Slot("preferred_majors", True, 2, "Bạn quan tâm nhất đến ngành nào?", None),
    Slot("subject_combination", False, 3, "Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?", parse_subject_combination),
    Slot("location_preference", True, 4, "Bạn muốn học ở khu vực hoặc thành phố nào?", None),
    Slot("tuition_budget", False, 5, "Mức học phí bạn mong muốn khoảng bao nhiêu?", None),
]

_BY_NAME = {s.name: s for s in SLOTS}
_ORDERED = sorted(SLOTS, key=lambda s: s.order)


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or value == ""


def missing_critical_slots(state) -> List[str]:
    """Slot critical chưa điền, theo thứ tự. Duck-typed: dùng getattr nên chạy
    cho cả ChatProfileState lẫn StudentProfile."""
    return [s.name for s in _ORDERED if s.critical and _is_empty(getattr(state, s.name, None))]


def next_follow_up_question(state):
    missing = missing_critical_slots(state)
    if not missing:
        return None
    return _BY_NAME[missing[0]].follow_up


def parse_slot(name: str, raw_message: str):
    slot = _BY_NAME.get(name)
    return slot.parser(raw_message) if slot and slot.parser else None
```

> `field` import không dùng — bỏ nếu linter than phiền; giữ tối thiểu `dataclass`.

- [ ] **Step 4: Chạy để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_slots.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add services/profile/slots.py tests/services/profile/test_slots.py
git commit -m "feat(profile): add slot registry preserving current critical set (slice 1)"
```

---

## Task 3: `profile_state_service` delegate về registry (giữ nguyên hành vi)

**Files:**
- Modify: `services/chat/profile_state_service.py`
- Test: `tests/services/chat/test_profile_state_service.py` (đã có — phải vẫn xanh)

- [ ] **Step 1: Chạy test hiện có để chốt baseline xanh**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_profile_state_service.py -v`
Expected: PASS (5 passed) — đây là hành vi cần bảo toàn.

- [ ] **Step 2: Thay phần tự suy bằng delegate về registry**

Trong `services/chat/profile_state_service.py`:

Xóa khối `CRITICAL_SLOT_ORDER`, `missing_critical_slots`, `next_follow_up_question`, và hàm `parse_pending_slot_answer`; thay bằng re-export từ registry. Giữ `_extract_admission_year` và `merge_profile_state` (merge vẫn dùng `or` ở slice 1).

Nội dung mới của file:

```python
import re

from agents.models import StudentProfile
from services.chat.models import ChatProfileState
from services.profile.slots import (  # noqa: F401  (re-export cho callers/test cũ)
    missing_critical_slots,
    next_follow_up_question,
    parse_slot,
)


def _extract_admission_year(raw_message: str):
    match = re.search(r"\b20\d{2}\b", raw_message)
    return int(match.group(0)) if match else None


def parse_pending_slot_answer(pending_slot: str, raw_message: str):
    """Backward-compat shim → registry parser. Trả giá trị parse được hoặc None."""
    return parse_slot(pending_slot, raw_message)


def merge_profile_state(current: ChatProfileState, extracted: StudentProfile, raw_message: str) -> ChatProfileState:
    merged = ChatProfileState(
        admission_year=_extract_admission_year(raw_message) or current.admission_year,
        total_score=extracted.total_score or current.total_score,
        subject_combination=extracted.subject_combination or current.subject_combination,
        preferred_majors=extracted.preferred_majors or current.preferred_majors,
        preferred_schools=extracted.preferred_schools or current.preferred_schools,
        location_preference=extracted.location_preference or current.location_preference,
        tuition_budget=extracted.tuition_budget or current.tuition_budget,
        constraints=extracted.constraints or current.constraints,
    )
    merged.missing_slots = missing_critical_slots(merged)
    return merged
```

> `parse_slot("total_score", ...)` cho cùng kết quả với `parse_pending_slot_answer` cũ (regex số 0–40); các slot khác không có parser nên trả None — đúng hành vi cũ (cũ chỉ handle total_score).

- [ ] **Step 3: Chạy lại test hiện có để xác nhận vẫn PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_profile_state_service.py -v`
Expected: PASS (5 passed) — hành vi không đổi.

- [ ] **Step 4: Chạy test conversation_service để chắc không vỡ**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add services/chat/profile_state_service.py
git commit -m "refactor(profile): profile_state_service delegates slot logic to registry (slice 1)"
```

---

## Task 4: `build_profile` và `_normalize_profile` tính `missing_slots` qua registry

**Files:**
- Modify: `services/profile_service.py` (hàm `build_profile`)
- Modify: `services/profile_inference_service.py` (hàm `_normalize_profile`)
- Test: `tests/agents/test_profile_agent.py` (đã có — phải vẫn xanh)

- [ ] **Step 1: Viết test thất bại khẳng định build_profile dùng registry critical set**

Create `tests/services/profile/test_build_profile_missing_slots.py`:

```python
from services.profile_service import build_profile


def test_build_profile_missing_slots_uses_registry_critical_set():
    # Không nhắc gì → các slot critical (registry) phải nằm trong missing_slots.
    profile = build_profile("xin chào")
    assert "total_score" in profile.missing_slots
    assert "preferred_majors" in profile.missing_slots
    # subject_combination KHÔNG critical ở slice 1 → không xuất hiện.
    assert "subject_combination" not in profile.missing_slots
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_build_profile_missing_slots.py -v`
Expected: FAIL — build_profile hiện thêm `subject_combination` vào missing_slots (logic cũ).

- [ ] **Step 3: Sửa `build_profile` để tính missing_slots qua registry**

Trong `services/profile_service.py::build_profile`, thay khối tính `missing_slots` thủ công:

```python
    missing_slots: List[str] = []
    if score is None:
        missing_slots.append("total_score")
    if subject_combination is None:
        missing_slots.append("subject_combination")
    if not preferred_majors:
        missing_slots.append("preferred_majors")

    return StudentProfile(
        total_score=score,
        subject_combination=subject_combination,
        preferred_majors=preferred_majors,
        preferred_schools=preferred_schools,
        missing_slots=missing_slots,
    )
```

bằng:

```python
    profile = StudentProfile(
        total_score=score,
        subject_combination=subject_combination,
        preferred_majors=preferred_majors,
        preferred_schools=preferred_schools,
    )
    from services.profile.slots import missing_critical_slots
    profile.missing_slots = missing_critical_slots(profile)
    return profile
```

> Import cục bộ để tránh vòng import (`profile_service` được `slots` import). `missing_critical_slots` dùng getattr trên `StudentProfile` (có đủ field).

- [ ] **Step 4: Sửa `_normalize_profile` dùng registry**

Trong `services/profile_inference_service.py::_normalize_profile`, thay:

```python
    missing_slots = [
        slot for slot in profile.missing_slots if slot != "preferred_majors"
    ]
    return profile.model_copy(
        update={
            "preferred_majors": normalized_majors,
            "missing_slots": missing_slots,
        }
    )
```

bằng:

```python
    from services.profile.slots import missing_critical_slots
    updated = profile.model_copy(update={"preferred_majors": normalized_majors})
    updated.missing_slots = missing_critical_slots(updated)
    return updated
```

- [ ] **Step 5: Chạy test mới + test profile_agent**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_build_profile_missing_slots.py tests/agents/test_profile_agent.py -v`
Expected: PASS. Nếu `test_profile_agent_marks_missing_slots` vỡ (nó dùng FakeGateway trả `missing_slots` cố định, không qua build_profile/_normalize) → kiểm tra: test đó set `missing_slots` thủ công trong FakeGateway và đi qua `_normalize_profile` chỉ khi có preferred_majors. `economics` không nằm trong INTEREST map nên `_normalize_profile` trả sớm (no normalized_majors) → `missing_slots` giữ nguyên `["total_score","subject_combination"]`. Test vẫn PASS.

- [ ] **Step 6: Commit**

```bash
git add services/profile_service.py services/profile_inference_service.py tests/services/profile/test_build_profile_missing_slots.py
git commit -m "refactor(profile): compute missing_slots via registry in build_profile and normalize (slice 1)"
```

---

## Task 5: Chạy toàn bộ suite — chốt Slice 1 không đổi hành vi

**Files:** (không sửa — chỉ verify)

- [ ] **Step 1: Chạy full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS toàn bộ (không regression). Nếu có test vỡ KHÔNG liên quan subject_combination → sửa nguyên nhân trước khi tiếp.

- [ ] **Step 2: Commit (nếu có chỉnh sửa nhỏ)**

```bash
git add -A
git commit -m "test(profile): green full suite after registry refactor (slice 1)"
```

> Nếu Step 1 đã xanh và không sửa gì, bỏ qua Step 2.

---

## Task 6: Gỡ `_normalize_major_ids` khỏi đường missing_slots trùng lặp (dọn nhẹ)

**Files:**
- Modify: `services/chat/profile_state_service.py` (xác nhận không còn import chết)

- [ ] **Step 1: Grep tìm tham chiếu chết tới symbol đã xóa**

Run: `.\.venv\Scripts\python.exe -m pytest -q -k "profile or conversation"`
Và rà: không còn import `CRITICAL_SLOT_ORDER` từ `profile_state_service` ở bất kỳ đâu.

Run (PowerShell): `Select-String -Path services,tests -Pattern "CRITICAL_SLOT_ORDER" -Recurse`
Expected: không có kết quả (đã thay bằng registry). Nếu còn, cập nhật import sang `services.profile.slots`.

- [ ] **Step 2: Commit (nếu có sửa)**

```bash
git add -A
git commit -m "chore(profile): drop dead CRITICAL_SLOT_ORDER references (slice 1)"
```

---

## Task 7: (Quyết định §10-A) Bật `subject_combination` thành critical + cập nhật test

> **Gate:** chỉ làm nếu chốt §10-A = "subject_combination critical". Đây là task DUY NHẤT đổi hành vi của Slice 1, được cô lập để dễ review/revert.

**Files:**
- Modify: `services/profile/slots.py` (đổi 1 flag)
- Modify: `tests/services/profile/test_slots.py`
- Modify: `tests/services/chat/test_profile_state_service.py`
- Modify: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Đổi flag trong registry**

Trong `services/profile/slots.py`, dòng `subject_combination`:

```python
    Slot("subject_combination", True, 3, "Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?", parse_subject_combination),
```

(đổi `False` → `True`).

- [ ] **Step 2: Chạy full suite để liệt kê test vỡ**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: FAIL ở các test giả định "complete profile" mà thiếu `subject_combination`. Dự kiến gồm:
- `tests/services/profile/test_slots.py::test_missing_critical_slots_empty_state_returns_current_critical_set`
- `tests/services/profile/test_slots.py::test_missing_critical_slots_complete_returns_empty`
- `tests/services/profile/test_build_profile_missing_slots.py::test_build_profile_missing_slots_uses_registry_critical_set`
- `tests/services/chat/test_profile_state_service.py::test_merge_profile_state_keeps_previous_values_and_orders_missing_slots`
- `tests/services/chat/test_profile_state_service.py::test_merge_profile_state_returns_first_missing_slot_prompt`
- `tests/services/chat/test_profile_state_service.py::test_missing_critical_slots_complete_profile_returns_empty`
- `tests/services/chat/test_conversation_service.py::test_handle_advisory_clears_pending_question_when_complete` (đã có A00 → vẫn xanh)
- các hybrid test dùng `_complete_profile()` (thiếu subject_combination) → nay should_start_run=False.

- [ ] **Step 3: Cập nhật `test_slots.py`**

```python
def test_missing_critical_slots_empty_state_returns_current_critical_set():
    missing = missing_critical_slots(_state())
    assert missing == [
        "admission_year", "total_score", "preferred_majors",
        "subject_combination", "location_preference",
    ]


def test_missing_critical_slots_complete_returns_empty():
    state = _state(
        admission_year=2026, total_score=25.0,
        preferred_majors=["computer_science"], subject_combination="A00",
        location_preference="Ha Noi",
    )
    assert missing_critical_slots(state) == []
```

Và `test_build_profile_missing_slots.py`:

```python
def test_build_profile_missing_slots_uses_registry_critical_set():
    profile = build_profile("xin chào")
    assert "total_score" in profile.missing_slots
    assert "preferred_majors" in profile.missing_slots
    assert "subject_combination" in profile.missing_slots  # nay critical
```

- [ ] **Step 4: Cập nhật `test_profile_state_service.py`**

```python
def test_merge_profile_state_keeps_previous_values_and_orders_missing_slots():
    current = ChatProfileState(admission_year=2026, preferred_majors=["computer_science"])
    extracted = StudentProfile(total_score=27.0, subject_combination="A00", location_preference="Ha Noi")
    merged = merge_profile_state(current, extracted, "Em duoc khoang 27 diem A00 muon hoc tai Ha Noi")
    assert merged.total_score == 27.0
    assert merged.subject_combination == "A00"
    assert merged.missing_slots == []
    assert next_follow_up_question(merged) is None


def test_merge_profile_state_returns_first_missing_slot_prompt():
    merged = merge_profile_state(ChatProfileState(), StudentProfile(preferred_majors=["kinh_te"]), "Em muon hoc khoi kinh te")
    assert merged.missing_slots == ["admission_year", "total_score", "subject_combination", "location_preference"]
    assert next_follow_up_question(merged) == "Bạn đang xét tuyển cho năm nào?"


def test_missing_critical_slots_complete_profile_returns_empty():
    profile = ChatProfileState(
        admission_year=2026, total_score=25.0,
        preferred_majors=["computer_science"], subject_combination="A00",
        location_preference="Ha Noi",
    )
    assert missing_critical_slots(profile) == []
```

- [ ] **Step 5: Cập nhật `test_conversation_service.py::_complete_profile`**

```python
def _complete_profile():
    return ChatProfileState(
        admission_year=2026,
        total_score=27.0,
        preferred_majors=["computer_science"],
        subject_combination="A00",
        location_preference="Ha Noi",
        preferred_schools=["VNU-UET", "HUST"],
    )
```

- [ ] **Step 6: Chạy full suite, sửa nốt test còn vỡ theo cùng nguyên tắc**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS. Nếu còn test "complete profile" nào thiếu `subject_combination`, thêm `subject_combination="A00"` vào profile đó (chỉ test thiết lập hồ sơ đủ để chạy advisory).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(profile): make subject_combination a critical slot (slice 1, §10-A)"
```

---

## Self-Review (đã thực hiện khi viết plan)

**Spec coverage (§5):** Registry là nguồn duy nhất (Task 2), `profile_state_service`/`build_profile`/`_normalize_profile` delegate (Task 3,4), `subject_combination` critical (Task 7), gộp 3 định nghĩa lệch nhau (Task 3,4,6). ✔

**Placeholder scan:** Không có TBD/TODO; mọi step có code/command cụ thể. ✔

**Type consistency:** `Slot`, `SLOTS`, `missing_critical_slots(state)`, `next_follow_up_question(state)`, `parse_slot(name, raw)` dùng nhất quán giữa các task và khớp callers (`profile_state_service`, `build_profile`). ✔

**Rủi ro đã xử lý:** Task 1–6 giữ nguyên hành vi (Task 5 chốt suite xanh); thay đổi hành vi cô lập ở Task 7 kèm danh sách test phải sửa.
