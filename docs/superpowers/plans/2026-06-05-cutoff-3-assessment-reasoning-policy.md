# Cutoff Plan 3 — Assessment module, reasoning margin-based & policy guardrails

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pure module `services/cutoff/assessment.py` (nguồn sự thật duy nhất cho ngữ nghĩa cutoff: margin/borderline/volatility/conflict), reasoning thay bonus ngưỡng tuyệt đối bằng margin thật + band cap, policy thêm flag/claim cho EC-18/EC-14.

**Architecture:** `assess_cutoff()` thuần (không I/O), trả `CutoffAssessment` (model ở `agents/models.py`, Plan 1) hoặc `None` → reasoning fallback hành vi cũ. Reasoning gọi ở ngả 3 (đúng phương thức, sau check tổ hợp EC-12). Decision-changing → nhãn bảo thủ + `data_uncertain_fields += "cutoff_score"` + dual-value caution thay caution một-nguồn.

**Tech Stack:** Python thuần, pytest (fixture theo pattern `tests/agents/test_reasoning_agent.py`).

**Phụ thuộc:** Plan 1 (models). KHÔNG cần Plan 2 (test dùng fixture `cutoff_history` trực tiếp).

---

### Task 1: `services/cutoff/assessment.py`

**Files:**
- Create: `services/cutoff/__init__.py` (rỗng)
- Create: `services/cutoff/assessment.py`
- Test: `tests/services/cutoff/__init__.py` (rỗng), `tests/services/cutoff/test_assessment.py`

- [x] **Step 1: Viết test fail** — create `tests/services/cutoff/test_assessment.py`:

```python
from agents.models import CutoffEntry
from services.cutoff.assessment import assess_cutoff, classify_margin


def _e(year, score, source="https://ts.hust.edu.vn/dc", trust=5, method="thpt_score", scale=30.0):
    return CutoffEntry(cutoff_year=year, admission_method=method, cutoff_score=score,
                       score_scale=scale, source_url=source, trust_level=trust)


# ─── classify_margin ──────────────────────────────────────────────────────────

def test_classify_margin_bands():
    assert classify_margin(26.0, 26.5) == "below"        # margin < 0
    assert classify_margin(26.20, 26.20) == "borderline" # margin = 0
    assert classify_margin(26.25, 26.20) == "borderline" # EC-14: +0.05
    assert classify_margin(26.45, 26.20) == "above"      # +0.25 = ngưỡng trên của borderline
    assert classify_margin(28.0, 26.5) == "above"


# ─── Gate trả None ────────────────────────────────────────────────────────────

def test_gate_returns_none_without_score_or_method_or_history():
    history = [_e(2025, 26.2)]
    assert assess_cutoff(None, "thpt_score", history) is None
    assert assess_cutoff(27.0, None, history) is None
    assert assess_cutoff(27.0, "competency_test", history) is None   # ngoài thang 30
    assert assess_cutoff(27.0, "thpt_score", []) is None
    # entry khác method / khác thang bị lọc hết → None (KHÔNG quy đổi thang)
    assert assess_cutoff(27.0, "thpt_score", [_e(2025, 80, method="competency_test", scale=150.0)]) is None
    assert assess_cutoff(27.0, "thpt_score", [_e(2025, 80, scale=150.0)]) is None


# ─── EC-14: sát ngưỡng ───────────────────────────────────────────────────────

def test_ec14_borderline_margin():
    a = assess_cutoff(26.25, "thpt_score", [_e(2025, 26.20)])
    assert a.score_fit == "borderline"
    assert a.reference_year == 2025
    assert a.margin == 0.05
    assert a.conflicted is False and a.decision_changing is False and a.volatile is False


# ─── EC-15: biến động lịch sử ────────────────────────────────────────────────

def test_ec15_volatile_history_overrides_to_uncertain():
    history = [_e(2023, 24.8), _e(2024, 26.7), _e(2025, 25.9)]
    a = assess_cutoff(26.4, "thpt_score", history)
    assert a.score_fit == "uncertain"                    # override dù margin 2025 = +0.5 (above)
    assert a.volatile is True
    assert a.volatility_min == 24.8 and a.volatility_max == 26.7
    assert a.years_used == [2023, 2024, 2025]
    assert a.reference_year == 2025 and a.margin == 0.5


def test_two_years_never_volatile():
    a = assess_cutoff(26.4, "thpt_score", [_e(2024, 24.0), _e(2025, 25.9)])
    assert a.volatile is False and a.score_fit == "above"


def test_stable_three_years_not_volatile():
    a = assess_cutoff(27.0, "thpt_score", [_e(2023, 26.0), _e(2024, 26.4), _e(2025, 26.5)])
    assert a.volatile is False and a.score_fit == "above"


# ─── EC-16: hai nguồn lệch nhau ──────────────────────────────────────────────

def test_ec16_decision_changing_conflict_takes_conservative_label():
    history = [
        _e(2025, 26.2, source="https://truong.example/dc", trust=4),
        _e(2025, 26.8, source="https://dhqg.example/dc", trust=5),
    ]
    a = assess_cutoff(26.5, "thpt_score", history)
    # 26.5−26.2=+0.3→above; 26.5−26.8=−0.3→below ⇒ nhãn bảo thủ = below
    assert a.conflicted is True and a.decision_changing is True
    assert a.score_fit == "below"
    assert {v["value"] for v in a.latest_values} == {26.2, 26.8}
    # margin tính theo nguồn trust cao nhất (26.8)
    assert a.margin == -0.3


def test_conflict_same_label_is_not_decision_changing():
    history = [_e(2025, 25.0, trust=5), _e(2025, 25.2, source="https://b", trust=4)]
    a = assess_cutoff(27.0, "thpt_score", history)
    assert a.conflicted is True and a.decision_changing is False
    assert a.score_fit == "above"


def test_trust_tiebreak_prefers_higher_cutoff_when_equal_trust():
    history = [_e(2025, 26.0, trust=5), _e(2025, 26.4, source="https://b", trust=5)]
    a = assess_cutoff(28.0, "thpt_score", history)
    assert a.margin == 1.6                               # so với 26.4 (giá trị cao hơn = bảo thủ hơn)


def test_scale_none_treated_as_thang_30():
    a = assess_cutoff(27.0, "thpt_score", [_e(2025, 26.0, scale=None)])
    assert a is not None and a.score_fit == "above"
```

