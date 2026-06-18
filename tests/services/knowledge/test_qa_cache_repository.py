from services.knowledge.qa_cache import QACacheRepository, scope_key_for
from services.knowledge.scope import NATIONAL_SCHOOL


def test_scope_key_for_concrete_topic():
    assert scope_key_for("HUST", "tuition") == "s:HUST|t:tuition"


def test_scope_key_for_null_topic_is_wildcard():
    assert scope_key_for("HUST", None) == "s:HUST|t:*"
    assert scope_key_for("HUST", "") == "s:HUST|t:*"


def test_scope_keys_returns_four_dependency_scopes():
    keys = QACacheRepository.scope_keys("HUST", "tuition")
    assert keys == [
        "s:HUST|t:tuition",
        "s:HUST|t:*",
        f"s:{NATIONAL_SCHOOL}|t:tuition",
        f"s:{NATIONAL_SCHOOL}|t:*",
    ]


class FakeCursor:
    def __init__(self, fetchall_return=None):
        self.statements = []
        self._fetchall = fetchall_return or []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return self._fetchall

    def fetchone(self):
        return None

    def close(self):
        return None


class FakeConnection:
    def __init__(self, fetchall_return=None):
        self.cursor_obj = FakeCursor(fetchall_return)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def _repo(connection):
    return QACacheRepository(connection_factory=lambda: connection)


def test_current_versions_defaults_missing_keys_to_zero():
    # DB knows only s:HUST|t:tuition = 3; the other 3 scopes are absent → 0.
    connection = FakeConnection(fetchall_return=[("s:HUST|t:tuition", 3)])
    repo = _repo(connection)

    versions = repo.current_versions(QACacheRepository.scope_keys("HUST", "tuition"))

    sql, params = connection.cursor_obj.statements[0]
    assert "scope_key = ANY(%s)" in sql
    assert versions == {
        "s:HUST|t:tuition": 3,
        "s:HUST|t:*": 0,
        "s:MOET|t:tuition": 0,
        "s:MOET|t:*": 0,
    }


def test_current_versions_empty_keys_makes_no_query():
    connection = FakeConnection()
    repo = _repo(connection)
    assert repo.current_versions([]) == {}
    assert connection.cursor_obj.statements == []


def test_bump_version_upserts_with_increment():
    connection = FakeConnection()
    repo = _repo(connection)

    repo.bump_version("s:HUST|t:*")

    sql, params = connection.cursor_obj.statements[0]
    assert "INSERT INTO knowledge_qa_cache_version (scope_key)" in sql
    assert "ON CONFLICT (scope_key) DO UPDATE" in sql
    assert "version = knowledge_qa_cache_version.version + 1" in sql
    assert params == ("s:HUST|t:*",)
    assert connection.committed is True
