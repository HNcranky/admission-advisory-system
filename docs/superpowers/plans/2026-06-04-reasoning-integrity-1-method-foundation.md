# Plan 1/5 — Nền tảng `admission_method` (EC-13 phần thu thập)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hệ thống biết và hỏi phương thức xét tuyển: module canonical codes/scales/parser, slot bắt buộc mới (sau điểm), field mới trên 2 profile model, extractor nhận diện phương thức, `parse_score` hết bug 4-chữ-số và nhận điểm ĐGNL.

**Architecture:** Một module nguồn-sự-thật `services/profile/admission_methods.py` (đọc alias từ `ingestion/normalization/dictionaries/methods.json` + alias hội thoại). Slot registry (`services/profile/slots.py`) là nơi duy nhất khai báo slot — thêm 1 entry là correction-rerun/missing-slots/follow-up tự hoạt động. Mọi thay đổi degrade graceful: parse không được → `None`, không raise.

**Tech Stack:** Python 3.12, Pydantic v2, pytest. Chạy test bằng system Python: `python -m pytest` (repo KHÔNG có venv).

**Spec:** `docs/superpowers/specs/2026-06-04-phase1-reasoning-integrity-design.md` (mục 4.1)

**Lưu ý commit:** không bao giờ `git push`; commit message KHÔNG kèm Co-Authored-By hay attribution AI.

---

### Task 1: Module `admission_methods` — codes, scales, parse, display

**Files:**
- Create: `services/profile/admission_methods.py`
- Test: `tests/services/profile/test_admission_methods.py`

- [ ] **Step 1: Viết test fail**

```python
# tests/services/profile/test_admission_methods.py
from services.profile.admission_methods import (
    METHOD_CODES,
    SCORE_SCALES,
    THANG_30_METHODS,
    method_display,
    parse_admission_method,
)


def test_method_codes_match_methods_json_vocabulary():
    assert METHOD_CODES == {
        "thpt_score", "school_record", "competency_test", "combined", "talent_admission",
    }


def test_score_scales_per_method():
    assert SCORE_SCALES["thpt_score"] == 30.0
    assert SCORE_SCALES["school_record"] == 30.0
    assert SCORE_SCALES["competency_test"] == 150.0
    assert SCORE_SCALES["combined"] == 100.0
    assert SCORE_SCALES["talent_admission"] is None  # không validate trần


def test_thang_30_methods_only_thpt_and_school_record():
    assert THANG_30_METHODS == {"thpt_score", "school_record"}


def test_parse_from_canonical_alias_with_diacritics():
    assert parse_admission_method("em xét điểm thi tốt nghiệp THPT") == "thpt_score"
    assert parse_admission_method("xét học bạ 3 năm") == "school_record"


def test_parse_from_conversational_alias_without_diacritics():
    assert parse_admission_method("em thi dgnl") == "competency_test"
    assert parse_admission_method("xet tuyen ket hop") == "combined"
    assert parse_admission_method("em duoc tuyen thang") == "talent_admission"


def test_parse_short_alias_uses_word_boundary():
    # "TSA" là alias ngắn → word boundary; không match bên trong từ khác.
    assert parse_admission_method("em thi TSA được 80") == "competency_test"
    assert parse_admission_method("em học lớp tsanv") is None


def test_parse_longest_alias_wins():
    # "điểm thi đánh giá năng lực" phải ra competency_test (alias dài hơn thắng
    # alias hội thoại "diem thi" của thpt_score).
    assert parse_admission_method("điểm thi đánh giá năng lực của em là 105") == "competency_test"


def test_parse_no_match_returns_none():
    assert parse_admission_method("em muốn học ở Hà Nội") is None
    assert parse_admission_method("") is None
    assert parse_admission_method(None) is None


def test_method_display_has_vietnamese_labels():
    assert method_display("thpt_score") == "điểm thi tốt nghiệp THPT"
    assert method_display("school_record") == "học bạ"
    assert method_display("competency_test") == "đánh giá năng lực / tư duy"
    assert method_display("combined") == "xét tuyển kết hợp"
    assert method_display("talent_admission") == "xét tuyển tài năng / tuyển thẳng"
    assert method_display("unknown_code") == "unknown_code"  # fallback an toàn
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/profile/test_admission_methods.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.profile.admission_methods'`

- [ ] **Step 3: Viết implementation**

