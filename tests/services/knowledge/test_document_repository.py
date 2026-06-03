from services.knowledge.models import KnowledgeDocument
from services.knowledge.repository import KnowledgeDocumentRepository


class FakeCursor:
    def __init__(self, fetchone_return=None, fetchall_return=None):
        self.statements = []
        self._fetchone = fetchone_return
        self._fetchall = fetchall_return or []
        self.rowcount = 0

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
    return KnowledgeDocumentRepository(connection_factory=lambda: connection)


def test_get_document_by_url_returns_model():
    row = (5, "HUST", "tuition_page", "https://x/t", "abc123", "raw text")
    conn = FakeConnection(fetchone_return=row)
    repo = _repo(conn)

    doc = repo.get_document_by_url("https://x/t")

    sql, params = conn.cursor_obj.statements[0]
    assert "FROM knowledge_documents" in sql
    assert "WHERE source_url = %s" in sql
    assert params == ("https://x/t",)
    assert doc.id == 5
    assert doc.content_hash == "abc123"
    assert doc.school == "HUST"


def test_get_document_by_url_returns_none_when_absent():
    conn = FakeConnection(fetchone_return=None)
    assert _repo(conn).get_document_by_url("https://nope") is None


def test_get_or_create_document_uses_on_conflict_and_omits_content_hash():
    conn = FakeConnection(fetchone_return=(9,))
    repo = _repo(conn)

    doc_id = repo.get_or_create_document(KnowledgeDocument(
        school="NEU", document_type="tuition_page",
        source_url="https://neu/t", raw_text="body",
    ))

    sql, params = conn.cursor_obj.statements[0]
    assert doc_id == 9
    assert "INSERT INTO knowledge_documents" in sql
    assert "ON CONFLICT (source_url) DO UPDATE" in sql
    # content_hash is intentionally NOT written here (set by mark_ingested)
    assert "content_hash" not in sql
    assert params == ("NEU", "tuition_page", "https://neu/t", "body")
    assert conn.committed is True


def test_mark_ingested_updates_hash_for_id():
    conn = FakeConnection()
    repo = _repo(conn)

    repo.mark_ingested(9, "deadbeef")

    sql, params = conn.cursor_obj.statements[0]
    assert "UPDATE knowledge_documents" in sql
    assert "SET content_hash = %s" in sql
    assert "WHERE id = %s" in sql
    assert params == ("deadbeef", 9)
    assert conn.committed is True
