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
