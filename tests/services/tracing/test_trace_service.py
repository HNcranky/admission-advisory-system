from datetime import datetime, timezone

from services.tracing.trace_service import TraceService


class FakeChatRepo:
    def __init__(self, session, run_status=None):
        self._session = session
        self._run_status = run_status

    def get_session_by_token(self, token):
        return self._session

    def get_run_status(self, run_id):
        return self._run_status


class FakeTraceRepo:
    def __init__(self, events):
        self._events = events

    def list_events_for_run(self, run_id):
        return self._events


class FakeSession:
    def __init__(self, token, latest_run_id):
        self.session_token = token
        self.latest_run_id = latest_run_id


def test_returns_empty_payload_when_no_run_yet():
    chat = FakeChatRepo(session=FakeSession("tok", latest_run_id=None))
    trace = FakeTraceRepo(events=[])
    service = TraceService(chat_repository=chat, trace_repository=trace)

    payload = service.get_trace("tok")

    assert payload == {"run_id": None, "run_status": None, "events": []}


def test_returns_none_when_session_missing():
    chat = FakeChatRepo(session=None)
    trace = FakeTraceRepo(events=[])
    service = TraceService(chat_repository=chat, trace_repository=trace)

    assert service.get_trace("missing") is None


def test_synthesizes_pending_entries_for_missing_stages():
    chat = FakeChatRepo(
        session=FakeSession("tok", latest_run_id=10),
        run_status="running",
    )
    trace = FakeTraceRepo(events=[
        {
            "id": 1, "stage": "profile", "status": "completed", "sequence": 0,
            "started_at": datetime(2026, 5, 28, 3, 15, 1, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 5, 28, 3, 15, 2, tzinfo=timezone.utc),
            "duration_ms": 1234,
            "output_json": {"k": 1},
            "error_text": None,
        },
        {
            "id": 2, "stage": "retrieve", "status": "running", "sequence": 1,
            "started_at": datetime(2026, 5, 28, 3, 15, 2, tzinfo=timezone.utc),
            "completed_at": None,
            "duration_ms": None,
            "output_json": None,
            "error_text": None,
        },
    ])
    service = TraceService(chat_repository=chat, trace_repository=trace)

    payload = service.get_trace("tok")

    assert payload["run_id"] == 10
    assert payload["run_status"] == "running"
    stages = [e["stage"] for e in payload["events"]]
    assert stages == ["profile", "retrieve", "conflict", "reason", "policy", "explain"]
    assert payload["events"][0]["status"] == "completed"
    assert payload["events"][0]["duration_ms"] == 1234
    assert payload["events"][0]["started_at"] == "2026-05-28T03:15:01+00:00"
    assert payload["events"][1]["status"] == "running"
    assert payload["events"][1]["duration_ms"] is None
    assert payload["events"][2]["status"] == "pending"
    assert payload["events"][2]["sequence"] == 2
    assert payload["events"][5]["status"] == "pending"
    assert payload["events"][5]["stage"] == "explain"
