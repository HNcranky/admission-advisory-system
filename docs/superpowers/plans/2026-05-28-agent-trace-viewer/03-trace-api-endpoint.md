# Slice 03 — Trace API Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose trace events to the chat UI via `GET /api/sessions/{session_token}/trace`. The endpoint always returns six entries — pending entries for stages that have no row yet — so the UI can render the full ladder from the first poll.

**Architecture:** New `TraceService` resolves session → latest run id → events; synthesizes pending entries for missing stages. Endpoint serializes datetime fields to ISO 8601 strings. Returns `{run_id, run_status, events}`.

**Tech Stack:** FastAPI, pytest, FastAPI's `TestClient`.

---

### Task 1: Repository helper to resolve a session's latest run

**Files:**
- Modify: `services/chat/repository.py`
- Modify: `tests/services/chat/test_repository.py`

`ChatSessionRepository.get_session_by_token` already returns `latest_run_id`. We need a small helper that, given a `run_id`, returns its `status`.

- [ ] **Step 1: Write the failing test**

In `tests/services/chat/test_repository.py`, append:

```python
class FakeCursorRunStatus(FakeCursor):
    def __init__(self, status):
        super().__init__()
        self._row = (status,)


def test_get_run_status_returns_status_string():
    conn = FakeConnection()
    conn.cursor_obj = FakeCursorRunStatus("running")
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    status = repo.get_run_status(run_id=42)

    sql, params = conn.cursor_obj.statements[0]
    assert status == "running"
    assert "SELECT status" in sql and "chat_advisory_runs" in sql
    assert params == (42,)


def test_get_run_status_returns_none_when_missing():
    class EmptyCursor(FakeCursor):
        def fetchone(self):
            return None
    conn = FakeConnection()
    conn.cursor_obj = EmptyCursor()
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    assert repo.get_run_status(run_id=999) is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/chat/test_repository.py -v`
Expected: FAIL — `AttributeError: get_run_status`.

- [ ] **Step 3: Implement**

Append to `services/chat/repository.py` `ChatSessionRepository`:

```python
    def get_run_status(self, run_id: int):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM chat_advisory_runs WHERE id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/services/chat/test_repository.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```powershell
git add services/chat/repository.py tests/services/chat/test_repository.py
git commit -m "feat(chat): ChatSessionRepository.get_run_status helper"
```

---

### Task 2: `TraceService` — pending-stage synthesis

**Files:**
- Create: `services/tracing/trace_service.py`
- Create: `tests/services/tracing/test_trace_service.py`

- [ ] **Step 1: Write the failing test for the "no run yet" case**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_trace_service.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement minimal `TraceService`**

Create `services/tracing/trace_service.py`:

```python
from services.chat.repository import ChatSessionRepository
from services.tracing.agent_tracer import STAGE_ORDER
from services.tracing.trace_repository import TraceRepository


class TraceService:
    def __init__(self, chat_repository=None, trace_repository=None):
        self.chat_repository = chat_repository or ChatSessionRepository()
        self.trace_repository = trace_repository or TraceRepository()

    def get_trace(self, session_token: str):
        session = self.chat_repository.get_session_by_token(session_token)
        if session is None:
            return None
        run_id = session.latest_run_id
        if run_id is None:
            return {"run_id": None, "run_status": None, "events": []}
        return {"run_id": run_id, "run_status": None, "events": []}  # filled in next tasks
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_trace_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/trace_service.py tests/services/tracing/test_trace_service.py
git commit -m "feat(tracing): TraceService scaffold returning empty payload"
```

---

### Task 3: `TraceService` — return None for unknown session

**Files:**
- Modify: `tests/services/tracing/test_trace_service.py`
- (impl already handles this; just lock with a test)

- [ ] **Step 1: Add test**

```python
def test_returns_none_when_session_missing():
    chat = FakeChatRepo(session=None)
    trace = FakeTraceRepo(events=[])
    service = TraceService(chat_repository=chat, trace_repository=trace)

    assert service.get_trace("missing") is None
