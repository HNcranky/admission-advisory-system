import pytest

from ingestion.knowledge.pipeline import KnowledgePipeline
from ingestion.knowledge.registry.models import KnowledgeSource
from services.knowledge.models import Citation, KnowledgeDocument, KnowledgeQAResult
from services.knowledge.qa_cache import QACacheRepository

pytestmark = pytest.mark.integration

_SCHOOL, _TOPIC = "ITEST", "admission_policy"


class _FakeDocRepo:
    def __init__(self):
        self.marked = []
        self._n = 1

    def get_document_by_url(self, url):
        return None

    def get_or_create_document(self, doc):
        i = self._n
        self._n += 1
        return i

    def mark_ingested(self, doc_id, content_hash):
        self.marked.append((doc_id, content_hash))


class _FakeChunkRepo:
    def get_embeddings_for_hashes(self, hashes):
        return {}

    def delete_chunks_for_document(self, doc_id):
        return 0

    def upsert_chunk(self, chunk):
        return 1


class _FakeEmbedder:
    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeHtml:
    raw_content = (
        b"<html><body><div>Noi dung chinh du dai de tao thanh mot chunk "
        b"hop le va du tu de chunk.</div></body></html>"
    )
    content_hash = "newhash"
    content_type = "text/html"


def test_run_for_source_invalidates_cached_answer(db_available, qa_cache_clean):
    cache = QACacheRepository()
    vec = [0.1] * 768

    # A fresh, version-stamped cached answer for (ITEST, admission_policy).
    dep = cache.current_versions(cache.scope_keys(_SCHOOL, _TOPIC))
    result = KnowledgeQAResult(
        has_data=True, answer="cached answer",
        citations=[Citation(source_url="http://itest/x", chunk_text="t")],
        confidence=0.9,
    )
    cache.store(_SCHOOL, _TOPIC, "q", vec, result, dep, ttl_days=30)
    assert cache.lookup(vec, _SCHOOL, _TOPIC, threshold=0.5) is not None

    # Ingest a new doc into the same (school, topic) scope.
    pipe = KnowledgePipeline(
        registry=None, embedder=_FakeEmbedder(),
        doc_repo=_FakeDocRepo(), chunk_repo=_FakeChunkRepo(),
        fetch=lambda u: _FakeHtml(), cache_repo=cache,
    )
    source = KnowledgeSource(
        school=_SCHOOL, source_url="https://itest/new",
        document_type="faq", topic=_TOPIC, selector=None,
    )
    pipe.run_for_source(source)

    # The bump made the cached row stale → lookup now misses.
    assert cache.lookup(vec, _SCHOOL, _TOPIC, threshold=0.5) is None
