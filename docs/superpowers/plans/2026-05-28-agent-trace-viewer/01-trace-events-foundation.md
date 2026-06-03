# Slice 01 — Trace Events Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the persistence layer for per-stage trace events — schema, repository, and the plumbing that carries a `trace_run_id` from the dispatcher into `AgentState`. After this slice, the system can record trace rows when called directly; it does NOT yet auto-record from the LangGraph nodes (that arrives in Slice 02).

**Architecture:** Add table `advisory_trace_events`, a thin `TraceRepository` with `start_event` / `complete_event` / `fail_event`, a new optional `AgentState.trace_run_id`, and pass that id from `RunDispatcher` through `run_advisory_for_session`. No graph wiring yet.

**Tech Stack:** Python 3.12, psycopg2, pydantic v2, pytest.

---

### Task 1: Migration `011_advisory_trace_events.sql`

**Files:**
- Create: `db/migrations/011_advisory_trace_events.sql`

- [ ] **Step 1: Write the migration**

```sql
CREATE TABLE IF NOT EXISTS advisory_trace_events (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES chat_advisory_runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    output_json JSONB,
    error_text TEXT,
    UNIQUE (run_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_trace_events_run
    ON advisory_trace_events (run_id, sequence);
```

- [ ] **Step 2: Apply migration twice to confirm idempotency**

Run:
```powershell
python -m db.setup_db
python -m db.setup_db
```
Expected: both succeed; second run is a no-op.

- [ ] **Step 3: Verify schema in psql**

Run:
```powershell
docker compose exec db psql -U postgres -d admission -c "\d advisory_trace_events"
```
Expected: columns `id, run_id, stage, status, sequence, started_at, completed_at, duration_ms, output_json, error_text` are present; unique constraint `(run_id, stage)` shown.

- [ ] **Step 4: Commit**

```powershell
git add db/migrations/011_advisory_trace_events.sql
git commit -m "feat(db): add advisory_trace_events table for per-stage trace persistence"
```

---

### Task 2: `AgentState.trace_run_id`

**Files:**
- Modify: `state.py`
- Test: `tests/test_state.py` (create if missing)

- [ ] **Step 1: Write the failing test**

Create `tests/test_state.py`:

```python
from state import AgentState


def test_agent_state_default_trace_run_id_is_none():
    state = AgentState(user_query="hello")
    assert state.trace_run_id is None


def test_agent_state_accepts_trace_run_id():
    state = AgentState(user_query="hello", trace_run_id=42)
    assert state.trace_run_id == 42
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `pytest tests/test_state.py -v`
Expected: FAIL — `AgentState` rejects unknown field `trace_run_id` (pydantic raises `ValidationError`).

- [ ] **Step 3: Add the field**

In `state.py`, add to the `AgentState` class (after `final_answer: Optional[str] = None`):

```python
    trace_run_id: Optional[int] = None
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_state.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```powershell
git add state.py tests/test_state.py
git commit -m "feat(state): add optional trace_run_id field on AgentState"
```

---

### Task 3: `services/tracing/` package skeleton

**Files:**
- Create: `services/tracing/__init__.py`
- Create: `tests/services/tracing/__init__.py`

- [ ] **Step 1: Create empty package files**

`services/tracing/__init__.py` — empty (one trailing newline).
`tests/services/tracing/__init__.py` — empty (one trailing newline).

- [ ] **Step 2: Confirm pytest discovers the new test directory**

Run: `pytest tests/services/tracing -v`
Expected: `no tests ran` (not an import error).

- [ ] **Step 3: Commit**

```powershell
git add services/tracing/__init__.py tests/services/tracing/__init__.py
git commit -m "chore(tracing): scaffold services/tracing package"
```

---

### Task 4: `TraceRepository.start_event`

**Files:**
- Create: `services/tracing/trace_repository.py`
- Create: `tests/services/tracing/test_trace_repository.py`

- [ ] **Step 1: Write the failing test**

```python
from services.tracing.trace_repository import TraceRepository


class FakeCursor:
    def __init__(self, fetch_value=(99,)):
        self.statements = []
        self._fetch = fetch_value

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return self._fetch

    def close(self):
        return None


class FakeConnection:
    def __init__(self, cursor=None):
        self.cursor_obj = cursor or FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def test_start_event_inserts_running_row_and_returns_id():
    conn = FakeConnection(FakeCursor(fetch_value=(123,)))
    repo = TraceRepository(connection_factory=lambda: conn)

    event_id = repo.start_event(run_id=7, stage="profile", sequence=0)

    assert event_id == 123
    sql, params = conn.cursor_obj.statements[0]
    assert "INSERT INTO advisory_trace_events" in sql
    assert "status" in sql
    assert params[0] == 7
    assert params[1] == "profile"
    assert params[2] == "running"
    assert params[3] == 0
    assert conn.committed is True
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/services/tracing/test_trace_repository.py -v`
Expected: FAIL — `ImportError: cannot import name 'TraceRepository'`.