```

- [ ] **Step 2: Run**

Run: `pytest tests/services/tracing/test_trace_service.py -v`
Expected: PASS (the impl from Task 2 already returns `None`).

- [ ] **Step 3: Commit**

```powershell
git add tests/services/tracing/test_trace_service.py
git commit -m "test(tracing): lock behavior for unknown session"
```

---

### Task 4: `TraceService` — merge DB events with synthesized pending entries

**Files:**
- Modify: `services/tracing/trace_service.py`
- Modify: `tests/services/tracing/test_trace_service.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone


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
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_trace_service.py::test_synthesizes_pending_entries_for_missing_stages -v`
Expected: FAIL.

- [ ] **Step 3: Implement merge logic**

Replace `TraceService.get_trace` in `services/tracing/trace_service.py`:

```python
    def get_trace(self, session_token: str):
        session = self.chat_repository.get_session_by_token(session_token)
        if session is None:
            return None
        run_id = session.latest_run_id
        if run_id is None:
            return {"run_id": None, "run_status": None, "events": []}

        run_status = self.chat_repository.get_run_status(run_id)
        raw_events = self.trace_repository.list_events_for_run(run_id)
        by_stage = {e["stage"]: e for e in raw_events}

        events = []
        for sequence, stage in enumerate(STAGE_ORDER):
            if stage in by_stage:
                events.append(self._serialize_event(by_stage[stage]))
            else:
                events.append({
                    "stage": stage,
                    "sequence": sequence,
                    "status": "pending",
                    "started_at": None,
                    "completed_at": None,
                    "duration_ms": None,
                    "output_json": None,
                    "error_text": None,
                })

        return {"run_id": run_id, "run_status": run_status, "events": events}

    @staticmethod
    def _serialize_event(event: dict) -> dict:
        return {
            "stage": event["stage"],
            "sequence": event["sequence"],
            "status": event["status"],
            "started_at": event["started_at"].isoformat() if event["started_at"] else None,
            "completed_at": event["completed_at"].isoformat() if event["completed_at"] else None,
            "duration_ms": event["duration_ms"],
            "output_json": event["output_json"],
            "error_text": event["error_text"],
        }
```

- [ ] **Step 4: Run all `TraceService` tests**

Run: `pytest tests/services/tracing/test_trace_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/trace_service.py tests/services/tracing/test_trace_service.py
git commit -m "feat(tracing): TraceService merges DB events with synthesized pending stages"
```

---

### Task 5: FastAPI endpoint `GET /api/sessions/{token}/trace`

**Files:**
- Modify: `web/routes/chat_api.py`
- Create: `tests/web/__init__.py` (if missing)
- Create: `tests/web/test_trace_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_trace_endpoint.py`:

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.app import build_app


def test_trace_endpoint_returns_payload_for_known_session():
    fake_payload = {
        "run_id": 42,
        "run_status": "running",
        "events": [
            {"stage": "profile", "sequence": 0, "status": "completed",
             "duration_ms": 1234, "started_at": "2026-05-28T03:15:01+00:00",
             "completed_at": "2026-05-28T03:15:02+00:00",
             "output_json": {"k": 1}, "error_text": None},
        ],
    }

    with patch("web.routes.chat_api.TraceService") as mock_cls:
        mock_cls.return_value.get_trace.return_value = fake_payload
        client = TestClient(build_app())
        response = client.get("/api/sessions/abc-token/trace")

    assert response.status_code == 200
    assert response.json() == fake_payload


def test_trace_endpoint_returns_404_for_unknown_session():
    with patch("web.routes.chat_api.TraceService") as mock_cls:
        mock_cls.return_value.get_trace.return_value = None
        client = TestClient(build_app())
        response = client.get("/api/sessions/unknown/trace")

    assert response.status_code == 404
```

If `tests/web/__init__.py` does not exist, create it (empty).

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/web/test_trace_endpoint.py -v`
Expected: FAIL — endpoint not registered (`response.status_code == 404` even for the known-session test? — actually all 404 because route doesn't exist; the second test passes spuriously, the first fails).

- [ ] **Step 3: Implement the route**

Edit `web/routes/chat_api.py`:

Add import at the top:
```python
from services.tracing.trace_service import TraceService
```

Add factory:
```python
def get_trace_service():
    return TraceService()
```

Add route:
```python
@router.get("/{session_token}/trace")
def get_trace(session_token: str):
    payload = get_trace_service().get_trace(session_token)
    if payload is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return payload
```

- [ ] **Step 4: Run all web tests**

Run: `pytest tests/web/test_trace_endpoint.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Run the full non-integration suite to confirm no regression**

Run: `pytest -m "not integration"`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add web/routes/chat_api.py tests/web/test_trace_endpoint.py tests/web/__init__.py
git commit -m "feat(web): GET /api/sessions/{token}/trace endpoint"
```

---

### Task 6: End-to-end smoke test against real DB

**Files:**
- Create: `tests/web/test_trace_endpoint_integration.py`

This proves session → run → trace events flow end-to-end through the HTTP layer.

- [ ] **Step 1: Write the integration test**

```python
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
```

- [ ] **Step 2: Run the integration test**

Run:
```powershell
docker compose up -d --wait db
pytest tests/web/test_trace_endpoint_integration.py -m integration -v
```
Expected: PASS (both tests).

- [ ] **Step 3: Commit**

```powershell
git add tests/web/test_trace_endpoint_integration.py
git commit -m "test(web): integration test for trace endpoint pending+mixed ladders"
```

---

## Slice 03 Done When

- `GET /api/sessions/{token}/trace` returns the 6-entry ladder, mixed states, ISO 8601 timestamps.
- 404 for unknown session.
- TraceService unit-tested with fakes; endpoint unit-tested with `TestClient` + mock `TraceService`; both integration-tested against real Postgres.
- `pytest -m "not integration"` and `pytest -m integration` (with docker DB up) both pass.

Next slice: [04 — Debug panel UI](./04-debug-panel-ui.md).
