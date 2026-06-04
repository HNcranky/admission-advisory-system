from agents.explanation_agent import explanation_agent
from agents.models import (
    CandidateProgram,
    Evidence,
    PolicyDecision,
    RankedRecommendation,
    StudentProfile,
)
from services.conflict.models import EvidenceOption, ResolutionOutcome
from state import AgentState


def test_explanation_agent_builds_final_answer_with_sources():
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile(
        total_score=27,
        subject_combination="A00",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="hust:1",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            admission_method="thpt_score",
            evidence=[
                Evidence(
                    source_url="https://example.com/hust",
                    school_name="HUST",
                    admission_year=2026,
                    field_name="record",
                )
            ],
        )
    ]
    state.ranked_recommendations = [
        RankedRecommendation(
            candidate_id="hust:1",
            band="safe",
            score=0.91,
            summary="fit",
            reasons=["Preferred major matches candidate program."],
            cautions=["Check official cutoff updates."],
        )
    ]
    state.policy_decision = PolicyDecision(
        warnings=["Conflicting records detected; verify official source before applying."],
        requires_follow_up=False,
    )

    output = explanation_agent(state)

    assert output.final_answer is not None
    assert "### 1. HUST — Khoa hoc May tinh" in output.final_answer
    assert "**Mức phù hợp: Cao / An toàn**" in output.final_answer
    assert "Ngành ưu tiên khớp với chương trình." in output.final_answer
    assert "**Nguồn tham chiếu**" in output.final_answer
    assert "https://example.com/hust" in output.final_answer
    assert "**Cảnh báo**" in output.final_answer
    # Điểm nội bộ (band score) KHÔNG được lộ ra cho người dùng.
    assert "0.91" not in output.final_answer
    assert "Điểm phù hợp" not in output.final_answer


def test_explanation_agent_adds_follow_up_prompt():
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile(missing_slots=["total_score", "subject_combination"])
    state.policy_decision = PolicyDecision(requires_follow_up=True)

    output = explanation_agent(state)

    assert "Thông tin cần bổ sung:" in output.final_answer


def test_explanation_includes_per_program_data_note_for_resolved_outcome():
    option = EvidenceOption(
        evidence_id="mock://vnu/proposal-pdf|quota",
        source_url="mock://vnu/proposal-pdf",
        trust_level=3,
        value=150,
    )
    # Per-program data note (AC6) chỉ render khi chương trình đó được đề xuất:
    # cần một candidate + recommendation khớp conflict_key.
    state = AgentState(
        user_query="Tu van",
        resolution_outcomes=[
            ResolutionOutcome(
                conflict_key="vnu_uet:2026:cntt:thpt_score",
                field_name="quota",
                school_id="vnu_uet",
                school_name="Dai hoc Cong nghe - DHQGHN",
                program_name="Cong nghe thong tin",
                status="resolved",
                resolved_value=150,
                chosen_evidence=option,
                rationale="Resolved by deterministic comparison.",
                decision_axes=["trust_level"],
            )
        ],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="vnu_uet:2026:cntt:thpt_score",
            school_id="vnu_uet",
            school_name="Dai hoc Cong nghe - DHQGHN",
            admission_year=2026,
            program_id="cntt",
            program_name="Cong nghe thong tin",
            admission_method="thpt_score",
            evidence=[
                Evidence(
                    source_url="mock://vnu/proposal-pdf",
                    school_name="Dai hoc Cong nghe - DHQGHN",
                    admission_year=2026,
                    field_name="quota",
                )
            ],
        )
    ]
    state.ranked_recommendations = [
        RankedRecommendation(
            candidate_id="vnu_uet:2026:cntt:thpt_score",
            band="match",
            score=0.6,
            summary="fit",
        )
    ]

    output = explanation_agent(state)

    assert "**Lưu ý dữ liệu:**" in output.final_answer
    assert "Cong nghe thong tin" in output.final_answer
    assert "150" in output.final_answer
    assert "Nguồn mock: VNU proposal PDF" in output.final_answer