- [x] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/services/cutoff/test_assessment.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.cutoff'`

- [x] **Step 3: Implement** — create `services/cutoff/__init__.py` (rỗng) và `services/cutoff/assessment.py`:

```python
"""Đối chiếu điểm hồ sơ với điểm chuẩn lịch sử (EC-14/15/16/18) — pure, không I/O.

Hằng số là tham số chỉnh được (docs/edge-case.md không quy định số cụ thể);
giá trị khởi điểm được neo theo ví dụ trong doc:
- BORDERLINE_MARGIN=0.25: EC-14 (+0.05 so với cutoff) phải ra "borderline".
- VOLATILITY_RANGE=1.0:   EC-15 (range 24.8–26.7 = 1.9) phải ra "uncertain".
- SAFE_MARGIN=1.0:        chỉ margin >= 1.0 mới nhận bonus tối đa ở reasoning.
- MIN_YEARS_VOLATILITY=3: dưới 3 năm dữ liệu thì không kết luận biến động.

Tuyệt đối KHÔNG quy đổi giữa các thang điểm: entry khác method/khác thang 30
bị lọc ở gate, không bao giờ được so trực tiếp.
"""
from typing import List, Optional

from agents.models import CutoffAssessment, CutoffEntry
from services.profile.admission_methods import THANG_30_METHODS

BORDERLINE_MARGIN = 0.25
SAFE_MARGIN = 1.0
VOLATILITY_RANGE = 1.0
MIN_YEARS_VOLATILITY = 3

_FIT_ORDER = {"below": 0, "borderline": 1, "above": 2}  # nhỏ hơn = bảo thủ hơn


def classify_margin(total_score: float, cutoff_score: float) -> str:
    """Nhãn per-value: below / borderline / above (EC-14)."""
    margin = total_score - cutoff_score
    if margin < 0:
        return "below"
    if margin < BORDERLINE_MARGIN:
        return "borderline"
    return "above"


def _usable(admission_method: str, history: List[CutoffEntry]) -> List[CutoffEntry]:
    return [
        e for e in history
        if e.admission_method == admission_method
        and (e.score_scale is None or e.score_scale == 30)
    ]


def _best_of(entries: List[CutoffEntry]) -> CutoffEntry:
    """Nguồn trust cao nhất; hoà trust → giá trị cao hơn (bảo thủ: margin nhỏ hơn)."""
    return max(
        entries,
        key=lambda e: (
            e.trust_level if e.trust_level is not None else -1,
            e.cutoff_score,
        ),
    )


def assess_cutoff(
    total_score: Optional[float],
    admission_method: Optional[str],
    cutoff_history: List[CutoffEntry],
) -> Optional[CutoffAssessment]:
    """None khi không đủ điều kiện so sánh → caller giữ nguyên hành vi cũ."""
    if total_score is None or admission_method not in THANG_30_METHODS:
        return None
    entries = _usable(admission_method, cutoff_history or [])
    if not entries:
        return None

    years = sorted({e.cutoff_year for e in entries})
    reference_year = years[-1]
    latest = [e for e in entries if e.cutoff_year == reference_year]

    distinct_values = sorted({e.cutoff_score for e in latest})
    fits = {classify_margin(total_score, value) for value in distinct_values}
    conflicted = len(distinct_values) > 1
    decision_changing = len(fits) > 1
    score_fit = min(fits, key=lambda f: _FIT_ORDER[f])  # nhãn bảo thủ nhất (EC-16)

    best = _best_of(latest)
    margin = round(total_score - best.cutoff_score, 2)

    volatile = False
    volatility_min = volatility_max = None
    if len(years) >= MIN_YEARS_VOLATILITY:
        per_year = [
            _best_of([e for e in entries if e.cutoff_year == year]).cutoff_score
            for year in years
        ]
        volatility_min, volatility_max = min(per_year), max(per_year)
        if volatility_max - volatility_min >= VOLATILITY_RANGE:
            volatile = True
            score_fit = "uncertain"                      # override (EC-15)

    return CutoffAssessment(
        score_fit=score_fit,
        reference_year=reference_year,
        margin=margin,
        latest_values=[
            {"value": e.cutoff_score, "source_url": e.source_url, "trust_level": e.trust_level}
            for e in sorted(latest, key=lambda e: e.cutoff_score)
        ],
        conflicted=conflicted,
        decision_changing=decision_changing,
        volatile=volatile,
        volatility_min=volatility_min,
        volatility_max=volatility_max,
        years_used=years,
    )
```