```python
# services/profile/admission_methods.py
"""Nguồn sự thật phía profile cho phương thức xét tuyển (EC-04, EC-13).

Mã canonical khớp ingestion/normalization/dictionaries/methods.json.
Mọi hàm degrade graceful: không match/không đọc được dict → None, không raise.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional, Set

from services.profile_service import normalize_text

logger = logging.getLogger(__name__)

METHOD_CODES = {
    "thpt_score", "school_record", "competency_test", "combined", "talent_admission",
}

# Thang điểm tối đa theo phương thức; None = không validate trần (EC-04).
SCORE_SCALES = {
    "thpt_score": 30.0,
    "school_record": 30.0,
    "competency_test": 150.0,  # trần chung TSA(100)/HSA(150)
    "combined": 100.0,
    "talent_admission": None,
}

# Chỉ các phương thức thang 30 được áp score-fit bonus trong reasoning (EC-13).
THANG_30_METHODS = {"thpt_score", "school_record"}

_METHOD_DISPLAY = {
    "thpt_score": "điểm thi tốt nghiệp THPT",
    "school_record": "học bạ",
    "competency_test": "đánh giá năng lực / tư duy",
    "combined": "xét tuyển kết hợp",
    "talent_admission": "xét tuyển tài năng / tuyển thẳng",
}

# Alias hội thoại (đã normalize sẵn — normalize_text bỏ dấu, lowercase).
_EXTRA_ALIASES = {
    "thpt_score": ["diem thi", "thi thpt", "tot nghiep", "diem thi thpt"],
    "school_record": ["hoc ba"],
    "competency_test": ["dgnl", "danh gia nang luc", "dgtd", "tu duy", "tsa", "hsa"],
    "combined": ["ket hop", "xet tuyen ket hop"],
    "talent_admission": ["tuyen thang", "tai nang", "uu tien xet tuyen"],
}

_DICT_PATH = (
    Path(__file__).resolve().parents[2]
    / "ingestion" / "normalization" / "dictionaries" / "methods.json"
)


def _build_alias_index():
    """[(alias_normalized, code)] gộp _shared + mọi section trường, dài nhất trước."""
    pairs = set()
    try:
        data = json.loads(_DICT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # thiếu file/JSON hỏng → chỉ còn alias hội thoại
        logger.warning("admission_methods: không đọc được methods.json: %r", exc)
        data = {}
    for section in data.values():
        for code, info in section.items():
            if code not in METHOD_CODES:
                continue
            names = [info.get("canonical_name", "")] + list(info.get("aliases", []))
            for name in names:
                norm = normalize_text(name)
                if norm:
                    pairs.add((norm, code))
    for code, aliases in _EXTRA_ALIASES.items():
        for alias in aliases:
            pairs.add((alias, code))
    return sorted(pairs, key=lambda p: -len(p[0]))


_ALIAS_INDEX = _build_alias_index()


def _alias_hit(query_norm: str, alias: str) -> bool:
    if len(alias) <= 3:  # alias ngắn (tsa, hsa) → word boundary, tránh match trong từ
        return re.search(rf"\b{re.escape(alias)}\b", query_norm) is not None
    return alias in query_norm


def parse_admission_method(raw_message) -> Optional[str]:
    query = normalize_text(raw_message or "")
    if not query:
        return None
    for alias, code in _ALIAS_INDEX:
        if _alias_hit(query, alias):
            return code
    return None


def method_display(code) -> str:
    return _METHOD_DISPLAY.get(code, str(code))
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/profile/test_admission_methods.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add services/profile/admission_methods.py tests/services/profile/test_admission_methods.py
git commit -m "feat: admission method codes, scales and parser for profile side"
```

---

### Task 2: `candidate_method_codes` — map ngược display name của store về mã

**Files:**
- Modify: `services/profile/admission_methods.py` (thêm cuối file)
- Test: `tests/services/profile/test_admission_methods.py` (thêm cuối file)

Bối cảnh: store lưu `admission_method` là **display name** ("Xét điểm thi TN THPT", có thể ghép `;`), nhưng test fixture/dev row lưu thẳng **mã** ("thpt_score") — phải nhận cả hai.

- [ ] **Step 1: Viết test fail (append vào test file)**

