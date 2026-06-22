import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG
from services.knowledge.models import KnowledgeChunk
from services.knowledge.repository import KnowledgeChunkRepository

pytestmark = pytest.mark.integration


def _conn():
    return psycopg2.connect(**DB_CONFIG)


@pytest.fixture
def repo(db_available):
    r = KnowledgeChunkRepository(connection_factory=_conn)
    # Clean slate for this test's program labels.
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE school = 'TESTU'")
        c.commit()
    yield r
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE school = 'TESTU'")
        c.commit()


def _seed(repo, program, school="TESTU", url=None):
    repo.upsert_chunk(KnowledgeChunk(
        knowledge_document_id=None, school=school, program=program, year=None,
        document_type=None, topic="program_overview",
        chunk_text=f"{program} nội dung", content_hash=None, embedding=None,
        source_url=url or f"https://t/{program}", span_start=0, span_end=5,
    ))


def test_resolves_program_named_in_question(repo):
    _seed(repo, "Kỹ thuật Ô tô")
    _seed(repo, "Khoa học Máy tính")
    assert repo.resolve_program("cơ hội việc làm ngành Kỹ thuật Ô tô", "TESTU") \
        == "Kỹ thuật Ô tô"


def test_returns_none_when_no_program_named(repo):
    _seed(repo, "Kỹ thuật Ô tô")
    assert repo.resolve_program("phương thức xét tuyển của trường", "TESTU") is None


def test_scoped_by_school(repo):
    _seed(repo, "Kỹ thuật Ô tô", school="TESTU")
    # Same name under another school must not leak when school is given.
    assert repo.resolve_program("ngành Kỹ thuật Ô tô", "OTHERU") is None


def test_empty_question_returns_none(repo):
    _seed(repo, "Kỹ thuật Ô tô")
    assert repo.resolve_program("", "TESTU") is None
