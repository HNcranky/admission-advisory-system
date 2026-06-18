from services.knowledge.qa_cache import CachedAnswer, QACacheRepository


class ScriptedCursor:
    """Returns queued results per execute() call, in order.

    Each entry is a dict: {"one": <fetchone result>, "all": <fetchall result>}.
    lookup() issues the candidate query (fetchone) first, then — only on a
    threshold pass — the version query (fetchall).
    """

    def __init__(self, results):
        self._results = list(results)
        self._i = -1
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        self._i += 1

    def fetchone(self):
        return self._results[self._i].get("one")

    def fetchall(self):
        return self._results[self._i].get("all", [])

    def close(self):
        return None


class ScriptedConnection:
    def __init__(self, results):
        self.cursor_obj = ScriptedCursor(results)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def _repo(results):
    conn = ScriptedConnection(results)
    return QACacheRepository(connection_factory=lambda: conn), conn


# scope_keys("HUST", "tuition") in order:
_KEYS = QACacheRepository.scope_keys("HUST", "tuition")
_ANSWER_JSON = {
    "answer": "Học phí 35 triệu",
    "citations": [{"source_url": "http://u", "chunk_text": "đoạn"}],
    "confidence": 0.91,
}
_FRESH_VERSIONS = {k: 1 for k in _KEYS}


def test_lookup_no_candidate_returns_none():
    repo, conn = _repo([{"one": None}])
    assert repo.lookup([0.1, 0.2], "HUST", "tuition", threshold=0.95) is None
    # candidate query only — no version query when there is no row
    sql, _ = conn.cursor_obj.statements[0]
    assert "FROM knowledge_qa_cache" in sql
    assert "ORDER BY embedding <=> %s::vector" in sql
    assert "expires_at > NOW()" in sql
    assert len(conn.cursor_obj.statements) == 1


def test_lookup_below_threshold_returns_none():
    # candidate row present but cosine score 0.80 < threshold 0.95
    repo, conn = _repo([{"one": (_ANSWER_JSON, 0.91, _FRESH_VERSIONS, 0.80)}])
    assert repo.lookup([0.1, 0.2], "HUST", "tuition", threshold=0.95) is None
    assert len(conn.cursor_obj.statements) == 1   # short-circuits before versions


def test_lookup_version_mismatch_returns_none():
    # score passes; stored versions are all 1, but the DB now reports none → 0
    repo, conn = _repo([
        {"one": (_ANSWER_JSON, 0.91, _FRESH_VERSIONS, 0.99)},
        {"all": []},   # current_versions → every scope 0 → mismatch
    ])
    assert repo.lookup([0.1, 0.2], "HUST", "tuition", threshold=0.95) is None
    assert len(conn.cursor_obj.statements) == 2


def test_lookup_hit_returns_cached_answer():
    repo, conn = _repo([
        {"one": (_ANSWER_JSON, 0.91, _FRESH_VERSIONS, 0.99)},
        {"all": [(k, 1) for k in _KEYS]},   # current == stored → hit
    ])
    hit = repo.lookup([0.1, 0.2], "HUST", "tuition", threshold=0.95)
    assert isinstance(hit, CachedAnswer)
    assert hit.answer == "Học phí 35 triệu"
    assert hit.confidence == 0.91
    assert hit.citations[0].source_url == "http://u"
    assert hit.citations[0].chunk_text == "đoạn"
