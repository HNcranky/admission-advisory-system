from agents.models import CandidateProgram, Evidence, RankedRecommendation, StudentProfile
from agents.policy_agent import policy_agent
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
