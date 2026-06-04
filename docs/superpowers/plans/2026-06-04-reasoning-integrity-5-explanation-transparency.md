# Plan 5/5 — Explanation minh bạch (EC-12 hiển thị, EC-24)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Câu trả lời cuối hiển thị section "Không đủ điều kiện xét tuyển" (từ `eligibility_checks`, cap 3, kèm lý do tổ hợp); khi 0 đề xuất → liệt kê đúng tiêu chí đang áp và gợi ý nới minh bạch (không bịa, không tự nới); intro nêu phương thức; correction message có nhãn cho phương thức.

**Architecture:** `build_explanation` nhận thêm `eligibility_checks` (kênh NOT_ELIGIBLE — vì `policy_agent` ghi đè `ranked_recommendations`, recommendations không còn chứa các chương trình này). Toàn bộ render là template deterministic, không LLM.

**Tech Stack:** Python 3.12, pytest (`python -m pytest`, KHÔNG có venv).

**Phụ thuộc:** Plan 1 (`method_display`), Plan 3 (reasoning ghi `eligible=False` + policy flag `no_eligible_recommendations`).

**Spec:** `docs/superpowers/specs/2026-06-04-phase1-reasoning-integrity-design.md` (WS4)

**Lưu ý commit:** không `git push`; message KHÔNG kèm Co-Authored-By / attribution AI.

---

### Task 1: Section "Không đủ điều kiện xét tuyển" + truyền `eligibility_checks`

**Files:**
- Modify: `services/explanation_service.py` (signature, section mới, labels, import)
- Modify: `agents/explanation_agent.py:5-14`
- Test: `tests/agents/test_explanation_agent.py`

- [ ] **Step 1: Viết test fail (append vào test_explanation_agent.py)**

```python
from agents.models import EligibilityCheck


def test_explanation_renders_not_eligible_section_with_reason():
    """EC-12: chương trình sai tổ hợp xuất hiện ở section riêng kèm lý do,
    KHÔNG nằm trong danh sách đề xuất đánh số."""
    state = AgentState(user_query="Tu van", admission_year=2026)
    state.student_profile = StudentProfile(
        total_score=28.0, subject_combination="D01", admission_method="thpt_score",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="uet:ne", school_id="vnu_uet",
            school_name="Đại học Công nghệ - ĐHQGHN",
            admission_year=2026, program_id="computer_science",
            program_name="Khoa học máy tính", admission_method="thpt_score",
            subject_combinations=["A00", "A01"],
        ),
        CandidateProgram(
            candidate_id="hust:ok", school_id="hust", school_name="HUST",
            admission_year=2026, program_id="data_science",
            program_name="Khoa học dữ liệu", admission_method="thpt_score",
            subject_combinations=["A00", "A01", "D01"],
        ),
    ]
    state.eligibility_checks = [
        EligibilityCheck(
            candidate_id="uet:ne", eligible=False,
            risks=["Chương trình không nhận tổ hợp D01 theo phương thức đã chọn — các tổ hợp được công bố: A00, A01."],
        ),
        EligibilityCheck(candidate_id="hust:ok", eligible=True),
    ]
    state.ranked_recommendations = [
        RankedRecommendation(candidate_id="hust:ok", band="match", score=0.75, summary="fit"),
    ]

    output = explanation_agent(state)

    assert "**Không đủ điều kiện xét tuyển**" in output.final_answer
    assert "không nhận tổ hợp D01" in output.final_answer
    # Chương trình NOT_ELIGIBLE không được nằm trong danh sách đề xuất đánh số
    assert "### 1. HUST — Khoa học dữ liệu" in output.final_answer
    assert "### 2." not in output.final_answer
    assert output.final_answer.index("### 1.") < output.final_answer.index("Không đủ điều kiện")


def test_explanation_no_not_eligible_section_when_all_eligible():
    state = AgentState(user_query="Tu van")
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="hust:1", school_id="hust", school_name="HUST",
            admission_year=2026, program_id="computer_science",
            program_name="Khoa hoc May tinh", admission_method="thpt_score",
        )
    ]
    state.eligibility_checks = [EligibilityCheck(candidate_id="hust:1", eligible=True)]
    state.ranked_recommendations = [
        RankedRecommendation(candidate_id="hust:1", band="match", score=0.6, summary="fit"),
    ]

    output = explanation_agent(state)

    assert "Không đủ điều kiện" not in output.final_answer


def test_intro_paragraph_mentions_admission_method():
    state = AgentState(user_query="Tu van", admission_year=2026)
    state.student_profile = StudentProfile(
        total_score=27.0, admission_method="thpt_score", subject_combination="A00",
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="hust:1", school_id="hust", school_name="HUST",
            admission_year=2026, program_id="computer_science",
            program_name="Khoa hoc May tinh", admission_method="thpt_score",
        )
    ]
    state.ranked_recommendations = [
        RankedRecommendation(candidate_id="hust:1", band="match", score=0.6, summary="fit"),
    ]

    output = explanation_agent(state)

    assert "phương thức điểm thi tốt nghiệp THPT" in output.final_answer


def test_correction_sentence_labels_admission_method():
    from services.explanation_service import _correction_sentence
    sentence = _correction_sentence(
        {"slot": "admission_method", "previous_value": "thpt_score", "new_value": "school_record"}
    )
    assert "phương thức xét tuyển" in sentence
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/agents/test_explanation_agent.py -v`
Expected: FAIL — chưa có section/label/method trong intro

