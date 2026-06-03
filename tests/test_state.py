from state import AgentState


def test_agent_state_default_trace_run_id_is_none():
    state = AgentState(user_query="hello")
    assert state.trace_run_id is None


def test_agent_state_accepts_trace_run_id():
    state = AgentState(user_query="hello", trace_run_id=42)
    assert state.trace_run_id == 42
