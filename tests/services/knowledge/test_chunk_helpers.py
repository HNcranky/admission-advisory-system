import hashlib

from services.knowledge.repository import (
    KnowledgeChunkRepository,
    chunk_content_hash,
)


class FakeCursor:
    def __init__(self, fetchall_return=None):
        self.statements = []
        self._fetchall = fetchall_return or []
        self.rowcount = len(self._fetchall)

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return self._fetchall

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
    return KnowledgeChunkRepository(connection_factory=lambda: connection)


def test_chunk_content_hash_is_sha256_of_utf8_text():
    text = "Học phí 2026"
    assert chunk_content_hash(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_get_embedding_map_keys_by_hash_and_parses_vector():
    rows = [("Học phí 2026", "[0.1,0.2,0.3]")]
    conn = FakeConnection(fetchall_return=rows)
    repo = _repo(conn)

    mapping = repo.get_embedding_map_for_document(7)

    sql, params = conn.cursor_obj.statements[0]
    assert "FROM knowledge_chunks" in sql
    assert "WHERE knowledge_document_id = %s" in sql
    assert "embedding IS NOT NULL" in sql
    assert params == (7,)
    key = chunk_content_hash("Học phí 2026")
    assert mapping[key] == [0.1, 0.2, 0.3]


def test_delete_chunks_for_document_runs_delete_and_commits():
    conn = FakeConnection()
    conn.cursor_obj.rowcount = 4
    repo = _repo(conn)

    deleted = repo.delete_chunks_for_document(7)

    sql, params = conn.cursor_obj.statements[0]
    assert "DELETE FROM knowledge_chunks" in sql
    assert "WHERE knowledge_document_id = %s" in sql
    assert params == (7,)
    assert deleted == 4
    assert conn.committed is True
