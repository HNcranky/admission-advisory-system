# Plan 3/5 — Reasoning trung thực: eligibility & method gating (EC-12, EC-13)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chương trình sai tổ hợp (đúng phương thức) → `EligibilityCheck(eligible=False)` và KHÔNG được xếp hạng; chương trình khác phương thức → vẫn xếp theo ngành/trường kèm caution, không đối chiếu điểm/tổ hợp; score-fit bonus chỉ áp cho thang 30; policy nhận biết các trạng thái mới.

**Architecture:** Toàn bộ thay đổi nằm trong `reason_candidates` (3 ngả xử lý) và `evaluate_policy_guardrails`. Kênh dữ liệu: candidate NOT_ELIGIBLE đi qua `state.eligibility_checks` (đã có trên AgentState + tracing, trước nay không ai dùng downstream), KHÔNG đi qua `ranked_recommendations` — vì `policy_agent` ghi đè `ranked_recommendations` bằng danh sách lọc.

**Tech Stack:** Python 3.12, pytest (`python -m pytest`, KHÔNG có venv).

**Phụ thuộc:** Plan 1 (cần `THANG_30_METHODS`, `candidate_method_codes`, `method_display`, `StudentProfile.admission_method`).

**Spec:** `docs/superpowers/specs/2026-06-04-phase1-reasoning-integrity-design.md` (WS2)

**Lưu ý commit:** không `git push`; message KHÔNG kèm Co-Authored-By / attribution AI.

---

### Task 1: `reason_candidates` — 3 ngả method/eligibility/scored

**Files:**
- Modify: `services/reasoning_service.py:35-115`
- Test: `tests/agents/test_reasoning_agent.py`

- [ ] **Step 1: Cập nhật fixture cũ + viết test fail**

Trong `tests/agents/test_reasoning_agent.py`:

```python
# 1) test_reasoning_agent_ranks_candidates — StudentProfile thêm:
        admission_method="thpt_score",
#    (giữ nguyên assertion; với method khớp, score = 0.40+0.35+0.15+0.10 = 1.0 → "safe")

# 2) test_uncertain_quota_candidate_is_not_safe_band — StudentProfile thêm:
        admission_method="thpt_score",
#    (score = 0.40 + 0.10 = 0.50 → "match" ≠ "safe"; caution quota giữ nguyên)
```

Append các test mới:

```python
def _candidate(**overrides):
    base = dict(
        candidate_id="hust:2026:computer_science:thpt_score",
        school_id="hust",
        school_name="HUST",
        admission_year=2026,
        program_id="computer_science",
        program_name="Khoa hoc May tinh",
        admission_method="thpt_score",
        subject_combinations=["A00", "A01"],
    )
    base.update(overrides)
    return CandidateProgram(**base)


def test_ec12_wrong_combination_is_not_ranked_and_flagged_not_eligible():
    """EC-12: điểm cao nhưng tổ hợp D01 không được nhận → NOT_ELIGIBLE,
    không xuất hiện trong recommendations, không tính score-fit."""
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=28.0, subject_combination="D01", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    state.retrieved_programs = [_candidate()]

    output = reasoning_agent(state)

    assert output.ranked_recommendations == []          # KHÔNG được xếp hạng
    assert len(output.eligibility_checks) == 1
    check = output.eligibility_checks[0]
    assert check.eligible is False
    assert "D01" in check.risks[0]
    assert "A00" in check.risks[0]                       # nêu rõ tổ hợp được nhận


def test_method_mismatch_still_ranked_with_caution_no_score_fit():
    """Row khác phương thức: vẫn xếp theo ngành/trường, caution rõ ràng,
    KHÔNG check tổ hợp, KHÔNG cộng điểm score-fit."""
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=28.0, subject_combination="D01", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    # Row ĐGNL — tổ hợp D01 không nằm trong list nhưng row này KHÔNG bị NOT_ELIGIBLE
    state.retrieved_programs = [_candidate(
        candidate_id="hust:2026:computer_science:competency",
        admission_method="Đánh giá tư duy (TSA)",
    )]

    output = reasoning_agent(state)

    assert len(output.ranked_recommendations) == 1
    rec = output.ranked_recommendations[0]
    assert rec.score == 0.5                              # 0.35 ngành + 0.15 trường
    assert any("khác phương thức" in c for c in rec.cautions)
    assert output.eligibility_checks[0].eligible is None


def test_score_bonus_not_applied_for_competency_method():
    """EC-13: điểm ĐGNL không so được với heuristic thang 30 → không bonus + caution."""
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=105.0, subject_combination="A00", admission_method="competency_test",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [_candidate(admission_method="competency_test")]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.score == 0.75                             # 0.40 tổ hợp + 0.35 ngành, KHÔNG +0.10
    assert any("chưa thể đối chiếu" in c for c in rec.cautions)


def test_score_bonus_skipped_with_caution_when_method_unknown():
    """EC-13 defense-in-depth: gọi pipeline trực tiếp không có phương thức."""
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=27.0, subject_combination="A00",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [_candidate()]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.score == 0.75                             # không +0.10 vì method unknown
    assert any("chưa rõ phương thức" in c for c in rec.cautions)
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/agents/test_reasoning_agent.py -v`
Expected: FAIL — EC-12 candidate vẫn nằm trong recommendations; chưa có caution mới

