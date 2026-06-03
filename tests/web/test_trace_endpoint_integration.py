import pytest
from fastapi.testclient import TestClient

from services.chat.db import get_db_connection
from services.tracing.trace_repository import TraceRepository
from web.app import build_app


@pytest.fixture
def seeded_session_and_run():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO chat_sessions (session_token) VALUES (%s) RETURNING id",
                ("trace-e2e-test",))
    session_id = cur.fetchone()[0]
    cur.execute("INSERT INTO chat_advisory_runs (session_id, status) VALUES (%s, %s) RETURNING id",
                (session_id, "running"))
    run_id = cur.fetchone()[0]
    cur.execute("UPDATE chat_sessions SET latest_run_id = %s WHERE id = %s",
                (run_id, session_id))
    conn.commit()
    cur.close()
    conn.close()
    yield "trace-e2e-test", run_id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
    conn.commit()
    cur.close()
    conn.close()


@pytest.mark.integration
def test_trace_endpoint_returns_pending_ladder_before_any_events(seeded_session_and_run):
    token, _run_id = seeded_session_and_run
    client = TestClient(build_app())

    response = client.get(f"/api/sessions/{token}/trace")

    assert response.status_code == 200
    body = response.json()
    assert body["run_status"] == "running"
    assert [e["stage"] for e in body["events"]] == [
        "profile", "retrieve", "conflict", "reason", "policy", "explain"
    ]
    assert all(e["status"] == "pending" for e in body["events"])


@pytest.mark.integration
def test_trace_endpoint_returns_mixed_states_after_two_stages_complete(seeded_session_and_run):
    token, run_id = seeded_session_and_run
    repo = TraceRepository()

    e0 = repo.start_event(run_id, "profile", 0)
    repo.complete_event(e0, {"student_profile": {"total_score": 27.0}})
    e1 = repo.start_event(run_id, "retrieve", 1)
    repo.complete_event(e1, {"count": 5})
    repo.start_event(run_id, "conflict", 2)  # left in 'running'

    client = TestClient(build_app())
    response = client.get(f"/api/sessions/{token}/trace")
    body = response.json()

    statuses = [e["status"] for e in body["events"]]
    assert statuses == ["completed", "completed", "running", "pending", "pending", "pending"]
    assert body["events"][0]["output_json"] == {"student_profile": {"total_score": 27.0}}
    assert body["events"][0]["duration_ms"] is not None
