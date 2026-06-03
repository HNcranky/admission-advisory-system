from services.chat.advisory_runner import run_advisory_for_session
from services.chat.models import ChatProfileState


def test_run_advisory_for_session_seeds_agent_state(monkeypatch):
    captured = {}

    def fake_invoke(state):
        captured["state"] = state
        return {"final_answer": "ok"}

    monkeypatch.setattr("services.chat.advisory_runner.graph.invoke", fake_invoke)

    run_advisory_for_session(
        ChatProfileState(
            admission_year=2026,
            total_score=27.0,
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
        latest_user_message="Em duoc 27 diem va muon hoc CNTT",
    )

    assert captured["state"].profile_seeded is True
    assert captured["state"].student_profile.total_score == 27.0
    assert captured["state"].admission_year == 2026


def test_run_advisory_for_session_passes_trace_run_id_to_state(monkeypatch):
    captured = {}

    def fake_invoke(state):
        captured["trace_run_id"] = state.trace_run_id
        return {"final_answer": "ok"}

    monkeypatch.setattr("services.chat.advisory_runner.graph.invoke", fake_invoke)

    run_advisory_for_session(
        ChatProfileState(admission_year=2026),
        latest_user_message="hello",
        trace_run_id=42,
    )

    assert captured["trace_run_id"] == 42


def test_run_advisory_for_session_default_trace_run_id_is_none(monkeypatch):
    captured = {}

    def fake_invoke(state):
        captured["trace_run_id"] = state.trace_run_id
        return {"final_answer": "ok"}

    monkeypatch.setattr("services.chat.advisory_runner.graph.invoke", fake_invoke)

    run_advisory_for_session(
        ChatProfileState(admission_year=2026),
        latest_user_message="hello",
    )

    assert captured["trace_run_id"] is None