- [ ] **Step 3: Implementation — thay toàn bộ thân `reason_candidates`**

```python
# services/reasoning_service.py
from typing import Dict, List, Tuple

from agents.models import CandidateProgram, EligibilityCheck, RankedRecommendation, StudentProfile
from services.explanation_service import _program_label
from services.profile.admission_methods import (
    THANG_30_METHODS,
    candidate_method_codes,
    method_display,
)

# ... _major_matches, _school_matches, _score_to_band giữ nguyên ...


def _max_confidence(candidate: CandidateProgram):
    return max(
        [ev.confidence_score for ev in candidate.evidence if ev.confidence_score is not None]
        or [None]
    )


def reason_candidates(
    profile: StudentProfile, candidates: List[CandidateProgram]
) -> Tuple[List[EligibilityCheck], List[RankedRecommendation]]:
    checks: List[EligibilityCheck] = []
    recommendations: List[RankedRecommendation] = []
    profile_method = getattr(profile, "admission_method", None)

    for candidate in candidates:
        score = 0.0
        reasons: List[str] = []
        risks: List[str] = []
        cautions: List[str] = []
        eligible = True

        codes = candidate_method_codes(candidate)
        method_mismatch = bool(profile_method and codes and profile_method not in codes)

        if method_mismatch:
            # Ngả 1 — khác phương thức: xếp theo ngành/trường, KHÔNG đối chiếu
            # điểm/tổ hợp (tổ hợp của row thuộc phương thức khác).
            eligible = None
            cautions.append(
                f"Chương trình này xét theo {candidate.admission_method}, khác phương thức "
                f"em đã chọn ({method_display(profile_method)}); điểm và tổ hợp chưa được đối chiếu."
            )
        elif profile.subject_combination:
            if (
                not candidate.subject_combinations
                or profile.subject_combination in candidate.subject_combinations
            ):
                score += 0.40
                reasons.append("Tổ hợp xét tuyển phù hợp.")
            else:
                # Ngả 2 — NOT_ELIGIBLE (EC-12): ghi check, KHÔNG xếp hạng,
                # KHÔNG tính tiếp score-fit.
                combos = ", ".join(candidate.subject_combinations)
                checks.append(
                    EligibilityCheck(
                        candidate_id=candidate.candidate_id,
                        eligible=False,
                        risks=[
                            f"Chương trình không nhận tổ hợp {profile.subject_combination} "
                            f"theo phương thức đã chọn — các tổ hợp được công bố: {combos}."
                        ],
                        confidence=_max_confidence(candidate),
                    )
                )
                continue
        else:
            eligible = None
            risks.append("Hồ sơ còn thiếu tổ hợp xét tuyển.")

        # Ngả 3 — chấm điểm như cũ, nhưng score-fit bonus chỉ cho thang 30.
        if _major_matches(profile, candidate):
            score += 0.35
            reasons.append("Ngành ưu tiên khớp với chương trình.")

        if _school_matches(profile, candidate):
            score += 0.15
            reasons.append("Trường ưu tiên khớp với nguyện vọng.")

        if profile.total_score is not None:
            if method_mismatch:
                pass  # đã caution ở ngả 1; không đối chiếu điểm
            elif profile_method in THANG_30_METHODS:
                if profile.total_score >= 26:
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

        has_missing_critical = bool(profile.missing_slots)
        band = _score_to_band(score, has_missing_critical)
        if "quota" in candidate.data_uncertain_fields:
            if band == "safe":
                band = "match"
            cautions.append("Dữ liệu hạn ngạch chưa được xác minh giữa các nguồn.")
        summary = f"{_program_label(candidate)} tại {candidate.school_name}: mức phù hợp {band}."

        checks.append(
            EligibilityCheck(
                candidate_id=candidate.candidate_id,
                eligible=eligible,
                reasons=reasons,
                risks=risks,
                confidence=_max_confidence(candidate),
            )
        )
        recommendations.append(
            RankedRecommendation(
                candidate_id=candidate.candidate_id,
                band=band,
                score=round(score, 3),
                summary=summary,
                reasons=reasons,
                cautions=risks + cautions,
            )
        )

    order = {"safe": 0, "match": 1, "reach": 2, "unknown": 3}
    recommendations.sort(key=lambda rec: (order.get(rec.band, 99), -rec.score))
    return checks, recommendations
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/agents/test_reasoning_agent.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add services/reasoning_service.py tests/agents/test_reasoning_agent.py
git commit -m "feat: exclude wrong-combination programs from ranking and gate score fit by method"
```

