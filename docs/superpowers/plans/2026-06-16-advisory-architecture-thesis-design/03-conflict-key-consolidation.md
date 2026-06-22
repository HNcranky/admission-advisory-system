# Plan 03 — Gom logic conflict-key về một module (C4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa chuỗi conflict-key (đang tính trùng ở **3 module**) về một nguồn duy nhất `services/conflict/keys.py`, **giữ chuỗi key y hệt từng byte**.

**Architecture:** Cùng một quota-key text được tạo bởi 3 nơi với code giống hệt: `detection._conflict_key_text(_conflict_key(c))`, `conflict_agent._mark_uncertain` (inline `":".join([...])`), `explanation_service._candidate_conflict_key` (inline `":".join([...])`). Cutoff-key text là f-string ở `detection.py`. Rủi ro: các chuỗi này được **so khớp xuyên module** (vd `outcome_by_key = {o.conflict_key: ...}` trong explanation). Nếu lệch dù 1 ký tự → mất đánh dấu uncertain / mất tra cứu outcome. Do đó: viết **characterization test pin chuỗi literal trước**, rồi mới refactor.

**Tech Stack:** Python, pytest. **⚠️ Plan rủi ro nhất — có thể hoãn** nếu gần mốc nộp.

**Lệnh test:** `.venv/bin/python -m pytest -q`

**Phụ thuộc:** nên chạy **sau Plan 01** (để `keys.py` import `domain.models`). Vẫn chạy độc lập được vì `domain.models` tồn tại sẵn.

---

### Task 1: Baseline

- [ ] **Step 1: Chạy test conflict + explanation, ghi số pass**

Run: `.venv/bin/python -m pytest tests/services/conflict tests/agents/test_conflict_agent.py tests/agents/test_explanation_agent.py -q`
Expected: PASS (ghi số).

---

### Task 2: Tạo `services/conflict/keys.py` (TDD)

**Files:**
- Create: `services/conflict/keys.py`
- Test: `tests/services/conflict/test_keys.py`

- [ ] **Step 1: Viết test characterization (pin chuỗi literal)**

Tạo `tests/services/conflict/test_keys.py`:
```python
from types import SimpleNamespace

from services.conflict.keys import (
    quota_key_tuple,
    quota_key_text,
    quota_key_text_from_tuple,
    cutoff_key_text,
)


def _cand(**kw):
    base = dict(
        school_id="HUST",
        admission_year=2026,
        program_id="IT1",
        program_name="CNTT",
        admission_method="thpt",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_quota_key_text_basic():
    assert quota_key_text(_cand()) == "HUST:2026:IT1:thpt"


def test_quota_key_falls_back_to_program_name_when_no_id():
    assert quota_key_text(_cand(program_id=None)) == "HUST:2026:CNTT:thpt"


def test_quota_key_unknown_method_when_none():
    assert quota_key_text(_cand(admission_method=None)) == "HUST:2026:IT1:unknown_method"


def test_quota_tuple_and_text_consistent():
    c = _cand()
    assert quota_key_text_from_tuple(quota_key_tuple(c)) == quota_key_text(c)


def test_cutoff_key_text():
    assert cutoff_key_text("HUST", 2024, "IT1", "thpt") == "HUST:2024:IT1:thpt:cutoff"
```

- [ ] **Step 2: Chạy test — kỳ vọng FAIL (module chưa tồn tại)**

Run: `.venv/bin/python -m pytest tests/services/conflict/test_keys.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.conflict.keys'`.

- [ ] **Step 3: Tạo `services/conflict/keys.py`**

```python
"""Nguồn duy nhất cho chuỗi conflict-key (quota + cutoff).

Trước đây logic này lặp ở detection.py, agents/conflict_agent.py và
explanation_service.py. Các chuỗi được so khớp xuyên module nên định dạng phải
ổn định tuyệt đối.
"""
from typing import Tuple

from domain.models import CandidateProgram


def quota_key_tuple(candidate: CandidateProgram) -> Tuple[str, int, str, str]:
    return (
        candidate.school_id,
        candidate.admission_year,
        candidate.program_id or candidate.program_name,
        candidate.admission_method or "unknown_method",
    )


def quota_key_text_from_tuple(key: Tuple[str, int, str, str]) -> str:
    return ":".join(str(part) for part in key)


def quota_key_text(candidate: CandidateProgram) -> str:
    return quota_key_text_from_tuple(quota_key_tuple(candidate))


def cutoff_key_text(school_id: str, cutoff_year: int, program_key: str, method: str) -> str:
    return f"{school_id}:{cutoff_year}:{program_key}:{method}:cutoff"
```

- [ ] **Step 4: Chạy test — kỳ vọng PASS**

Run: `.venv/bin/python -m pytest tests/services/conflict/test_keys.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add services/conflict/keys.py tests/services/conflict/test_keys.py
git commit -m "feat(conflict): thêm module keys.py làm nguồn duy nhất cho conflict-key"
```

---

### Task 3: Refactor `detection.py` dùng `keys.py`

