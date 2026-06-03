import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG, EMBEDDING_DIM
from services.knowledge.models import KnowledgeChunk, KnowledgeDocument
from services.knowledge.repository import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
    chunk_content_hash,
)

pytestmark = pytest.mark.integration


def _vec(*head):
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


@pytest.fixture
def repos():
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
    return KnowledgeDocumentRepository(), KnowledgeChunkRepository()


def test_document_create_chunks_reuse_map_delete_and_mark(repos):
    doc_repo, chunk_repo = repos

    doc_id = doc_repo.get_or_create_document(KnowledgeDocument(
        school="VNU-UET", document_type="tuition_page",
        source_url="https://x/t", raw_text="body",
    ))
    # get_or_create is idempotent on source_url → same id
    assert doc_repo.get_or_create_document(KnowledgeDocument(
        school="VNU-UET", document_type="tuition_page",
        source_url="https://x/t", raw_text="body2",
    )) == doc_id

    chunk_repo.upsert_chunk(KnowledgeChunk(
        knowledge_document_id=doc_id, school="VNU-UET", topic="tuition",
        chunk_text="Học phí", embedding=_vec(1.0, 0.0),
        source_url="https://x/t", span_start=0, span_end=7,
    ))

    mapping = chunk_repo.get_embedding_map_for_document(doc_id)
    key = chunk_content_hash("Học phí")
    assert key in mapping
    assert mapping[key][0] == 1.0

    assert chunk_repo.delete_chunks_for_document(doc_id) == 1
    assert chunk_repo.get_embedding_map_for_document(doc_id) == {}

    # content_hash is None until mark_ingested
    assert doc_repo.get_document_by_url("https://x/t").content_hash is None
    doc_repo.mark_ingested(doc_id, "hash-final")
    assert doc_repo.get_document_by_url("https://x/t").content_hash == "hash-final"