- [x] **Step 4: Chạy test**

Run: `python -m pytest tests/services/cutoff/test_assessment.py -q`
Expected: PASS 11 test.

- [x] **Step 5: Commit**

```bash
git add services/cutoff/ tests/services/cutoff/
git commit -m "feat: pure cutoff assessment (margin, borderline, volatility, conflict semantics)"
```

---

### Task 2: Reasoning dùng margin thật (EC-14/15/16 phía ranking)

**Files:**
- Modify: `services/reasoning_service.py`
- Test: `tests/agents/test_reasoning_agent.py` (append)

- [x] **Step 1: Viết test fail** — append vào `tests/agents/test_reasoning_agent.py` (đã có helper `_candidate`; thêm import đầu file: `from agents.models import CutoffEntry`):

```python
def _hist(*pairs, source="https://ts.hust.edu.vn/dc", trust=5):
    return [
        CutoffEntry(cutoff_year=y, admission_method="thpt_score", cutoff_score=s,
                    score_scale=30.0, source_url=source, trust_level=trust)
        for (y, s) in pairs
    ]


def _profile_27():
    return StudentProfile(
        total_score=27.0, subject_combination="A00", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )


def test_margin_bonus_replaces_absolute_threshold():
    """Có cutoff: margin 1.5 → +0.10 với reason nêu năm tham chiếu (không dùng heuristic 26/24)."""
    state = AgentState(user_query="test")
    state.student_profile = _profile_27()
    state.retrieved_programs = [_candidate(cutoff_history=_hist((2025, 25.5)))]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.score == 1.0                               # 0.40+0.35+0.15+0.10
    assert any("tham chiếu 2025" in r for r in rec.reasons)
    assert rec.cutoff_assessment is not None and rec.cutoff_assessment.score_fit == "above"


def test_small_positive_margin_gets_half_bonus():
    state = AgentState(user_query="test")
    state.student_profile = _profile_27()
    state.retrieved_programs = [_candidate(cutoff_history=_hist((2025, 26.5)))]  # margin +0.5

    output = reasoning_agent(state)

    assert output.ranked_recommendations[0].score == 0.95  # +0.05


def test_ec14_borderline_caps_band_at_match_with_caution():
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=26.25, subject_combination="A01", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    state.retrieved_programs = [
        _candidate(subject_combinations=["A00", "A01"], cutoff_history=_hist((2025, 26.20)))
    ]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.band == "match"                            # 0.90 → "safe" nếu không cap
    assert any("sát ngưỡng tham chiếu 2025" in c.lower() for c in rec.cautions)
    assert rec.cutoff_assessment.score_fit == "borderline"


def test_below_reference_caps_band_at_reach():
    state = AgentState(user_query="test")
    state.student_profile = _profile_27()
    state.retrieved_programs = [_candidate(cutoff_history=_hist((2025, 28.0)))]  # margin −1.0

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.band == "reach"
    assert any("thấp hơn mức tham chiếu 2025" in c.lower() for c in rec.cautions)


def test_ec15_volatile_history_caps_match_with_range_caution():
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=26.4, subject_combination="A00", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    state.retrieved_programs = [
        _candidate(cutoff_history=_hist((2023, 24.8), (2024, 26.7), (2025, 25.9)))
    ]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.band == "match"
    assert any("dao động 24.8–26.7" in c for c in rec.cautions)
    assert rec.cutoff_assessment.score_fit == "uncertain"


def test_ec16_decision_changing_marks_uncertain_and_dual_caution():
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=26.5, subject_combination="A00", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    history = _hist((2025, 26.2), trust=4) + _hist((2025, 26.8), source="https://dhqg/dc", trust=5)
    state.retrieved_programs = [_candidate(cutoff_history=history)]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    candidate = output.retrieved_programs[0]
    assert "cutoff_score" in candidate.data_uncertain_fields
    assert rec.band == "reach"                            # nhãn bảo thủ below → cap reach
    assert any("các nguồn ghi khác nhau về điểm chuẩn" in c.lower() for c in rec.cautions)
    # caution một-nguồn ("thấp hơn mức tham chiếu") bị THAY bằng dual note:
    assert not any("thấp hơn mức tham chiếu" in c.lower() for c in rec.cautions)


def test_no_history_falls_back_to_absolute_threshold():
    state = AgentState(user_query="test")
    state.student_profile = _profile_27()
    state.retrieved_programs = [_candidate()]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.score == 1.0                               # heuristic cũ: 27 >= 26 → +0.10
    assert rec.cutoff_assessment is None
```

