import pytest

from services.chat.db import get_db_connection
from services.tracing.trace_repository import TraceRepository


@pytest.fixture
def seeded_run_id():
    """Create a temporary session + run row for FK satisfaction; clean up after."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_sessions (session_token) VALUES (%s) RETURNING id",
        ("trace-integration-test",),
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
    # cleanup
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
    conn.commit()
    cur.close()
    conn.close()


@pytest.mark.integration
def test_full_lifecycle_writes_completed_row(seeded_run_id):
    repo = TraceRepository()

    event_id = repo.start_event(run_id=seeded_run_id, stage="profile", sequence=0)
    repo.complete_event(event_id, output_json={"count": 3, "name": "abc"})

    events = repo.list_events_for_run(seeded_run_id)
    assert len(events) == 1
    assert events[0]["stage"] == "profile"
    assert events[0]["status"] == "completed"
    assert events[0]["duration_ms"] is not None
    assert events[0]["output_json"] == {"count": 3, "name": "abc"}


@pytest.mark.integration
def test_failed_event_records_error_text(seeded_run_id):
    repo = TraceRepository()

    event_id = repo.start_event(run_id=seeded_run_id, stage="retrieve", sequence=1)
    repo.fail_event(event_id, error_text="boom")

    events = repo.list_events_for_run(seeded_run_id)
    assert events[0]["status"] == "failed"
    assert events[0]["error_text"] == "boom"