```python
from types import SimpleNamespace

from services.profile.admission_methods import candidate_method_codes


def _candidate(method, school_id="hust"):
    return SimpleNamespace(admission_method=method, school_id=school_id)


def test_candidate_codes_accepts_raw_canonical_code():
    # Fixture/dev rows lưu thẳng mã code.
    assert candidate_method_codes(_candidate("thpt_score")) == {"thpt_score"}


def test_candidate_codes_maps_display_name():
    assert candidate_method_codes(_candidate("Xét điểm thi TN THPT")) == {"thpt_score"}


def test_candidate_codes_maps_joined_display_names():
    codes = candidate_method_codes(_candidate("Xét điểm thi TN THPT; Xét tuyển kết hợp"))
    assert codes == {"thpt_score", "combined"}


def test_candidate_codes_school_specific_display():
    assert candidate_method_codes(
        _candidate("Đánh giá tư duy (TSA)", school_id="hust")
    ) == {"competency_test"}


def test_candidate_codes_unknown_returns_none():
    # Không map được → None = unknown → caller KHÔNG gate theo phương thức.
    assert candidate_method_codes(_candidate("Phương thức bí ẩn XYZ")) is None
    assert candidate_method_codes(_candidate(None)) is None
    assert candidate_method_codes(_candidate("")) is None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/profile/test_admission_methods.py -v`
Expected: FAIL — `ImportError: cannot import name 'candidate_method_codes'`

- [ ] **Step 3: Implementation (append vào `services/profile/admission_methods.py`)**

```python
def candidate_method_codes(candidate) -> Optional[Set[str]]:
    """Set mã phương thức của một CandidateProgram; None = không xác định.

    Store lưu display name (có thể ghép ';'); fixture/dev lưu thẳng mã.
    Bất kỳ phần nào không map được → None (caller không được gate)."""
    raw = (getattr(candidate, "admission_method", None) or "").strip()
    if not raw:
        return None
    codes: Set[str] = set()
    for part in [p.strip() for p in raw.split(";") if p.strip()]:
        if part in METHOD_CODES:
            codes.add(part)
            continue
        mapped = None
        try:
            from ingestion.normalization.method_mapper import map_method
            mapped = map_method(part, school_id=getattr(candidate, "school_id", "") or "")
        except Exception as exc:  # ingestion không sẵn sàng → unknown, không raise
            logger.warning("candidate_method_codes: map_method lỗi cho %r: %r", part, exc)
            return None
        matched = False
        for code in str(mapped or "").split(";"):
            code = code.strip()
            if code in METHOD_CODES:
                codes.add(code)
                matched = True
        if not matched:
            return None  # một phần không map được → coi toàn bộ là unknown
    return codes or None
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/profile/test_admission_methods.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add services/profile/admission_methods.py tests/services/profile/test_admission_methods.py
git commit -m "feat: map candidate admission_method display names back to canonical codes"
```

---

### Task 3: Slot mới + sửa `parse_score`

**Files:**
- Modify: `services/profile/slots.py`
- Test: `tests/services/profile/test_slots.py`

- [ ] **Step 1: Sửa/thêm test (test_slots.py)**

Thay test `test_parse_score_out_of_range_returns_none` và `test_missing_critical_slots_empty_state_returns_current_critical_set`, `_state`, thêm test mới — nội dung đích:

```python
# THAY test_parse_score_out_of_range_returns_none bằng:
def test_parse_score_out_of_range_returns_none():
    assert parse_score("999") is None       # > 150 sanity cap
    assert parse_score("không có") is None


def test_parse_score_accepts_three_digit_competency_scores():
    assert parse_score("105") == 105.0      # điểm ĐGNL/ĐGTD
    assert parse_score("128,5") == 128.5


def test_parse_score_ignores_four_digit_year_tokens():
    # Bug cũ: "2026" bị regex \d{1,2} cắt thành 20.0 → điểm rác lọt vào profile.
    assert parse_score("2026") is None
    assert parse_score("năm 2026") is None
    assert parse_score("2026 em được 26.5") == 26.5
```

```python
# TRONG _state(): thêm key admission_method=None vào dict base:
    base = dict(
        admission_year=None, total_score=None, subject_combination=None,
        admission_method=None,
        preferred_majors=[], inferred_interest_tags=[], explicit_preferred_majors=[],
        preferred_schools=[], location_preference=None,
        tuition_budget=None, constraints=[],
    )
```

```python
# THAY test_missing_critical_slots_empty_state_returns_current_critical_set:
def test_missing_critical_slots_empty_state_returns_current_critical_set():
    missing = missing_critical_slots(_state())
    assert missing == [
        "admission_year", "total_score", "admission_method",
        "preferred_majors", "subject_combination",
    ]
```