- [ ] **Step 3: Implement `start_event`**

Create `services/tracing/trace_repository.py`:

```python
from services.chat.db import get_db_connection


class TraceRepository:
    def __init__(self, connection_factory=get_db_connection):
        self.connection_factory = connection_factory

    def start_event(self, run_id: int, stage: str, sequence: int) -> int:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO advisory_trace_events
                (run_id, stage, status, sequence, started_at)
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (run_id, stage, "running", sequence),
        )
        event_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return event_id
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_trace_repository.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/trace_repository.py tests/services/tracing/test_trace_repository.py
git commit -m "feat(tracing): TraceRepository.start_event inserts running row"
```

---

### Task 5: `TraceRepository.complete_event`

**Files:**
- Modify: `services/tracing/trace_repository.py`
- Modify: `tests/services/tracing/test_trace_repository.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/services/tracing/test_trace_repository.py`:

```python
def test_complete_event_updates_row_with_output_and_duration():
    conn = FakeConnection()
    repo = TraceRepository(connection_factory=lambda: conn)

    repo.complete_event(event_id=55, output_json={"count": 3})

    sql, params = conn.cursor_obj.statements[0]
    assert "UPDATE advisory_trace_events" in sql
    assert "status" in sql and "completed_at" in sql and "duration_ms" in sql
    assert "output_json" in sql
    # params end with the row id; the JSONB-wrapped output is second-to-last
    assert params[-1] == 55
    assert conn.committed is True
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_trace_repository.py::test_complete_event_updates_row_with_output_and_duration -v`
Expected: FAIL — `AttributeError: complete_event`.

- [ ] **Step 3: Implement `complete_event`**

Append to `services/tracing/trace_repository.py`:

```python
from fastapi.encoders import jsonable_encoder
from psycopg2.extras import Json
```

(Add these imports at the top alongside the existing one.)

Add method:

