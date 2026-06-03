from ingestion.knowledge import verify_corpus


class FakeCursor:
    def __init__(self, fetchall_return=None, fetchone_return=None):
        self.statements = []
        self._fetchall = fetchall_return or []
        self._fetchone = fetchone_return

    def execute(self, sql, params=None):
        self.statements.append(sql)

    def fetchall(self):
        return self._fetchall

    def fetchone(self):
        return self._fetchone

    def close(self):
        return None


class FakeConnection:
    def __init__(self, fetchall_return=None, fetchone_return=None):
        self.cursor_obj = FakeCursor(fetchall_return, fetchone_return)

    def cursor(self):
        return self.cursor_obj

    def close(self):
        return None


class FakeRegistry:
    def __init__(self, schools):
        self._schools = schools

    def schools(self):
        return list(self._schools)


def test_find_missing_schools_flags_schools_with_no_chunks():
    counts = [("HUST", "tuition", 5), ("NEU", "tuition", 0)]
    missing = verify_corpus.find_missing_schools(["HUST", "NEU", "VNU-UET"], counts)
    assert missing == ["NEU", "VNU-UET"]   # NEU has only a 0-count row; VNU-UET absent


def test_collect_counts_runs_group_by_query():
    conn = FakeConnection(fetchall_return=[("HUST", "tuition", 3)])
    counts = verify_corpus.collect_counts(connection_factory=lambda: conn)
    assert counts == [("HUST", "tuition", 3)]
    assert "GROUP BY school, topic" in conn.cursor_obj.statements[0]


def test_main_returns_1_when_a_school_is_missing():
    conn = FakeConnection(fetchall_return=[("HUST", "tuition", 3)], fetchone_return=(0,))
    code = verify_corpus.main(
        connection_factory=lambda: conn,
        registry=FakeRegistry(["HUST", "NEU"]),
    )
    assert code == 1


def test_main_returns_0_when_all_schools_present():
    conn = FakeConnection(fetchall_return=[("HUST", "tuition", 3)], fetchone_return=(0,))
    code = verify_corpus.main(
        connection_factory=lambda: conn,
        registry=FakeRegistry(["HUST"]),
    )
    assert code == 0
