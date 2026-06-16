from services.conflict.repository import ConflictEvidenceRepository


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = None

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._cur = _FakeCursor(rows)

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_fetch_fetched_at_maps_rows_by_source_url():
    conn = _FakeConn([("https://a", None), ("https://b", None)])
    repo = ConflictEvidenceRepository(connection_factory=lambda: conn)
    result = repo.fetch_fetched_at_by_source(["https://a", "https://b"], "hust", 2024)
    assert result == {"https://a": None, "https://b": None}


def test_fetch_fetched_at_first_row_wins_per_url():
    conn = _FakeConn([("https://a", None), ("https://a", None)])
    repo = ConflictEvidenceRepository(connection_factory=lambda: conn)
    result = repo.fetch_fetched_at_by_source(["https://a"], "hust", 2024)
    assert result == {"https://a": None}
    sql, params = conn._cur.executed
    assert "= ANY(" in sql  # batched, not per-option
    assert params == (["https://a"], "hust", 2024)
