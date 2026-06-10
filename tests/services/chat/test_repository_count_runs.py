from services.chat.repository import ChatSessionRepository


class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._row

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_count_runs_returns_scalar_for_session():
    cur = _FakeCursor((3,))
    repo = ChatSessionRepository(connection_factory=lambda: _FakeConn(cur))
    assert repo.count_runs("tok-123") == 3
    sql, params = cur.executed[-1]
    assert "chat_advisory_runs" in sql
    assert params == ("tok-123",)