def test_explanation_deduplicates_same_program_recommendations_and_keeps_all_sources():
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile(
        total_score=26.5,
        subject_combination="A00",
        preferred_majors=["cntt"],
        preferred_schools=["vnu_uet"],
    )
    duplicate_id = "vnu_uet:2026:cntt:thpt_score"
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id=duplicate_id,
            school_id="vnu_uet",
            school_name="Dai hoc Cong nghe - DHQGHN",
            admission_year=2026,
            program_id="cntt",
            program_name="Cong nghe thong tin",
            admission_method="thpt_score",
            evidence=[
                Evidence(
                    source_url="mock://uet/program-page",
                    school_name="Dai hoc Cong nghe - DHQGHN",
                    admission_year=2026,
                    field_name="quota",
                )
            ],
        ),
        CandidateProgram(
            candidate_id=duplicate_id,
            school_id="vnu_uet",
            school_name="Dai hoc Cong nghe - DHQGHN",
            admission_year=2026,
            program_id="cntt",
            program_name="Cong nghe thong tin",
            admission_method="thpt_score",
            evidence=[
                Evidence(
                    source_url="mock://vnu/proposal-pdf",
                    school_name="Dai hoc Cong nghe - DHQGHN",
                    admission_year=2026,
                    field_name="quota",
                )
            ],
        ),
    ]
    state.ranked_recommendations = [
        RankedRecommendation(
            candidate_id=duplicate_id,
            band="safe",
            score=1.0,
            summary="fit",
            reasons=["Preferred major matches candidate program."],
        ),
        RankedRecommendation(
            candidate_id=duplicate_id,
            band="safe",
            score=1.0,
            summary="fit",
            reasons=["Preferred major matches candidate program."],
        ),
    ]

    output = explanation_agent(state)

    assert output.final_answer.count("### 1. Dai hoc Cong nghe - DHQGHN — Cong nghe thong tin") == 1
    assert "mock://uet/program-page" in output.final_answer
    assert "mock://vnu/proposal-pdf" in output.final_answer


def test_explanation_uses_vietnamese_accents_and_readable_sections():
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile(
        total_score=26.5,
        subject_combination="A00",
        preferred_majors=["cntt"],
        preferred_schools=["vnu_uet"],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="vnu_uet:2026:cntt:thpt_score",
            school_id="vnu_uet",
            school_name="Đại học Công nghệ - ĐHQGHN",
            admission_year=2026,
            program_id="cntt",
            program_name="Công nghệ thông tin",
            admission_method="thpt_score",
            subject_combinations=["A00"],
            evidence=[
                Evidence(
                    source_url="mock://uet/program-page",
                    school_name="Đại học Công nghệ - ĐHQGHN",
                    admission_year=2026,
                    field_name="quota",
                )
            ],
        )
    ]
    state.ranked_recommendations = [
        RankedRecommendation(
            candidate_id="vnu_uet:2026:cntt:thpt_score",
            band="safe",
            score=1.0,
            summary="fit",
            reasons=[
                "Tổ hợp xét tuyển phù hợp.",
                "Ngành ưu tiên khớp với chương trình.",
            ],
            cautions=["Dữ liệu hạn ngạch chưa được xác minh giữa các nguồn."],
        )
    ]

    output = explanation_agent(state)

    assert "dự kiến 26.5 điểm" in output.final_answer
    assert "### 1. Đại học Công nghệ - ĐHQGHN — Công nghệ thông tin" in output.final_answer
    assert "**Mức phù hợp: Cao / An toàn**" in output.final_answer
    assert "- Tổ hợp xét tuyển phù hợp." in output.final_answer
    assert "**Nguồn tham chiếu**" in output.final_answer
    # Câu hỏi chốt mời ưu tiên tiêu chí (happy-path Turn 6).
    assert "Em có muốn ưu tiên theo tiêu chí nào hơn" in output.final_answer


def test_explanation_prepends_correction_sentence_when_correction_note_present():
    state = AgentState(user_query="Tu van", admission_year=2026)
    state.correction_note = {"slot": "total_score", "previous_value": 27.0, "new_value": 25.75}
    state.student_profile = StudentProfile(
        total_score=25.75, subject_combination="A01", preferred_majors=["computer_science"]
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="hust:1",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            admission_method="thpt_score",
        )
    ]
    state.ranked_recommendations = [
        RankedRecommendation(candidate_id="hust:1", band="match", score=0.6, summary="fit")
    ]

    output = explanation_agent(state)

    assert output.final_answer.startswith("Mình đã cập nhật điểm dự kiến")
    assert "27" in output.final_answer
    assert "25.75" in output.final_answer
    assert "thứ tự ưu tiên thay đổi" in output.final_answer


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
    # Qua agent thì admission_year luôn có default (state.py:25) nên test fallback
    # generic ở mức service: không có bất kỳ tiêu chí nào → câu generic.
    from services.explanation_service import build_explanation

    answer = build_explanation(
        profile=StudentProfile(), recommendations=[], candidates=[], policy=None,
    )

    assert "chưa tìm thấy chương trình phù hợp trong dữ liệu hiện có" in answer
