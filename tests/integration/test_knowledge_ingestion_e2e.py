from dataclasses import dataclass

import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG, EMBEDDING_DIM
from ingestion.knowledge.pipeline import KnowledgePipeline
from ingestion.knowledge.registry.models import KnowledgeSource
from services.knowledge.repository import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
)

pytestmark = pytest.mark.integration

HTML = b"<html><body><p>HELLO WORLD</p></body></html>"


@dataclass
class FakeFetchResult:
    content_hash: str
    content_type: str
    raw_content: bytes


class FakeEmbedder:
    """Deterministic full-dimension vectors; no API key, no network."""
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in texts]


@pytest.fixture
def clean_knowledge_db():
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


def test_ingest_then_rerun_is_idempotent(clean_knowledge_db):
    source = KnowledgeSource(
        school="HUST", source_url="https://x/t",
        document_type="tuition_page", topic="tuition",
    )
    embedder = FakeEmbedder()
    fetch = lambda url: FakeFetchResult("HASH-1", "text/html", HTML)
    pipe = KnowledgePipeline(
        registry=None, embedder=embedder,
        doc_repo=KnowledgeDocumentRepository(),
        chunk_repo=KnowledgeChunkRepository(),
        fetch=fetch,
    )

    first = pipe.run_for_source(source)
    assert first.skipped is False
    assert first.chunks_total >= 1
    assert first.chunks_embedded == first.chunks_total
    assert len(embedder.calls) == 1

    # Re-run with identical content → content_hash gate skips everything.
    second = pipe.run_for_source(source)
    assert second.skipped is True
    assert len(embedder.calls) == 1   # embedder NOT called again

    # Corpus has exactly the first run's chunks (no duplicates).
    rows = KnowledgeChunkRepository().search_by_metadata("HUST", topic="tuition")
    assert len(rows) == first.chunks_total
