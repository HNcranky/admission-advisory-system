from domain.models import (
    CandidateProgram,
    CutoffAssessment,
    Evidence,
    RankedRecommendation,
    StudentProfile,
)
from agents.policy_agent import policy_agent
from services.policy_service import evaluate_policy_guardrails
from state import AgentState


def test_policy_agent_filters_recommendations_without_evidence():
    state = AgentState(user_query="Em muon biet chac do khong")
    state.student_profile = StudentProfile(
        total_score=27,
        subject_combination="A00",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="good",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            evidence=[
                Evidence(
                    source_url="https://example.com",
                    school_name="HUST",
                    admission_year=2026,
                    field_name="record",
                )
            ],
        ),
        CandidateProgram(
            candidate_id="bad",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="software_engineering",
            program_name="Ky thuat phan mem",
            evidence=[],
        ),
    ]
    state.ranked_recommendations = [
        RankedRecommendation(candidate_id="good", band="match", score=0.7, summary="ok"),
        RankedRecommendation(candidate_id="bad", band="match", score=0.7, summary="bad"),
    ]

    output = policy_agent(state)

    assert len(output.ranked_recommendations) == 1
    assert output.ranked_recommendations[0].candidate_id == "good"
    assert "no_guaranteed_admission_claim" in output.policy_decision.blocked_claims


def test_policy_agent_requires_follow_up_when_critical_slots_missing():
    state = AgentState(user_query="Tu van giup em")
    state.student_profile = StudentProfile(
        missing_slots=["total_score", "subject_combination", "preferred_majors"]
    )

    output = policy_agent(state)

    assert output.policy_decision.requires_follow_up is True
    assert "missing_critical_profile" in output.policy_decision.policy_flags


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
