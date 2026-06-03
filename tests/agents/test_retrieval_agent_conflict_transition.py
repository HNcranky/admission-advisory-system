from agents.models import CandidateProgram, StudentProfile
from agents.retrieval_agent import retrieval_agent
from state import AgentState


def test_retrieval_agent_no_longer_populates_legacy_conflicts(monkeypatch):
    candidate_a = CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        quota={"value": 120},
    )
    candidate_b = candidate_a.model_copy(update={"quota": {"value": 150}})

    monkeypatch.setattr(
        "agents.retrieval_agent.fetch_candidates",
        lambda filters: [candidate_a, candidate_b],
    )

    state = AgentState(user_query="Tu van", student_profile=StudentProfile())
    output = retrieval_agent(state)

    assert output.retrieved_programs == [candidate_a, candidate_b]
    assert output.conflicts == []