- [x] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/agents/test_reasoning_agent.py -q`
Expected: 7 test mới FAIL (TypeError `cutoff_assessment` chưa gắn / band không cap); test cũ PASS.

- [x] **Step 3: Implement** — sửa `services/reasoning_service.py`:

(a) Imports — đổi dòng 4-9 thành:

```python
from services.cutoff.assessment import SAFE_MARGIN, assess_cutoff
from services.explanation_service import _fmt_num, _program_label
from services.profile.admission_methods import (
    THANG_30_METHODS,
    candidate_method_codes,
    method_display,
)
```

(b) Thêm helpers sau `_score_to_band` (sau dòng 37):

```python
_BAND_TIGHTNESS = {"reach": 0, "match": 1, "safe": 2}  # nhỏ hơn = chặt hơn


def _cap_band(band: str, cap):
    """Hạ band xuống cap nếu band đang lỏng hơn; 'unknown' giữ nguyên."""
    if cap is None or band not in _BAND_TIGHTNESS:
        return band
    return cap if _BAND_TIGHTNESS[band] > _BAND_TIGHTNESS[cap] else band


def _tightest_cap(*caps):
    real = [c for c in caps if c is not None]
    return min(real, key=lambda c: _BAND_TIGHTNESS[c]) if real else None


def _fmt_margin(margin: float) -> str:
    return f"{margin:+g}"


