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
    # Defense in depth: never TRUNCATE outside the isolated test database.
    assert DB_CONFIG["database"].endswith("_test"), (
        f"refusing to truncate {DB_CONFIG['database']!r}"
    )
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


def test_vector_search_includes_null_topic_excludes_other_topics(knowledge_repo):
    web_tuition = KnowledgeChunk(
        school="HUST", topic="tuition", chunk_text="học phí web",
        embedding=_vec(1.0, 0.0), source_url="http://x/tuition",
        span_start=0, span_end=1,
    )
    local_pdf = KnowledgeChunk(
        school="HUST", topic=None, chunk_text="quy chế pdf",
        embedding=_vec(0.9, 0.1), source_url="file:///d/quy-che-2026.pdf",
        span_start=0, span_end=1,
    )
    web_dorm = KnowledgeChunk(
        school="HUST", topic="dormitory", chunk_text="ký túc xá web",
        embedding=_vec(0.8, 0.2), source_url="http://x/dorm",
        span_start=0, span_end=1,
    )
    for chunk in (web_tuition, local_pdf, web_dorm):
        knowledge_repo.upsert_chunk(chunk)

    results = knowledge_repo.vector_search(
        _vec(1.0, 0.0), school="HUST", topic="tuition", limit=10
    )

    urls = {r.source_url for r in results}
    assert "http://x/tuition" in urls                  # đúng topic: giữ
    assert "file:///d/quy-che-2026.pdf" in urls        # NULL topic: wildcard
    assert "http://x/dorm" not in urls                 # topic khác: vẫn bị loại