```python
    def complete_event(self, event_id: int, output_json: dict) -> None:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE advisory_trace_events
            SET status = 'completed',
                completed_at = NOW(),
                duration_ms = EXTRACT(MILLISECONDS FROM (NOW() - started_at))::INTEGER,
                output_json = %s
            WHERE id = %s
            """,
            (Json(jsonable_encoder(output_json)), event_id),
        )
        conn.commit()
        cur.close()
        conn.close()
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_trace_repository.py -v`
Expected: PASS (3 tests now, all green).

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/trace_repository.py tests/services/tracing/test_trace_repository.py
git commit -m "feat(tracing): TraceRepository.complete_event records output and duration"
```

---

### Task 6: `TraceRepository.fail_event`

**Files:**
- Modify: `services/tracing/trace_repository.py`
- Modify: `tests/services/tracing/test_trace_repository.py`

- [ ] **Step 1: Write the failing test**

```python
def test_fail_event_updates_row_with_error_text():
    conn = FakeConnection()
    repo = TraceRepository(connection_factory=lambda: conn)

    repo.fail_event(event_id=77, error_text="ValueError: bad input")

    sql, params = conn.cursor_obj.statements[0]
    assert "UPDATE advisory_trace_events" in sql
    assert "status" in sql and "error_text" in sql
    assert params[0] == "ValueError: bad input"
    assert params[-1] == 77
    assert conn.committed is True
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_trace_repository.py::test_fail_event_updates_row_with_error_text -v`
Expected: FAIL — `AttributeError: fail_event`.

- [ ] **Step 3: Implement `fail_event`**

Add to `services/tracing/trace_repository.py`:

```python
    def fail_event(self, event_id: int, error_text: str) -> None:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE advisory_trace_events
            SET status = 'failed',
                completed_at = NOW(),
                duration_ms = EXTRACT(MILLISECONDS FROM (NOW() - started_at))::INTEGER,
                error_text = %s
            WHERE id = %s
            """,
            (error_text, event_id),
        )
        conn.commit()
        cur.close()
        conn.close()
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_trace_repository.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/trace_repository.py tests/services/tracing/test_trace_repository.py
git commit -m "feat(tracing): TraceRepository.fail_event records error_text"
```

---

### Task 7: `TraceRepository.list_events_for_run` (read-side)

**Files:**
- Modify: `services/tracing/trace_repository.py`
- Modify: `tests/services/tracing/test_trace_repository.py`

This read method is consumed by the API in Slice 03 but is colocated with the repository.

- [ ] **Step 1: Write the failing test**

Add to the test file (you'll need to extend `FakeCursor` to support `fetchall`):

```python
class FakeCursorWithRows(FakeCursor):
    def __init__(self, rows):
        super().__init__()
        self._rows = rows

    def fetchall(self):
        return self._rows


def test_list_events_for_run_returns_rows_sorted_by_sequence():
    rows = [
        (10, "profile",  "completed", 0, "2026-05-28T03:15:01+00:00", "2026-05-28T03:15:02+00:00", 1234, {"k": 1}, None),
        (11, "retrieve", "running",   1, "2026-05-28T03:15:02+00:00", None, None, None, None),
    ]
    conn = FakeConnection(FakeCursorWithRows(rows))
    repo = TraceRepository(connection_factory=lambda: conn)

    events = repo.list_events_for_run(run_id=7)

    assert len(events) == 2
    assert events[0]["stage"] == "profile"
    assert events[0]["status"] == "completed"
    assert events[0]["duration_ms"] == 1234
    assert events[0]["output_json"] == {"k": 1}
    assert events[1]["stage"] == "retrieve"
    assert events[1]["status"] == "running"
    assert events[1]["duration_ms"] is None
    sql, params = conn.cursor_obj.statements[0]
    assert "SELECT" in sql and "advisory_trace_events" in sql
    assert "ORDER BY sequence" in sql
    assert params == (7,)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_trace_repository.py::test_list_events_for_run_returns_rows_sorted_by_sequence -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `services/tracing/trace_repository.py`:

```python
    def list_events_for_run(self, run_id: int) -> list[dict]:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, stage, status, sequence, started_at, completed_at,
                   duration_ms, output_json, error_text
            FROM advisory_trace_events
            WHERE run_id = %s
            ORDER BY sequence ASC
            """,
            (run_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0],
                "stage": r[1],
                "status": r[2],
                "sequence": r[3],
                "started_at": r[4],
                "completed_at": r[5],
                "duration_ms": r[6],
                "output_json": r[7],
                "error_text": r[8],
            }
            for r in rows
        ]
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_trace_repository.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/trace_repository.py tests/services/tracing/test_trace_repository.py
git commit -m "feat(tracing): TraceRepository.list_events_for_run for API consumption"
```

---

### Task 8: Plumb `trace_run_id` through `advisory_runner`

**Files:**
- Modify: `services/chat/advisory_runner.py`
- Modify: `tests/services/chat/test_advisory_runner.py`

- [ ] **Step 1: Write the failing test**

Open `tests/services/chat/test_advisory_runner.py` and add:

```python
from unittest.mock import patch

from services.chat.advisory_runner import run_advisory_for_session
from services.chat.models import ChatProfileState


def test_run_advisory_for_session_passes_trace_run_id_to_state():
    captured = {}

    def fake_invoke(state):
        captured["trace_run_id"] = state.trace_run_id
        return {"final_answer": "ok"}

    with patch("services.chat.advisory_runner.graph") as mock_graph:
        mock_graph.invoke = fake_invoke
        run_advisory_for_session(
            profile_state=ChatProfileState(admission_year=2026),
            latest_user_message="hello",
            trace_run_id=42,
        )

    assert captured["trace_run_id"] == 42


def test_run_advisory_for_session_default_trace_run_id_is_none():
    captured = {}

    def fake_invoke(state):
        captured["trace_run_id"] = state.trace_run_id
        return {"final_answer": "ok"}

    with patch("services.chat.advisory_runner.graph") as mock_graph:
        mock_graph.invoke = fake_invoke
        run_advisory_for_session(
            profile_state=ChatProfileState(admission_year=2026),
            latest_user_message="hello",
        )

    assert captured["trace_run_id"] is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/chat/test_advisory_runner.py -v`
Expected: FAIL — either `TypeError: unexpected keyword 'trace_run_id'` or assertion failure.

- [ ] **Step 3: Modify `advisory_runner.py`**

Replace the entire file with:

```python
from agents.models import StudentProfile
from graph import graph
from state import AgentState


