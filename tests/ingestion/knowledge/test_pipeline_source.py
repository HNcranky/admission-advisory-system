from ingestion.knowledge.pipeline import KnowledgePipeline
from ingestion.knowledge.registry.models import KnowledgeSource


class FakeDocRepo:
    def __init__(self):
        self.created = []
        self.marked = []
        self._n = 1

    def get_document_by_url(self, url):
        return None

    def get_or_create_document(self, doc):
        self.created.append(doc)
        i = self._n
        self._n += 1
        return i

    def mark_ingested(self, doc_id, content_hash):
        self.marked.append((doc_id, content_hash))


class FakeChunkRepo:
    def __init__(self):
        self.upserts = []

    def get_embeddings_for_hashes(self, hashes):
        return {}

    def delete_chunks_for_document(self, doc_id):
        return 0

    def upsert_chunk(self, chunk):
        self.upserts.append(chunk)
        return len(self.upserts)


class FakeEmbedder:
    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeHtml:
    def __init__(self, body):
        self.raw_content = body
        self.content_hash = "h1"
        self.content_type = "text/html"


_BODY = (
    b"<html><body><nav>MENU</nav>"
    b"<div id='content'>Noi dung chinh cua trang du dai de tao thanh mot chunk hop le.</div>"
    b"<footer>FOOTER</footer></body></html>"
)


def _pipe(doc_repo, chunk_repo, fetch):
    return KnowledgePipeline(registry=None, embedder=FakeEmbedder(),
                             doc_repo=doc_repo, chunk_repo=chunk_repo, fetch=fetch)


def _source(selector):
    return KnowledgeSource(school="MOET", source_url="https://x",
                           document_type="faq", topic="admission_policy",
                           selector=selector)


def test_run_for_source_selector_hit_ingests_region():
    doc_repo, chunk_repo = FakeDocRepo(), FakeChunkRepo()
    pipe = _pipe(doc_repo, chunk_repo, fetch=lambda u: FakeHtml(_BODY))

    result = pipe.run_for_source(_source("#content"))

    assert result.skipped is False
    assert len(chunk_repo.upserts) >= 1
    joined = " ".join(c.chunk_text for c in chunk_repo.upserts)
    assert "Noi dung chinh" in joined
    assert "MENU" not in joined and "FOOTER" not in joined


def test_run_for_source_selector_miss_skips_no_write(caplog):
    doc_repo, chunk_repo = FakeDocRepo(), FakeChunkRepo()
    pipe = _pipe(doc_repo, chunk_repo, fetch=lambda u: FakeHtml(_BODY))

    import logging
    with caplog.at_level(logging.WARNING):
        result = pipe.run_for_source(_source("#nope"))

    assert result.skipped is True
    assert chunk_repo.upserts == []
    assert doc_repo.created == []
    assert doc_repo.marked == []
    assert any("#nope" in r.message for r in caplog.records)
