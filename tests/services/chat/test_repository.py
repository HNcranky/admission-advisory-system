from unittest.mock import MagicMock

from psycopg2.extras import Json

from services.chat.models import ChatProfileState, FlowState
from services.chat.repository import ChatSessionRepository


def _make_conn(fetchone_return=None):
    """Returns (conn, cursor) MagicMocks wired together. Cursor returns tuples (like psycopg2)."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_return
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


class FakeCursor:
    def __init__(self):
        self.statements = []
        self._row = (
            1,
            "session-123",
            "collecting_profile",
            {},
            None,
        )
        self._rows = [
            (1, "session-123", "assistant", "assistant_welcome", "Chào bạn"),
            (2, "session-123", "user", "user_message", "Em muon hoc CNTT"),
        ]

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return self._row
    
    def fetchall(self):
        return self._rows

    def close(self):
        return None


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def test_create_session_persists_token_and_returns_record():
    connection = FakeConnection()
    repo = ChatSessionRepository(connection_factory=lambda: connection)

    session = repo.create_session("session-123")

    assert session.session_token == "session-123"
    assert session.status == "collecting_profile"
    assert "INSERT INTO chat_sessions" in connection.cursor_obj.statements[0][0]
    assert connection.committed is True
    
    
def test_list_message_returns_transcript_in_order():
    connection = FakeConnection()
    repo = ChatSessionRepository(connection_factory=lambda: connection)

    messages = repo.list_message("session-123")

    assert [message.kind for message in messages] == [
        "assistant_welcome",
        "user_message",
    ]
    sql = connection.cursor_obj.statements[0][0]
    assert "JOIN chat_sessions s ON s.id = m.session_id" in sql
    assert "WHERE s.session_token = %s" in sql


def test_repository_wraps_jsonb_payloads_with_psycopg2_json_adapter():
    connection = FakeConnection()
    repo = ChatSessionRepository(connection_factory=lambda: connection)
    profile_state = ChatProfileState(
        admission_year=2026,
        preferred_majors=["computer_science"],
        missing_slots=["total_score"],
    )

    repo.update_profile_state("session-123", profile_state, "collecting_profile")
    repo.create_run("session-123", profile_state)
    repo.complete_run(7, {"final_answer": "ok", "profile_state": profile_state}, "ok")

    update_params = connection.cursor_obj.statements[0][1]
    create_run_params = connection.cursor_obj.statements[1][1]
    complete_run_params = connection.cursor_obj.statements[3][1]

    assert isinstance(update_params[0], Json)
    assert isinstance(create_run_params[0], Json)
    assert isinstance(complete_run_params[0], Json)
    assert complete_run_params[0].adapted["profile_state"]["admission_year"] == 2026


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


# --- get_flow_state ---

def test_get_flow_state_returns_default_when_column_is_null():
    conn, _ = _make_conn(fetchone_return=(None,))   # row exists, column value is NULL
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    result = repo.get_flow_state("tok-1")

    assert result == FlowState()
    assert result.active_flow is None
    assert result.pending_question is None


def test_get_flow_state_returns_default_when_row_missing():
    conn, _ = _make_conn(fetchone_return=None)   # no session row at all
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    result = repo.get_flow_state("tok-1")

    assert result == FlowState()


def test_get_flow_state_returns_persisted_state():
    saved = {"active_flow": "ADVISORY_FLOW", "pending_question": "Bạn học khối gì?"}
    conn, _ = _make_conn(fetchone_return=(saved,))
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    result = repo.get_flow_state("tok-1")

    assert result.active_flow == "ADVISORY_FLOW"
    assert result.pending_question == "Bạn học khối gì?"


def test_get_flow_state_queries_correct_table_and_token():
    conn, cursor = _make_conn(fetchone_return=(None,))
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    repo.get_flow_state("my-token")

    sql = cursor.execute.call_args[0][0]
    params = cursor.execute.call_args[0][1]
    assert "flow_state_json" in sql
    assert "chat_sessions" in sql
    assert params == ("my-token",)


# --- update_flow_state ---

def test_update_flow_state_executes_update_sql_and_commits():
    conn, cursor = _make_conn()
    repo = ChatSessionRepository(connection_factory=lambda: conn)
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Q?")

    repo.update_flow_state("tok-1", flow)

    cursor.execute.assert_called_once()
    sql = cursor.execute.call_args[0][0]
    assert "flow_state_json" in sql
    assert "chat_sessions" in sql
    conn.commit.assert_called_once()


def test_update_flow_state_wraps_value_with_jsonb_helper():
    """Must use self._jsonb(...) like every other write, not a raw model_dump_json string."""
    conn, cursor = _make_conn()
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    repo.update_flow_state("tok-1", FlowState(active_flow="ADVISORY_FLOW"))

    first_param = cursor.execute.call_args[0][1][0]
    # psycopg2.extras.Json wraps the dict; its .adapted attribute holds the original value
    assert getattr(first_param, "adapted", None) == {
        "active_flow": "ADVISORY_FLOW",
        "pending_question": None,
    }


def test_update_flow_state_passes_correct_session_token():
    conn, cursor = _make_conn()
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    repo.update_flow_state("specific-token", FlowState())

    params = cursor.execute.call_args[0][1]
    assert "specific-token" in params


def test_update_flow_state_closes_connection():
    conn, cursor = _make_conn()
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    repo.update_flow_state("tok-1", FlowState())

    assert cursor.close.called
    assert conn.close.called