def run_advisory_for_session(profile_state, latest_user_message: str, trace_run_id: int | None = None):
    student_profile = StudentProfile(
        total_score=profile_state.total_score,
        subject_combination=profile_state.subject_combination,
        preferred_majors=profile_state.preferred_majors,
        preferred_schools=profile_state.preferred_schools,
        location_preference=profile_state.location_preference,
        tuition_budget=profile_state.tuition_budget,
        constraints=profile_state.constraints,
        missing_slots=profile_state.missing_slots,
    )

    state = AgentState(
        user_query=latest_user_message,
        admission_year=profile_state.admission_year or 2026,
        student_profile=student_profile,
        profile_seeded=True,
        trace_run_id=trace_run_id,
    )

    return graph.invoke(state)
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/services/chat/test_advisory_runner.py -v`
Expected: PASS for the new tests; pre-existing tests still pass (they don't pass `trace_run_id`, default `None`).

- [ ] **Step 5: Commit**

```powershell
git add services/chat/advisory_runner.py tests/services/chat/test_advisory_runner.py
git commit -m "feat(chat): pass trace_run_id from runner into AgentState"
```

---

### Task 9: Plumb `run_id` through `RunDispatcher`

**Files:**
- Modify: `services/chat/run_dispatcher.py`
- Modify: `tests/services/chat/test_run_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/services/chat/test_run_dispatcher.py`:

```python
def test_dispatcher_passes_run_id_as_trace_run_id_to_runner():
    repo = FakeRepository()
    captured = {}

    def runner(profile_state, latest_user_message, trace_run_id=None):
        captured["trace_run_id"] = trace_run_id
        return {"final_answer": "ok"}

    dispatcher = RunDispatcher(
        repository=repo,
        runner=runner,
        executor=InlineExecutor(),
    )

    dispatcher.submit(
        session_token="session-xyz",
        run_id=99,
        latest_user_message="hello",
        profile_state=ChatProfileState(admission_year=2026),
    )

    assert captured["trace_run_id"] == 99
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/chat/test_run_dispatcher.py::test_dispatcher_passes_run_id_as_trace_run_id_to_runner -v`
Expected: FAIL — runner receives no `trace_run_id` kwarg (current dispatcher calls `self.runner(profile_state, latest_user_message)`).

- [ ] **Step 3: Modify `run_dispatcher.py`**

In `services/chat/run_dispatcher.py`, change the line in `_execute`:

```python
            result = self.runner(profile_state, latest_user_message)
```
to:
```python
            result = self.runner(profile_state, latest_user_message, trace_run_id=run_id)
```

- [ ] **Step 4: Run all dispatcher tests**

Run: `pytest tests/services/chat/test_run_dispatcher.py -v`
Expected: PASS for the new test. The pre-existing tests use `lambda profile_state, latest_user_message: ...` — they will FAIL with `TypeError: unexpected keyword 'trace_run_id'`. Update them to accept `**_` or `trace_run_id=None`:

In existing tests, change each runner lambda to:
```python
runner=lambda profile_state, latest_user_message, trace_run_id=None: ...
```

Re-run; expected: ALL PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/chat/run_dispatcher.py tests/services/chat/test_run_dispatcher.py
git commit -m "feat(chat): dispatcher forwards run_id as trace_run_id to advisory runner"
```

---

### Task 10: Integration smoke test (real Postgres)

**Files:**
- Create: `tests/services/tracing/test_trace_repository_integration.py`

- [ ] **Step 1: Write the integration test**

```python
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
```

- [ ] **Step 2: Run integration tests against the docker DB**

Run:
```powershell
docker compose up -d --wait db
pytest tests/services/tracing/test_trace_repository_integration.py -m integration -v
```
Expected: PASS (both tests).

- [ ] **Step 3: Confirm unit suite still green**

Run: `pytest -m "not integration"`
Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/services/tracing/test_trace_repository_integration.py
git commit -m "test(tracing): integration coverage for TraceRepository lifecycle"
```

---

## Slice 01 Done When

- `python -m db.setup_db` is idempotent and creates `advisory_trace_events`.
- `TraceRepository` has `start_event`, `complete_event`, `fail_event`, `list_events_for_run`, all unit-tested with `FakeConnection` and integration-tested against real Postgres.
- `AgentState.trace_run_id` exists, defaults to `None`.
- `RunDispatcher._execute` passes its `run_id` to `run_advisory_for_session(..., trace_run_id=...)`.
- Full test suite passes: `pytest -m "not integration"` (and `pytest -m integration` with the docker DB up).

Next slice: [02 — Tracer wrapper + extractors](./02-tracer-wrapper-and-extractors.md).
