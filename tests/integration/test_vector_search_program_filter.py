import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG
from services.knowledge.models import KnowledgeChunk
from services.knowledge.repository import KnowledgeChunkRepository

pytestmark = pytest.mark.integration

DIM = 768


def _conn():
    return psycopg2.connect(**DB_CONFIG)


@pytest.fixture
def repo(db_available):
    r = KnowledgeChunkRepository(connection_factory=_conn)
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE school = 'TESTU'")
        c.commit()
    yield r
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE school = 'TESTU'")
        c.commit()


def _seed(repo, program, url):
    repo.upsert_chunk(KnowledgeChunk(
        knowledge_document_id=None, school="TESTU", program=program, year=None,
        document_type=None, topic="program_overview",
        chunk_text=f"{program} nội dung", content_hash=None,
        embedding=[0.1] * DIM, source_url=url, span_start=0, span_end=5,
    ))


def test_program_filter_restricts_results(repo):
    _seed(repo, "Kỹ thuật Ô tô", "https://t/a")
    _seed(repo, "Khoa học Máy tính", "https://t/b")
    rows = repo.vector_search([0.1] * DIM, school="TESTU",
                              topic="program_overview", program="Kỹ thuật Ô tô")
    assert rows, "expected at least one match"
    assert {r.program for r in rows} == {"Kỹ thuật Ô tô"}


def test_no_program_returns_all(repo):
    _seed(repo, "Kỹ thuật Ô tô", "https://t/a")
    _seed(repo, "Khoa học Máy tính", "https://t/b")
    rows = repo.vector_search([0.1] * DIM, school="TESTU",
                              topic="program_overview", program=None)
    assert {r.program for r in rows} == {"Kỹ thuật Ô tô", "Khoa học Máy tính"}