- [ ] **Step 3: Implementation**

`services/explanation_service.py`:

```python
# Import: bổ sung EligibilityCheck + method_display
from agents.models import (
    CandidateProgram, EligibilityCheck, PolicyDecision, RankedRecommendation, StudentProfile,
)
from services.profile.admission_methods import method_display

# _SLOT_LABELS: thêm
    "admission_method": "phương thức xét tuyển",

# _intro_paragraph: sau khối `if admission_year:` thêm
    if getattr(profile, "admission_method", None):
        facts.append(f"phương thức {method_display(profile.admission_method)}")

# Helper mới (đặt sau _data_note):
def _not_eligible_lines(
    eligibility_checks: List[EligibilityCheck],
    candidates_by_id: Dict[str, List[CandidateProgram]],
) -> List[str]:
    """Section 'Không đủ điều kiện xét tuyển' (EC-12): cap 3, dedupe theo chương trình."""
    lines: List[str] = []
    seen = set()
    for check in eligibility_checks or []:
        if check.eligible is not False:
            continue
        group = candidates_by_id.get(check.candidate_id, [])
        if not group:
            continue
        candidate = group[0]
        key = (candidate.school_id, candidate.program_id or candidate.program_name)
        if key in seen:
            continue
        seen.add(key)
        reason = check.risks[0] if check.risks else "Không đáp ứng điều kiện xét tuyển đã công bố."
        lines.append(f"- {candidate.school_name} — {_program_label(candidate)}: {reason}")
        if len(lines) >= 3:
            break
    return lines

# build_explanation: thêm tham số cuối
def build_explanation(
    profile: StudentProfile,
    recommendations: List[RankedRecommendation],
    candidates: List[CandidateProgram],
    policy: Optional[PolicyDecision],
    resolution_outcomes: Optional[List[ResolutionOutcome]] = None,
    admission_year: Optional[int] = None,
    correction_note: Optional[Dict[str, Any]] = None,
    eligibility_checks: Optional[List[EligibilityCheck]] = None,
) -> str:

# build_explanation: NGAY SAU vòng `for idx, (recommendation, candidate) in enumerate(...)`
# (vẫn trong nhánh `if renderable:`) — và CŨNG chạy ở nhánh else (xem Task 2) —
# chèn section. Đặt đoạn sau ngay trước khối "Nguồn tham chiếu":
    ne_lines = _not_eligible_lines(eligibility_checks or [], candidates_by_id)
    if ne_lines:
        lines.append("")
        lines.append("**Không đủ điều kiện xét tuyển**")
        lines.append("")
        lines.extend(ne_lines)
```

`agents/explanation_agent.py` — thêm vào lời gọi `build_explanation`:

```python
        eligibility_checks=state.eligibility_checks,
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `python -m pytest tests/agents/test_explanation_agent.py -v`
Expected: PASS toàn bộ (test cũ giữ nguyên — tham số mới có default None)

- [ ] **Step 5: Commit**

```bash
git add services/explanation_service.py agents/explanation_agent.py tests/agents/test_explanation_agent.py
git commit -m "feat: surface not-eligible programs with reasons in final answer (EC-12)"
```

---

### Task 2: No-match minh bạch theo tiêu chí thật (EC-24)

**Files:**
- Modify: `services/explanation_service.py` (thay nhánh else "Chưa có đề xuất phù hợp")
- Test: `tests/agents/test_explanation_agent.py`
- Modify: `tests/e2e/test_advisory_flow.py:189` (assertion message mới)

- [ ] **Step 1: Viết test fail (append vào test_explanation_agent.py)**

```python
def test_no_match_lists_active_criteria_and_suggestions():
    """EC-24: 0 đề xuất → liệt kê đúng tiêu chí đang áp + gợi ý nới minh bạch."""
    state = AgentState(user_query="Tu van", admission_year=2026)
    state.student_profile = StudentProfile(
        total_score=23.0, subject_combination="A01", admission_method="thpt_score",
        preferred_majors=["artificial_intelligence"],
        location_preference="Ha Noi", tuition_budget="duoi 20 trieu",
    )
    state.retrieved_programs = []
    state.ranked_recommendations = []
    state.policy_decision = PolicyDecision(policy_flags=["empty_retrieval"])

    output = explanation_agent(state)

    answer = output.final_answer
    assert "chưa tìm thấy chương trình đáp ứng đồng thời" in answer
    assert "năm 2026" in answer
    assert "phương thức điểm thi tốt nghiệp THPT" in answer
    assert "tổ hợp A01" in answer
    assert "artificial_intelligence" in answer
    assert "Ha Noi" in answer
    assert "duoi 20 trieu" in answer
    # Gợi ý nới CHỈ những tiêu chí đang set, nói rõ không tự nới
    assert "ngành gần" in answer
    assert "khu vực" in answer
    assert "ngân sách" in answer
    assert "không tự nới" in answer
    # Không có câu hỏi chốt khi không có đề xuất
    assert "Em có muốn ưu tiên theo tiêu chí nào hơn" not in answer


def test_no_match_all_not_eligible_explains_combination_cause():
    """EC-24 + EC-12: mọi chương trình bị loại vì tổ hợp → nói thẳng nguyên nhân."""
    state = AgentState(user_query="Tu van", admission_year=2026)
    state.student_profile = StudentProfile(
        total_score=28.0, subject_combination="D01", admission_method="thpt_score",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="uet:ne", school_id="vnu_uet",
            school_name="Đại học Công nghệ - ĐHQGHN",
            admission_year=2026, program_id="computer_science",
            program_name="Khoa học máy tính", admission_method="thpt_score",
            subject_combinations=["A00", "A01"],
        ),
    ]
    state.eligibility_checks = [
        EligibilityCheck(
            candidate_id="uet:ne", eligible=False,
            risks=["Chương trình không nhận tổ hợp D01 theo phương thức đã chọn — các tổ hợp được công bố: A00, A01."],
        ),
    ]
    state.ranked_recommendations = []
    state.policy_decision = PolicyDecision(policy_flags=["no_eligible_recommendations"])

    output = explanation_agent(state)

    answer = output.final_answer
    assert "không nhận tổ hợp D01" in answer               # section NOT_ELIGIBLE vẫn render
    assert "cân nhắc tổ hợp khác hoặc ngành gần" in answer  # gợi ý đúng nguyên nhân


def test_no_match_without_any_criteria_falls_back_generic():
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile()
    state.ranked_recommendations = []

    output = explanation_agent(state)

    assert "chưa tìm thấy chương trình phù hợp trong dữ liệu hiện có" in output.final_answer
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/agents/test_explanation_agent.py -v`
Expected: FAIL — vẫn trả "Chưa có đề xuất phù hợp từ dữ liệu hiện tại."

- [ ] **Step 3: Implementation (explanation_service.py)**

Helper mới (đặt cạnh `_intro_paragraph`):

```python
def _profile_criteria(profile: StudentProfile, admission_year: Optional[int]) -> List[str]:
    facts: List[str] = []
    if admission_year:
        facts.append(f"năm {admission_year}")
    if getattr(profile, "admission_method", None):
        facts.append(f"phương thức {method_display(profile.admission_method)}")
    if profile.total_score is not None:
        facts.append(f"mức điểm {_fmt_num(profile.total_score)}")
    if profile.subject_combination:
        facts.append(f"tổ hợp {profile.subject_combination}")
    if profile.preferred_majors:
        facts.append("ngành " + ", ".join(profile.preferred_majors[:3]))
    if profile.location_preference:
        facts.append(f"khu vực {profile.location_preference}")
    if profile.tuition_budget:
        facts.append(f"ngân sách {profile.tuition_budget}")
    return facts