```python
# THAY test_missing_critical_slots_complete_returns_empty (thêm admission_method):
def test_missing_critical_slots_complete_returns_empty():
    state = _state(
        admission_year=2026, total_score=25.0, admission_method="thpt_score",
        preferred_majors=["computer_science"], subject_combination="A00",
    )
    assert missing_critical_slots(state) == []
```

Tương tự thêm `admission_method="thpt_score"` vào state của các test:
`test_major_slot_satisfied_by_inferred_tags_only`, `test_major_slot_satisfied_by_explicit_majors_only`,
`test_location_preference_is_not_critical`, và state thứ hai trong
`test_next_follow_up_question_returns_first_missing_prompt`.

```python
# THÊM test mới cuối file:
def test_admission_method_slot_asked_right_after_score():
    state = _state(admission_year=2026, total_score=27.0)
    assert missing_critical_slots(state)[0] == "admission_method"
    assert "phương thức" in next_follow_up_question(state)


def test_parse_slot_dispatches_admission_method():
    assert parse_slot("admission_method", "em xét học bạ") == "school_record"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/profile/test_slots.py -v`
Expected: FAIL — missing list thiếu `admission_method`, parse_score("105") trả None, v.v.

- [ ] **Step 3: Implementation (slots.py)**

```python
# Đầu file: thêm import
from services.profile.admission_methods import parse_admission_method

# THAY parse_score:
def parse_score(raw_message: str) -> Optional[float]:
    """Bare-answer parser cho total_score: một số trong [0, 150].

    Lookaround chặn token 4 chữ số ("2026" là năm, không phải điểm); trần 150
    là sanity chung — trần theo phương thức do validate_profile_delta xử lý."""
    match = re.search(r"(?<!\d)\d{1,3}(?:[.,]\d+)?(?!\d)", raw_message or "")
    if not match:
        return None
    value = float(match.group(0).replace(",", "."))
    return value if 0 <= value <= 150 else None

# THAY danh sách SLOTS (chèn admission_method, đánh lại order):
SLOTS: List[Slot] = [
    Slot("admission_year", True, 0, "Bạn đang xét tuyển cho năm nào?", parse_admission_year),
    Slot("total_score", True, 1, "Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?", parse_score),
    Slot("admission_method", True, 2,
         "Bạn xét tuyển theo phương thức nào: điểm thi tốt nghiệp THPT, học bạ, đánh giá năng lực hay xét tuyển kết hợp?",
         parse_admission_method),
    Slot("preferred_majors", True, 3, "Bạn quan tâm nhất đến ngành nào?", None, present=_major_present),
    Slot("subject_combination", True, 4, "Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?", parse_subject_combination),
    Slot("location_preference", False, 5, "Bạn muốn học ở khu vực hoặc thành phố nào?", None),
    Slot("tuition_budget", False, 6, "Mức học phí bạn mong muốn khoảng bao nhiêu?", None),
]

# THÊM helper cuối file (Plan 2 dùng cho _handle_rejection):
def follow_up_for(slot_name: str):
    slot = _BY_NAME.get(slot_name)
    return slot.follow_up if slot else None
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/profile/test_slots.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add services/profile/slots.py tests/services/profile/test_slots.py
git commit -m "feat: admission_method critical slot and method-aware score parser"
```

---

### Task 4: Field mới trên models + advisory_runner mapping

**Files:**
- Modify: `services/chat/models.py:31-45` (ChatProfileState)
- Modify: `agents/models.py:6-14` (StudentProfile)
- Modify: `services/chat/advisory_runner.py:8-17`
- Test: `tests/services/chat/test_advisory_runner.py`

- [ ] **Step 1: Viết test fail (append vào test_advisory_runner.py)**

```python
def test_run_advisory_for_session_maps_admission_method(monkeypatch):
    captured = {}

    def fake_invoke(state):
        captured["state"] = state
        return {"final_answer": "ok"}

    monkeypatch.setattr("services.chat.advisory_runner.graph.invoke", fake_invoke)

    run_advisory_for_session(
        ChatProfileState(admission_year=2026, admission_method="thpt_score"),
        latest_user_message="hello",
    )

    assert captured["state"].student_profile.admission_method == "thpt_score"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/chat/test_advisory_runner.py -v`
Expected: FAIL — ChatProfileState không nhận field `admission_method` (Pydantic ValidationError) hoặc StudentProfile thiếu attr

- [ ] **Step 3: Implementation**