def _apply_assessment(assessment, reasons, cautions, candidate):
    """Bảng WS5 spec: trả (bonus, band_cap); ghi reasons/cautions/data_uncertain tại chỗ.

    decision_changing: caution của nhãn bị THAY bằng dual-value note (phát biểu
    một-nguồn gây hiểu lầm khi nguồn khác nói ngược lại)."""
    bonus = 0.0
    cap = None
    year = assessment.reference_year

    if assessment.score_fit == "above":
        if assessment.margin >= SAFE_MARGIN:
            bonus = 0.10
            reasons.append(
                f"Điểm cao hơn rõ rệt mức tham chiếu {year} ({_fmt_margin(assessment.margin)})."
            )
        else:
            bonus = 0.05
            reasons.append(
                f"Điểm trên mức tham chiếu {year} ({_fmt_margin(assessment.margin)})."
            )
    elif assessment.score_fit == "borderline":
        cap = "match"
        if not assessment.decision_changing:
            cautions.append(
                f"Điểm sát ngưỡng tham chiếu {year} ({_fmt_margin(assessment.margin)}) "
                "— lựa chọn có rủi ro."
            )
    elif assessment.score_fit == "below":
        cap = "reach"
        if not assessment.decision_changing:
            cautions.append(
                f"Điểm thấp hơn mức tham chiếu {year} ({_fmt_margin(assessment.margin)})."
            )
    else:  # "uncertain" — điểm chuẩn biến động (EC-15)
        cap = "match"
        cautions.append(
            f"Điểm chuẩn dao động {_fmt_num(assessment.volatility_min)}–"
            f"{_fmt_num(assessment.volatility_max)} qua {len(assessment.years_used)} năm "
            "gần nhất, chưa thể kết luận."
        )

    if assessment.decision_changing:
        cap = _tightest_cap(cap, "match")
        if "cutoff_score" not in candidate.data_uncertain_fields:
            candidate.data_uncertain_fields.append("cutoff_score")
        values = " / ".join(_fmt_num(v["value"]) for v in assessment.latest_values)
        cautions.append(
            f"Các nguồn ghi khác nhau về điểm chuẩn tham chiếu {year} ({values}); "
            "kết luận thay đổi theo nguồn nên đánh giá ở mức thận trọng."
        )
    return bonus, cap
```

(c) Trong `reason_candidates`, đầu vòng for (sau `eligible = True`, dòng 59) thêm:

```python
        assessment = None
        cutoff_cap = None
```

(d) Thay NGUYÊN khối `if profile.total_score is not None:` (dòng 108-130) bằng:

```python
        if profile.total_score is not None:
            if method_mismatch:
                pass  # đã caution ở ngả 1; không đối chiếu điểm
            elif profile_method in THANG_30_METHODS:
                assessment = assess_cutoff(
                    profile.total_score, profile_method, candidate.cutoff_history
                )
                if assessment is not None:
                    bonus, cutoff_cap = _apply_assessment(
                        assessment, reasons, cautions, candidate
                    )
                    score += bonus
                # Fallback heuristic tuyệt đối khi CHƯA có dữ liệu điểm chuẩn.
                elif profile.total_score >= 26:
                    score += 0.10
                    reasons.append("Điểm dự kiến đang ở mức cạnh tranh tốt.")
                elif profile.total_score >= 24:
                    score += 0.05
                    reasons.append("Điểm dự kiến đang ở mức có thể cân nhắc.")
                else:
                    cautions.append(
                        "Điểm dự kiến có thể thấp hơn mức cạnh tranh của một số chương trình."
                    )
            elif profile_method is None:
                cautions.append("Hồ sơ chưa rõ phương thức xét tuyển nên chưa đánh giá mức điểm.")
            else:
                cautions.append(
                    f"Điểm theo {method_display(profile_method)} chưa thể đối chiếu trực tiếp "
                    "với dữ liệu tham chiếu hiện có."
                )
        else:
            cautions.append("Hồ sơ còn thiếu điểm nên chưa thể ước lượng mức cạnh tranh.")
```

(e) Sau `band = _score_to_band(score, has_missing_critical)` (dòng 133) thêm:

```python
        band = _cap_band(band, cutoff_cap)
```

(f) Trong khối tạo `RankedRecommendation` (dòng 149-158), thêm field:

```python
                cutoff_assessment=assessment,
