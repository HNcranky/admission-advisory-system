from services.knowledge.models import KnowledgeChunk
from services.knowledge.repository import KnowledgeChunkRepository


class FakeCursor:
    def __init__(self, fetchone_return=None, fetchall_return=None):
        self.statements = []
        self._fetchone = fetchone_return
        self._fetchall = fetchall_return or []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall

    def close(self):
        return None


class FakeConnection:
    def __init__(self, fetchone_return=None, fetchall_return=None):
        self.cursor_obj = FakeCursor(fetchone_return, fetchall_return)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def _repo(connection):
    return KnowledgeChunkRepository(connection_factory=lambda: connection)


def test_upsert_chunk_inserts_with_on_conflict_and_returns_id():
    connection = FakeConnection(fetchone_return=(42,))
    repo = _repo(connection)

    chunk = KnowledgeChunk(
        school="VNU-UET",
        topic="tuition",
        chunk_text="Học phí năm 2024 là ...",
        embedding=[0.1, 0.2, 0.3],
        source_url="http://uet/tuition",
        span_start=0,
        span_end=120,
    )
    chunk_id = repo.upsert_chunk(chunk)

    sql, params = connection.cursor_obj.statements[0]
    assert chunk_id == 42
    assert "INSERT INTO knowledge_chunks" in sql
    assert "ON CONFLICT (source_url, span_start, span_end) DO UPDATE" in sql
    assert "%s::vector" in sql
    # embedding is passed as a pgvector text literal, not a Python list
    assert "[0.1,0.2,0.3]" in params
    assert connection.committed is True


def test_upsert_chunk_passes_null_embedding_as_none():
    connection = FakeConnection(fetchone_return=(7,))
    repo = _repo(connection)

    repo.upsert_chunk(KnowledgeChunk(school="HUST", chunk_text="no embedding yet"))

    _, params = connection.cursor_obj.statements[0]
    assert None in params  # embedding literal is None → SQL NULL::vector


def test_upsert_chunk_persists_content_hash():
    connection = FakeConnection(fetchone_return=(1,))
    repo = _repo(connection)

    repo.upsert_chunk(KnowledgeChunk(
        school="HUST", chunk_text="x", content_hash="deadbeef",
        source_url="u", span_start=0, span_end=1,
    ))

    sql, params = connection.cursor_obj.statements[0]
    assert "content_hash" in sql
    assert "content_hash  = EXCLUDED.content_hash" in sql  # also updated on conflict
    assert "deadbeef" in params


def test_get_embeddings_for_hashes_returns_map_keyed_by_hash():
    rows = [("h1", "[1.0,0.0]"), ("h2", "[0.0,1.0]")]
    connection = FakeConnection(fetchall_return=rows)
    repo = _repo(connection)

    result = repo.get_embeddings_for_hashes(["h1", "h2"])

    sql, params = connection.cursor_obj.statements[0]
    assert "content_hash = ANY(%s)" in sql
    assert "embedding IS NOT NULL" in sql
    assert result == {"h1": [1.0, 0.0], "h2": [0.0, 1.0]}


def test_get_embeddings_for_hashes_empty_makes_no_query():
    connection = FakeConnection()
    repo = _repo(connection)

    assert repo.get_embeddings_for_hashes([]) == {}
    assert connection.cursor_obj.statements == []


def _chunk_row(id=1, school="VNU-UET", topic="tuition"):
    # Column order: id, knowledge_document_id, school, program, year,
    # document_type, topic, chunk_text, content_hash, source_url, span_start, span_end
    return (id, None, school, None, None, "tuition_page", topic,
            "chunk text", "hashabc", "http://uet/tuition", 0, 120)


def test_search_by_metadata_filters_school_only_when_topic_omitted():
    connection = FakeConnection(fetchall_return=[_chunk_row()])
    repo = _repo(connection)

    results = repo.search_by_metadata("VNU-UET")

    sql, params = connection.cursor_obj.statements[0]
    assert "WHERE school = %s" in sql
    assert "topic = %s" not in sql
    assert params == ("VNU-UET", 20)            # default limit
    assert results[0].school == "VNU-UET"
    assert results[0].chunk_text == "chunk text"


def test_search_by_metadata_adds_topic_clause_when_given():
    connection = FakeConnection(fetchall_return=[_chunk_row()])
    repo = _repo(connection)

    repo.search_by_metadata("VNU-UET", topic="tuition", limit=5)

    sql, params = connection.cursor_obj.statements[0]
    assert "WHERE school = %s" in sql
    assert "AND topic = %s" in sql
    assert params == ("VNU-UET", "tuition", 5)


def _scored_row(id=1, source_url="http://uet/tuition", score=0.91):
    # _chunk_row columns + trailing score; source_url now at index 9 (after content_hash)
    return _chunk_row(id=id)[:9] + (source_url,) + _chunk_row(id=id)[10:] + (score,)


def test_vector_search_builds_cosine_query_with_filters():
    connection = FakeConnection(
        fetchall_return=[_scored_row(id=1, source_url="http://uet/a", score=0.9)]
    )
    repo = _repo(connection)

    results = repo.vector_search([0.1, 0.2], school="VNU-UET", topic="tuition", limit=3)

    sql, params = connection.cursor_obj.statements[0]
    assert "1 - (embedding <=> %s::vector) AS score" in sql
    assert "ORDER BY embedding <=> %s::vector" in sql
    assert "embedding IS NOT NULL" in sql
    assert "AND school = %s" in sql
    assert "AND topic = %s" in sql
    # literal appears twice (SELECT score + ORDER BY), filters between, limit last
    assert params == ("[0.1,0.2]", "VNU-UET", "tuition", "[0.1,0.2]", 3)
    assert results[0].score == 0.9
    assert results[0].source_url == "http://uet/a"


def test_vector_search_without_filters_omits_metadata_clauses():
    connection = FakeConnection(fetchall_return=[])
    repo = _repo(connection)

    repo.vector_search([1.0, 0.0])

    sql, params = connection.cursor_obj.statements[0]
    assert "school = %s" not in sql
    assert "topic = %s" not in sql
    assert params == ("[1.0,0.0]", "[1.0,0.0]", 5)   # default limit