`services/chat/models.py` — trong `ChatProfileState`, thêm ngay sau `total_score`:

```python
    # Mã phương thức xét tuyển canonical (thpt_score/school_record/competency_test/
    # combined/talent_admission) — quyết định thang điểm hợp lệ và score-fit (EC-04/13).
    admission_method: Optional[str] = None
```

`agents/models.py` — trong `StudentProfile`, thêm ngay sau `total_score`:

```python
    admission_method: Optional[str] = None
```

`services/chat/advisory_runner.py` — trong constructor `StudentProfile(...)`, thêm sau `total_score=...`:

```python
        admission_method=profile_state.admission_method,
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/chat/test_advisory_runner.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add services/chat/models.py agents/models.py services/chat/advisory_runner.py tests/services/chat/test_advisory_runner.py
git commit -m "feat: admission_method field on profile models and advisory runner mapping"
```

---

### Task 5: Extractor + profile inference prompt nhận diện phương thức

**Files:**
- Modify: `services/profile/extractor.py:13-32, 52-61`
- Modify: `services/profile_inference_service.py:14-24`
- Test: `tests/services/profile/test_extractor.py`
- Test: `tests/services/test_profile_inference_service.py:83`

- [ ] **Step 1: Viết test fail (append vào test_extractor.py; sửa `_state` thêm `admission_method=None` vào dict base)**

```python
def test_llm_admission_method_display_name_is_coerced_to_code():
    # LLM hay trả display tiếng Việt thay vì mã → coerce qua parser.
    gw = FakeGatewayFields({"admission_method": "học bạ"})
    delta = extract_profile_update(
        "em xét học bạ nhé", known_state=_state(), active_slot=None,
        gateway=gw, resolver=_no_majors)
    assert delta["admission_method"] == "school_record"


def test_llm_admission_method_garbage_is_dropped():
    gw = FakeGatewayFields({"admission_method": "phương thức vũ trụ"})
    delta = extract_profile_update(
        "abc", known_state=_state(), active_slot=None,
        gateway=gw, resolver=_no_majors)
    assert "admission_method" not in delta


def test_deterministic_method_bare_answer_skips_llm():
    delta = extract_profile_update(
        "điểm thi THPT", known_state=_state(admission_year=2026, total_score=27.0),
        active_slot="admission_method", gateway=UnavailableGateway(), resolver=_no_majors)
    assert delta == {"admission_method": "thpt_score"}
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/services/profile/test_extractor.py -v`
Expected: FAIL — `admission_method` không nằm trong `_LLM_SLOT_KEYS` nên bị drop / parser chưa gắn

- [ ] **Step 3: Implementation**

`services/profile/extractor.py`:

```python
# Đầu file thêm import:
from services.profile.admission_methods import METHOD_CODES, parse_admission_method

# _LLM_SLOT_KEYS thêm "admission_method":
_LLM_SLOT_KEYS = {
    "admission_year", "total_score", "subject_combination", "admission_method",
    "location_preference", "tuition_budget", "preferred_schools", "constraints",
}

# STATE_UPDATE_PROMPT: THAY dòng total_score và THÊM dòng admission_method:
#   - total_score: số (0..150 tuỳ phương thức; thang phổ biến là 30)
#   - admission_method: một trong "thpt_score" (điểm thi TN THPT) | "school_record" (học bạ)
#     | "competency_test" (ĐGNL/ĐGTD) | "combined" (kết hợp) | "talent_admission" (tài năng/tuyển thẳng)

# _coerce_llm_delta: trong vòng for, sau check rỗng, thêm:
        if key == "admission_method" and value not in METHOD_CODES:
            value = parse_admission_method(str(value))
            if value is None:
                continue
```

`services/profile_inference_service.py` — trong `PROFILE_SYSTEM_PROMPT`, thêm sau dòng total_score:

```python
- admission_method: một trong "thpt_score" | "school_record" | "competency_test" | "combined" | "talent_admission", hoặc null
```

- [ ] **Step 4: Sửa assertion test_profile_inference_service**

`tests/services/test_profile_inference_service.py:83` — slot critical mới khiến missing đổi:

```python
    assert profile.missing_slots == ["admission_year", "admission_method"]
```

`tests/services/profile/test_build_profile_missing_slots.py` — thêm assertion:

