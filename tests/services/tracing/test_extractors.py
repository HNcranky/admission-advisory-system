from agents.models import (
    CandidateProgram,
    EligibilityCheck,
    Evidence,
    PolicyDecision,
    RankedRecommendation,
    StudentProfile,
)
from services.conflict.models import ResolutionOutcome
from services.tracing.extractors import (
    extract_candidates,
    extract_conflicts,
    extract_explanation,
    extract_policy,
    extract_profile,
    extract_reasoning,
)
from state import AgentState


def _make_candidate(school_id: str, program_name: str) -> CandidateProgram:
    return CandidateProgram(
        candidate_id=f"{school_id}:{program_name}",
        school_id=school_id,
        school_name=school_id.upper(),
        admission_year=2026,
        program_name=program_name,
    )


def test_extract_profile_returns_dumped_student_profile():
    profile = StudentProfile(total_score=27.0, preferred_majors=["cntt"])
    state_after = AgentState(user_query="hi", student_profile=profile)
    state_before = AgentState(user_query="hi")

    result = extract_profile(state_after, state_before)

    assert isinstance(result, dict)
    assert "student_profile" in result
    assert result["student_profile"]["total_score"] == 27.0
    assert result["student_profile"]["preferred_majors"] == ["cntt"]


def test_extract_candidates_includes_count_and_list():
    candidates = [
        _make_candidate("vnu_uet", "CNTT"),
        _make_candidate("hust", "KHMT"),
    ]
    state = AgentState(user_query="hi", retrieved_programs=candidates)

    result = extract_candidates(state, state)

    assert result["count"] == 2
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["program_name"] == "CNTT"


def test_extract_conflicts_returns_resolution_outcomes():
    state = AgentState(
        user_query="hi",
        resolution_outcomes=[
            ResolutionOutcome(
                conflict_key="quota:cs:hust",
                field_name="quota",
                school_id="hust",
                school_name="HUST",
                program_name="CS",
                status="resolved",
                resolved_value="120",
                rationale="latest source",
                uncertainty_reason=None,
            ),
        ],
    )

    result = extract_conflicts(state, state)

    assert len(result["resolution_outcomes"]) == 1
    assert result["resolution_outcomes"][0]["conflict_key"] == "quota:cs:hust"


def test_extract_reasoning_returns_eligibility_and_ranked():
    state = AgentState(
        user_query="hi",
        eligibility_checks=[EligibilityCheck(candidate_id="x", eligible=True, risks=[], confidence=0.9)],
        ranked_recommendations=[RankedRecommendation(candidate_id="x", band="match", score=0.8, summary="ok")],
    )

    result = extract_reasoning(state, state)

    assert len(result["eligibility_checks"]) == 1
    assert len(result["ranked_recommendations"]) == 1


def test_extract_policy_returns_decision_and_recommendations():
    state = AgentState(
        user_query="hi",
        policy_decision=PolicyDecision(allow_answer=True, blocked_claims=[], warnings=[], policy_flags=[]),
        ranked_recommendations=[RankedRecommendation(candidate_id="y", band="reach", score=0.4, summary="risky")],
    )

    result = extract_policy(state, state)

    assert result["policy_decision"]["allow_answer"] is True
    assert len(result["filtered_recommendations"]) == 1


def test_extract_explanation_returns_final_answer_and_evidence():
    state = AgentState(
        user_query="hi",
        final_answer="Here is your recommendation.",
        citations=[
            Evidence(
                source_url="https://x",
                school_name="UET",
                admission_year=2026,
                field_name="quota",
                normalized_value="120",
                confidence_score=0.9,
            )
        ],
    )

    result = extract_explanation(state, state)

    assert result["final_answer"] == "Here is your recommendation."
    assert len(result["evidence"]) == 1
