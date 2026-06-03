import pytest
from langgraph.graph import StateGraph

from agents.models import (
    CandidateProgram,
    EligibilityCheck,
    PolicyDecision,
    RankedRecommendation,
    StudentProfile,
)
from services.chat.db import get_db_connection
from services.tracing.agent_tracer import traced
from services.tracing.extractors import (
    extract_candidates,
    extract_conflicts,
    extract_explanation,
    extract_policy,
    extract_profile,
    extract_reasoning,
)
from services.tracing.trace_repository import TraceRepository
from state import AgentState


@pytest.fixture
def seeded_run_id():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_sessions (session_token) VALUES (%s) RETURNING id",
        ("trace-graph-int",),
    )
    session_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO chat_advisory_runs (session_id) VALUES (%s) RETURNING id",
        (session_id,),
    )
    run_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    yield run_id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
    conn.commit()
    cur.close()
    conn.close()


def _stub_state_returning(updates):
    def stub(state):
        for key, value in updates.items():
            setattr(state, key, value)
        return state
    return stub


def _build_test_graph(stubs):
    b = StateGraph(AgentState)
    b.add_node("profile",  traced("profile",  0, extract_profile)(stubs["profile"]))
    b.add_node("retrieve", traced("retrieve", 1, extract_candidates)(stubs["retrieve"]))
    b.add_node("conflict", traced("conflict", 2, extract_conflicts)(stubs["conflict"]))
    b.add_node("reason",   traced("reason",   3, extract_reasoning)(stubs["reason"]))
    b.add_node("policy",   traced("policy",   4, extract_policy)(stubs["policy"]))
    b.add_node("explain",  traced("explain",  5, extract_explanation)(stubs["explain"]))
    b.set_entry_point("profile")
    b.add_edge("profile", "retrieve")
    b.add_edge("retrieve", "conflict")
    b.add_edge("conflict", "reason")
    b.add_edge("reason", "policy")
    b.add_edge("policy", "explain")
    return b.compile()


@pytest.mark.integration
def test_graph_writes_six_trace_events_when_trace_run_id_set(seeded_run_id):
    candidate = CandidateProgram(
        candidate_id="x",
        school_id="x",
        school_name="X",
        admission_year=2026,
        program_name="y",
    )
    stubs = {
        "profile":  _stub_state_returning({}),
        "retrieve": _stub_state_returning({"retrieved_programs": [candidate]}),
        "conflict": _stub_state_returning({"resolution_outcomes": []}),
        "reason":   _stub_state_returning({
            "eligibility_checks": [EligibilityCheck(candidate_id="x", eligible=True, risks=[], confidence=0.9)],
            "ranked_recommendations": [RankedRecommendation(candidate_id="x", band="match", score=0.8, summary="ok")],
        }),
        "policy":   _stub_state_returning({"policy_decision":
                                           PolicyDecision(allow_answer=True, blocked_claims=[], warnings=[], policy_flags=[])}),
        "explain":  _stub_state_returning({"final_answer": "Done."}),
    }
    g = _build_test_graph(stubs)

    state = AgentState(
        user_query="Em duoc 27 diem",
        student_profile=StudentProfile(total_score=27.0),
        profile_seeded=True,
        trace_run_id=seeded_run_id,
    )
    g.invoke(state)

    repo = TraceRepository()
    events = repo.list_events_for_run(seeded_run_id)

    assert [e["stage"] for e in events] == ["profile", "retrieve", "conflict", "reason", "policy", "explain"]
    assert all(e["status"] == "completed" for e in events)
    assert all(e["duration_ms"] is not None for e in events)
    assert all(e["output_json"] is not None for e in events)