def _no_match_block(
    profile: StudentProfile,
    admission_year: Optional[int],
    eligibility_checks: List[EligibilityCheck],
) -> List[str]:
    """EC-24: nói rõ tiêu chí đang áp, nguyên nhân (nếu biết) và gợi ý nới minh bạch.
    KHÔNG bịa chương trình; KHÔNG tự nới tiêu chí."""
    facts = _profile_criteria(profile, admission_year)
    lines: List[str] = []
    if facts:
        lines.append(
            "Mình chưa tìm thấy chương trình đáp ứng đồng thời: "
            + "; ".join(facts) + " — trong dữ liệu hiện có."
        )
    else:
        lines.append("Mình chưa tìm thấy chương trình phù hợp trong dữ liệu hiện có.")

    not_eligible = [c for c in eligibility_checks if c.eligible is False]
    if not_eligible and profile.subject_combination:
        majors = ", ".join(profile.preferred_majors[:3]) or "em quan tâm"
        lines.append("")
        lines.append(
            f"Các chương trình ngành {majors} trong dữ liệu hiện không nhận tổ hợp "
            f"{profile.subject_combination}; em có thể cân nhắc tổ hợp khác hoặc ngành gần."
        )
        return lines

    suggestions: List[str] = []
    if profile.preferred_majors:
        suggestions.append("mở rộng sang ngành gần")
    if profile.location_preference:
        suggestions.append("nới khu vực học")
    if profile.tuition_budget:
        suggestions.append("điều chỉnh ngân sách")
    if suggestions:
        lines.append("")
        lines.append(
            "Em có thể cân nhắc: " + "; ".join(suggestions)
            + ". Mình sẽ không tự nới tiêu chí khi chưa có xác nhận của em."
        )
    return lines
```

Trong `build_explanation`, THAY nhánh else:

```python
    else:
        lines.extend(_no_match_block(profile, admission_year, eligibility_checks or []))
```

(Section "Không đủ điều kiện" của Task 1 đặt NGOÀI `if renderable:` — sau cả hai nhánh — nên ở ca all-not-eligible nó vẫn render. Kiểm tra vị trí: `ne_lines` chèn sau if/else, trước "Nguồn tham chiếu".)

- [ ] **Step 4: Cập nhật e2e assertion**

`tests/e2e/test_advisory_flow.py` — trong `test_advisory_flow_handles_empty_retrieval`, THAY:

```python
    assert "Chưa có đề xuất phù hợp" in result["final_answer"]
```

bằng:

```python
    assert "chưa tìm thấy chương trình đáp ứng đồng thời" in result["final_answer"]
    assert "tổ hợp A00" in result["final_answer"]
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `python -m pytest tests/agents/test_explanation_agent.py tests/e2e/test_advisory_flow.py -v`
Expected: PASS toàn bộ

- [ ] **Step 6: Chạy toàn bộ suite**

Run: `python -m pytest -q`
Expected: PASS (0 failed). Nếu có test nào khác assert chuỗi "Chưa có đề xuất phù hợp", cập nhật sang chuỗi mới "chưa tìm thấy chương trình" (grep: `python -m pytest` sẽ chỉ ra; chuỗi cũ chỉ còn ở `tests/e2e/test_chat_session_run_flow.py` nếu có — sửa tương tự).

- [ ] **Step 7: Commit**

```bash
git add services/explanation_service.py tests/agents/test_explanation_agent.py tests/e2e/test_advisory_flow.py
git commit -m "feat: transparent no-match explanation listing active criteria (EC-24)"
```