```

- [x] **Step 4: Chạy test**

Run: `python -m pytest tests/agents/test_reasoning_agent.py tests/services -q`
Expected: PASS toàn bộ (7 mới + cũ; `test_uncertain_quota_candidate_is_not_safe_band` vẫn xanh — total 29, không history → fallback +0.10).

- [x] **Step 5: Commit**

```bash
git add services/reasoning_service.py tests/agents/test_reasoning_agent.py
git commit -m "feat: margin-based score fit with band caps from historical cutoffs (EC-14/15/16)"
```

---

### Task 3: Policy guardrails

**Files:**
- Modify: `services/policy_service.py`
- Test: `tests/agents/test_policy_agent.py` (append)

- [x] **Step 1: Viết test fail** — append vào `tests/agents/test_policy_agent.py` (thêm các import sau đầu file nếu chưa có):

```python
from agents.models import (
    CandidateProgram,
    CutoffAssessment,
    Evidence,
    RankedRecommendation,
    StudentProfile,
)
from services.policy_service import evaluate_policy_guardrails


def _cutoff_candidate():
    return CandidateProgram(
        candidate_id="hust:2026:computer_science:thpt_score", school_id="hust",
        school_name="HUST", admission_year=2026, program_id="computer_science",
        program_name="Khoa hoc May tinh", admission_method="thpt_score",
        evidence=[Evidence(source_url="https://src", school_name="HUST",
                           admission_year=2026, field_name="record")],
    )


def _rec_with(assessment):
    return RankedRecommendation(
        candidate_id="hust:2026:computer_science:thpt_score", band="match",
        score=0.75, summary="fit", cutoff_assessment=assessment,
    )


def test_policy_flags_historical_cutoff_reference_for_any_assessment():
    rec = _rec_with(CutoffAssessment(score_fit="above", reference_year=2025, margin=1.5))
    decision, _ = evaluate_policy_guardrails(
        "tu van", StudentProfile(total_score=27, admission_method="thpt_score"),
        [_cutoff_candidate()], [rec], [],
    )
    assert "historical_cutoff_reference" in decision.policy_flags
    assert "no_admission_assertion_on_reference_cutoff" not in decision.blocked_claims


def test_policy_blocks_assertion_for_borderline_uncertain_or_decision_changing():
    for assessment in (
        CutoffAssessment(score_fit="borderline", reference_year=2025, margin=0.05),
        CutoffAssessment(score_fit="uncertain", reference_year=2025, margin=0.5, volatile=True),
        CutoffAssessment(score_fit="below", reference_year=2025, margin=-0.3,
                         conflicted=True, decision_changing=True),
    ):
        decision, _ = evaluate_policy_guardrails(
            "tu van", StudentProfile(total_score=26.25, admission_method="thpt_score"),
            [_cutoff_candidate()], [_rec_with(assessment)], [],
        )
        assert "no_admission_assertion_on_reference_cutoff" in decision.blocked_claims


def test_policy_no_cutoff_flags_without_assessment():
    decision, _ = evaluate_policy_guardrails(
        "tu van", StudentProfile(total_score=27, admission_method="thpt_score"),
        [_cutoff_candidate()], [_rec_with(None)], [],
    )
    assert "historical_cutoff_reference" not in decision.policy_flags
```

- [x] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/agents/test_policy_agent.py -q`
Expected: 3 test mới FAIL (flag/claim chưa tồn tại).

- [x] **Step 3: Implement** — trong `services/policy_service.py`, thêm sau khối `if candidates and not recommendations:` (sau dòng 57):

```python
    assessments = [
        rec.cutoff_assessment for rec in recommendations if rec.cutoff_assessment is not None
    ]
    if assessments:
        # EC-18: mọi đánh giá dựa trên cutoff lịch sử → explanation phải render caveat năm tham chiếu.
        policy_flags.append("historical_cutoff_reference")
        if any(
            a.score_fit in {"borderline", "uncertain"} or a.decision_changing
            for a in assessments
        ):
            # EC-14/15/16: chặn ngôn ngữ khẳng định trúng tuyển khi sát ngưỡng/biến động/conflict.
            blocked_claims.append("no_admission_assertion_on_reference_cutoff")
```

- [x] **Step 4: Chạy test**

Run: `python -m pytest tests/agents/test_policy_agent.py tests/e2e/test_advisory_flow.py -q`
Expected: PASS toàn bộ.

- [x] **Step 5: Commit**

```bash
git add services/policy_service.py tests/agents/test_policy_agent.py
git commit -m "feat: policy guardrails for historical cutoff reference (EC-14/18)"
```