---

### Task 2: Policy — critical slot, blocked claim, flag mới

**Files:**
- Modify: `services/policy_service.py:11, 26-50`
- Test: `tests/agents/test_policy_agent.py`

- [ ] **Step 1: Viết test fail (append vào test_policy_agent.py)**

```python
def test_policy_blocks_score_fit_claim_when_method_missing():
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile(total_score=27.0)  # không có admission_method

    output = policy_agent(state)

    assert "no_score_fit_without_method" in output.policy_decision.blocked_claims


def test_policy_flags_no_eligible_recommendations():
    """Có candidates nhưng reasoning loại hết (vd toàn sai tổ hợp) → flag riêng,
    phân biệt với empty_retrieval."""
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile(
        total_score=28.0, subject_combination="D01", admission_method="thpt_score",
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="hust:1", school_id="hust", school_name="HUST",
            admission_year=2026, program_id="computer_science",
            program_name="Khoa hoc May tinh",
            evidence=[Evidence(source_url="https://example.com", school_name="HUST",
                               admission_year=2026, field_name="record")],
        )
    ]
    state.ranked_recommendations = []  # reasoning đã loại hết

    output = policy_agent(state)

    assert "no_eligible_recommendations" in output.policy_decision.policy_flags
    assert "empty_retrieval" not in output.policy_decision.policy_flags


def test_policy_treats_admission_method_as_critical_slot():
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile(missing_slots=["admission_method"])

    output = policy_agent(state)

    assert output.policy_decision.requires_follow_up is True
    assert "missing_critical_profile" in output.policy_decision.policy_flags
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/agents/test_policy_agent.py -v`
Expected: FAIL — thiếu claim/flag mới; admission_method chưa critical

- [ ] **Step 3: Implementation (policy_service.py)**

```python
# Dòng 11 — THAY:
CRITICAL_PROFILE_SLOTS = {"total_score", "subject_combination", "preferred_majors", "admission_method"}

# Trong evaluate_policy_guardrails, sau khối `if profile.total_score is None:` thêm:
    if getattr(profile, "admission_method", None) is None:
        blocked_claims.append("no_score_fit_without_method")

# Sau khối `if not candidates:` (empty_retrieval) thêm:
    if candidates and not recommendations:
        policy_flags.append("no_eligible_recommendations")
        warnings.append(
            "Các chương trình tìm thấy hiện không đáp ứng điều kiện xét tuyển trong hồ sơ "
            "(ví dụ tổ hợp); xem chi tiết trong phần giải thích."
        )
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/agents/test_policy_agent.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Chạy toàn bộ suite**

Run: `python -m pytest -q`
Expected: PASS (0 failed). Đặc biệt kiểm tra `tests/e2e/test_advisory_flow.py::test_advisory_flow_returns_policy_checked_answer` vẫn pass (profile mock đã có `admission_method="thpt_score"` từ Plan 1 nên không có caution/claim drift).

- [ ] **Step 6: Commit**

```bash
git add services/policy_service.py tests/agents/test_policy_agent.py
git commit -m "feat: policy guardrails for admission method and ineligible-only retrievals"
```
