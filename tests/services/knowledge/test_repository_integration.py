import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG, EMBEDDING_DIM
from services.knowledge.models import KnowledgeChunk
from services.knowledge.repository import KnowledgeChunkRepository

pytestmark = pytest.mark.integration


def _vec(*head):
    """A full-dimension embedding: `head` values followed by zero padding."""
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


@pytest.fixture
def knowledge_repo():
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=2)
    except psycopg2.OperationalError:
        pytest.skip(
            "Postgres not reachable; run "
            "`docker compose up -d db && python -m db.setup_db` first."
        )
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE knowledge_chunks, knowledge_documents RESTART IDENTITY CASCADE"
        )
    conn.commit()
    conn.close()
    return KnowledgeChunkRepository()


def test_upsert_then_vector_search_round_trip(knowledge_repo):
    a = KnowledgeChunk(
        school="VNU-UET", topic="tuition", chunk_text="A",
        embedding=_vec(1.0, 0.0), source_url="http://x/a",
        span_start=0, span_end=1,
    )
    b = KnowledgeChunk(
        school="VNU-UET", topic="tuition", chunk_text="B",
        embedding=_vec(0.0, 1.0), source_url="http://x/b",
        span_start=0, span_end=1,
    )
    id_a = knowledge_repo.upsert_chunk(a)
    id_b = knowledge_repo.upsert_chunk(b)
    assert id_a != id_b

    results = knowledge_repo.vector_search(
        _vec(0.9, 0.1), school="VNU-UET", topic="tuition", limit=2
    )
    assert [r.source_url for r in results] == ["http://x/a", "http://x/b"]
    assert results[0].score >= results[1].score


def test_upsert_is_idempotent_on_source_url_span(knowledge_repo):
    chunk = KnowledgeChunk(
        school="HUST", topic="curriculum", chunk_text="v1",
        embedding=_vec(1.0), source_url="http://x/c",
        span_start=0, span_end=5,
    )
    first = knowledge_repo.upsert_chunk(chunk)
    chunk.chunk_text = "v2"
    second = knowledge_repo.upsert_chunk(chunk)
    assert first == second  # same row updated, not duplicated

    rows = knowledge_repo.search_by_metadata("HUST", topic="curriculum")
    assert len(rows) == 1
    assert rows[0].chunk_text == "v2"