**Files:** Modify `services/conflict/detection.py`

- [ ] **Step 1: Thêm import, xóa 2 helper nội bộ**

Thêm sau dòng `from services.conflict.models import ...`:
```python
from services.conflict.keys import quota_key_tuple, quota_key_text_from_tuple, cutoff_key_text
```
Xóa hai hàm `_conflict_key` (def cũ trả tuple) và `_conflict_key_text` (def cũ `":".join(str(part)...)`).

- [ ] **Step 2: Thay 3 chỗ dùng**

Trong `detect_quota_conflicts`:
- `groups[_conflict_key(candidate)].append(candidate)` → `groups[quota_key_tuple(candidate)].append(candidate)`
- `conflict_key=_conflict_key_text(key),` → `conflict_key=quota_key_text_from_tuple(key),`

Trong `detect_cutoff_conflicts`, thay:
```python
                conflict_key=f"{school_id}:{cutoff_year}:{program_key}:{method}:cutoff",
```
bằng:
```python
                conflict_key=cutoff_key_text(school_id, cutoff_year, program_key, method),
```

- [ ] **Step 3: Chạy test detection**

Run: `.venv/bin/python -m pytest tests/services/conflict/test_detection.py -q`
Expected: PASS (đúng số baseline cho file này).

- [ ] **Step 4: Commit**

```bash
git add services/conflict/detection.py
git commit -m "refactor(conflict): detection.py dùng keys.py, bỏ helper key trùng"
```

---

### Task 4: Refactor `conflict_agent.py` + `explanation_service.py`

**Files:**
- Modify `agents/conflict_agent.py`
- Modify `services/explanation_service.py`

- [ ] **Step 1: `conflict_agent.py` — thêm import, rút gọn `_mark_uncertain`**

Thêm import (sau dòng `from services.conflict.resolution import ...`):
```python
from services.conflict.keys import quota_key_text
```
Thay toàn bộ thân `_mark_uncertain` (vòng lặp tự ghép key) bằng:
```python
def _mark_uncertain(state: AgentState, conflict_key: str, field_name: str) -> None:
    for candidate in state.retrieved_programs:
        if quota_key_text(candidate) == conflict_key and field_name not in candidate.data_uncertain_fields:
            candidate.data_uncertain_fields.append(field_name)
```
(Lưu ý: nếu Plan 02 đã chạy, import resolution là `services.conflict.resolution`; nếu chưa, là `services.conflict.resolution_agent` — đặt import `keys` ở nhóm import conflict bất kỳ.)

- [ ] **Step 2: `explanation_service.py` — thêm import, ủy quyền `_candidate_conflict_key`**

Thêm import top-level (cạnh `from services.conflict.source_labels import ...`):
```python
from services.conflict.keys import quota_key_text
```
Thay thân `_candidate_conflict_key`:
```python
def _candidate_conflict_key(candidate: CandidateProgram) -> str:
    """Khớp đúng key conflict dùng (services/conflict/keys.py::quota_key_text)."""
    return quota_key_text(candidate)
```

- [ ] **Step 3: Chạy test liên quan**

Run: `.venv/bin/python -m pytest tests/agents/test_conflict_agent.py tests/agents/test_explanation_agent.py -q`
Expected: PASS (đúng số baseline).

- [ ] **Step 4: Commit**

```bash
git add agents/conflict_agent.py services/explanation_service.py
git commit -m "refactor(conflict): conflict_agent + explanation dùng keys.py"
```

---

### Task 5: Nghiệm thu toàn cục

- [ ] **Step 1: Không còn logic key trùng ngoài keys.py**

Run: `grep -rn '":".join' services/conflict/detection.py services/explanation_service.py agents/conflict_agent.py`
Expected: **rỗng** (mọi ghép key đã chuyển vào `keys.py`).

- [ ] **Step 2: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. So với trạng thái suite ngay trước Plan 03, chỉ tăng đúng 5 test (`test_keys.py`); **không có FAIL/ERROR mới**.

- [ ] **Step 3 (khuyến nghị): kiểm tra hành vi e2e conflict không đổi**

Nếu Docker DB đang chạy: `.venv/bin/python -m pytest tests/e2e -q -k conflict`
Expected: như trước (1 skip `test_real_conflict_resolution` là bình thường, theo FACTS.md).

---

## Self-Review

- **Spec coverage:** thực thi C4 (§6) + tiêu chí §9.3 (chuỗi key trước/sau khớp tuyệt đối). ✓
- **Placeholder scan:** không có; mọi code/edit cụ thể. ✓
- **Type/tên consistency:** hàm `quota_key_tuple/quota_key_text/quota_key_text_from_tuple/cutoff_key_text` định nghĩa ở Task 2, dùng nhất quán ở Task 3–4. ✓
- **Rủi ro đã chặn:** characterization test pin literal trước refactor; full suite (test_detection/test_conflict_agent/test_explanation_agent dựng `CandidateProgram` thật) là guard tích hợp. ✓
