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
    assert "Gợi ý chương trình phù hợp" in output.final_answer
    assert "Nguồn tham chiếu" in output.final_answer
    assert "https://example.com/hust" in output.final_answer
    assert "Cảnh báo" in output.final_answer
    assert "Lý do:" in output.final_answer


def test_explanation_agent_adds_follow_up_prompt():
    state = AgentState(user_query="Tu van")
    state.student_profile = StudentProfile(missing_slots=["total_score", "subject_combination"])
    state.policy_decision = PolicyDecision(requires_follow_up=True)

    output = explanation_agent(state)

    assert "Thông tin cần bổ sung:" in output.final_answer


def test_explanation_includes_data_verification_section_for_resolved_outcome():
    option = EvidenceOption(
        evidence_id="mock://vnu/proposal-pdf|quota",
        source_url="mock://vnu/proposal-pdf",
        trust_level=3,
        value=150,
    )
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

    output = explanation_agent(state)

    assert "Xác minh dữ liệu" in output.final_answer
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

    assert output.final_answer.count("Cong nghe thong tin - Dai hoc Cong nghe - DHQGHN") == 1
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

    assert "Hồ sơ hiện tại" in output.final_answer
    assert "- Điểm: 26.5" in output.final_answer
    assert "Gợi ý chương trình phù hợp" in output.final_answer
    assert "Mức phù hợp: an toàn" in output.final_answer
    assert "Lý do:" in output.final_answer
    assert "- Tổ hợp xét tuyển phù hợp." in output.final_answer
    assert "Lưu ý:" in output.final_answer
    assert "Nguồn tham chiếu" in output.final_answer