```python
    assert "admission_method" in profile.missing_slots
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `python -m pytest tests/services/profile/test_extractor.py tests/services/test_profile_inference_service.py tests/services/profile/test_build_profile_missing_slots.py -v`
Expected: PASS toàn bộ

- [ ] **Step 6: Commit**

```bash
git add services/profile/extractor.py services/profile_inference_service.py tests/services/profile/test_extractor.py tests/services/test_profile_inference_service.py tests/services/profile/test_build_profile_missing_slots.py
git commit -m "feat: extract admission_method via LLM delta and inference prompt"
```

---

### Task 6: Cập nhật fixture hội thoại/e2e + flow test EC-13

**Files:**
- Modify: `tests/services/chat/test_conversation_service.py`
- Modify: `tests/e2e/test_advisory_flow.py:53-60`

Slot bắt buộc mới làm các fixture "profile đầy đủ" thiếu phương thức → flow không complete nữa. Sửa đúng các chỗ sau:

- [ ] **Step 1: Sửa fixture (5 chỗ)**

```python
# 1) test_handle_advisory_clears_pending_question_when_complete — extract dict thêm:
            "admission_method": "thpt_score",

# 2) _complete_profile() (khối Phase 5d) — thêm vào ChatProfileState:
        admission_method="thpt_score",

# 3) _completed_profile() (khối AC7) — thêm vào ChatProfileState:
        admission_method="thpt_score",

# 4) test_pending_advisory_answer_via_llm_extracted_slot_continues_flow — profile thêm:
        profile=ChatProfileState(admission_year=2026, total_score=25.0, admission_method="thpt_score"),
```

```python
# 5) test_bare_number_out_of_score_range_is_not_taken_as_total_score —
#    parser mới nhận tới 150 nên "99" giờ hợp lệ ở tầng parser; đổi message thành "999":
    result = service.handle_user_message("tok", "999")
    assert repo.profile_state.total_score is None
```

- [ ] **Step 2: Thêm test flow EC-13 (append cuối file)**

```python
# ─── Plan reasoning-integrity 1: admission_method slot (EC-13 thu thập) ───────

def test_score_answer_then_system_asks_admission_method():
    """EC-13: có điểm nhưng chưa biết phương thức → câu hỏi kế tiếp là phương thức."""
    profile = ChatProfileState(admission_year=2026)
    flow = FlowState(active_flow="ADVISORY_FLOW",
                     pending_question="Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?")
    service, repo = _make_service(
        profile=profile, flow=flow,
        extract=lambda text, known_state=None, active_slot=None: {},
    )
    result = service.handle_user_message("tok", "27")

    assert repo.profile_state.total_score == 27.0
    assert "phương thức" in result.assistant_message
    assert repo.flow_state.pending_question == (
        "Bạn xét tuyển theo phương thức nào: điểm thi tốt nghiệp THPT, học bạ, "
        "đánh giá năng lực hay xét tuyển kết hợp?"
    )


def test_method_bare_answer_fills_pending_method_slot():
    profile = ChatProfileState(admission_year=2026, total_score=27.0)
    flow = FlowState(active_flow="ADVISORY_FLOW",
                     pending_question="Bạn xét tuyển theo phương thức nào?")
    service, repo = _make_service(
        profile=profile, flow=flow,
        extract=lambda text, known_state=None, active_slot=None: {},
    )
    result = service.handle_user_message("tok", "điểm thi tốt nghiệp THPT")

    assert repo.profile_state.admission_method == "thpt_score"
    assert "ngành" in result.assistant_message.lower()  # hỏi tiếp slot ngành
```

- [ ] **Step 3: Sửa e2e fixture**

`tests/e2e/test_advisory_flow.py` — `_mock_profile()` thêm:

```python
        admission_method="thpt_score",
```

(giữ `missing_slots=[]`; candidate mock đã là `admission_method="thpt_score"` dạng mã — `candidate_method_codes` nhận trực tiếp.)

- [ ] **Step 4: Chạy bộ test liên quan**

Run: `python -m pytest tests/services/chat/test_conversation_service.py tests/e2e/test_advisory_flow.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Chạy TOÀN BỘ suite**

Run: `python -m pytest -q`
Expected: PASS (0 failed). Nếu có test khác fail vì missing `admission_method`, thêm `admission_method="thpt_score"` vào fixture tương ứng theo đúng pattern trên.

- [ ] **Step 6: Commit**

```bash
git add tests/services/chat/test_conversation_service.py tests/e2e/test_advisory_flow.py
git commit -m "test: cover admission_method slot in conversation flow and e2e fixtures"
```
