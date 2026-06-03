from dataclasses import dataclass

from ingestion.knowledge.pipeline import KnowledgePipeline, KnowledgeIngestResult
from ingestion.knowledge.registry.models import KnowledgeSource
from services.knowledge.models import KnowledgeDocument
from services.knowledge.repository import chunk_content_hash

# HTML whose extracted text is exactly "HELLO WORLD" (body fallback, one block).
HTML = b"<html><body><p>HELLO WORLD</p></body></html>"
EXPECTED_CHUNK = "HELLO WORLD"


@dataclass
class FakeFetchResult:
    content_hash: str
    content_type: str
    raw_content: bytes


def make_fetch(result):
    def _fetch(url):
        return result
    return _fetch


class FakeDocRepo:
    def __init__(self, existing=None, doc_id=1):
        self.existing = existing
        self.doc_id = doc_id
        self.marked = []

    def get_document_by_url(self, url):
        return self.existing

    def get_or_create_document(self, doc):
        return self.doc_id

    def mark_ingested(self, doc_id, content_hash):
        self.marked.append((doc_id, content_hash))


class FakeChunkRepo:
    def __init__(self, reuse_map=None):
        self.reuse_map = reuse_map or {}
        self.events = []
        self.upserts = []

    def get_embeddings_for_hashes(self, hashes):
        self.events.append("map")
        self.queried_hashes = list(hashes)
        return dict(self.reuse_map)

    def delete_chunks_for_document(self, doc_id):
        self.events.append("delete")
        return 0

    def upsert_chunk(self, chunk):
        self.events.append("upsert")
        self.upserts.append(chunk)
        return len(self.upserts)


class FakeEmbedder:
    def __init__(self, dim=3):
        self.dim = dim
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0] + [0.0] * (self.dim - 1) for _ in texts]


SOURCE = KnowledgeSource(
    school="HUST", source_url="https://x/t",
    document_type="tuition_page", topic="tuition",
)


def _pipeline(doc_repo, chunk_repo, embedder, content_hash="H1"):
    fetch = make_fetch(FakeFetchResult(content_hash, "text/html", HTML))
    return KnowledgePipeline(
        registry=None, embedder=embedder,
        doc_repo=doc_repo, chunk_repo=chunk_repo, fetch=fetch,
    )


def test_unchanged_document_is_skipped_without_embedding():
    existing = KnowledgeDocument(
        school="HUST", document_type="tuition_page",
        source_url="https://x/t", content_hash="H1",
    )
    doc_repo, chunk_repo, embedder = FakeDocRepo(existing), FakeChunkRepo(), FakeEmbedder()

    result = _pipeline(doc_repo, chunk_repo, embedder, content_hash="H1").run_for_source(SOURCE)

    assert result == KnowledgeIngestResult(source_url="https://x/t", skipped=True)
    assert embedder.calls == []          # no embedding work
    assert chunk_repo.events == []        # no chunk work
    assert doc_repo.marked == []


def test_new_document_embeds_all_chunks_then_marks_ingested():
    doc_repo, chunk_repo, embedder = FakeDocRepo(existing=None), FakeChunkRepo(), FakeEmbedder()

    result = _pipeline(doc_repo, chunk_repo, embedder, content_hash="H9").run_for_source(SOURCE)

    assert result.skipped is False
    assert result.chunks_total == 1
    assert result.chunks_embedded == 1
    assert result.chunks_reused == 0
    assert embedder.calls == [[EXPECTED_CHUNK]]
    assert len(chunk_repo.upserts) == 1
    assert chunk_repo.upserts[0].chunk_text == EXPECTED_CHUNK
    assert chunk_repo.upserts[0].knowledge_document_id == 1
    assert chunk_repo.upserts[0].topic == "tuition"
    assert doc_repo.marked == [(1, "H9")]                 # content_hash written LAST


def test_changed_document_reuses_matching_chunk_embedding():
    existing = KnowledgeDocument(
        school="HUST", document_type="tuition_page",
        source_url="https://x/t", content_hash="OLD",
    )
    reuse = {chunk_content_hash(EXPECTED_CHUNK): [0.5, 0.5, 0.5]}
    doc_repo, chunk_repo, embedder = FakeDocRepo(existing), FakeChunkRepo(reuse), FakeEmbedder()

    result = _pipeline(doc_repo, chunk_repo, embedder, content_hash="NEW").run_for_source(SOURCE)

    assert result.chunks_reused == 1
    assert result.chunks_embedded == 0
    assert embedder.calls == []                           # reused, not re-embedded
    assert chunk_repo.upserts[0].embedding == [0.5, 0.5, 0.5]


def test_cross_document_reuse_keys_lookup_by_chunk_hash():
    """Reuse map is fetched by chunk hashes (corpus-wide), and a hash present
    from any document supplies the embedding without re-embedding."""
    reuse = {chunk_content_hash(EXPECTED_CHUNK): [0.9, 0.1, 0.0]}
    doc_repo, chunk_repo, embedder = FakeDocRepo(existing=None), FakeChunkRepo(reuse), FakeEmbedder()

    result = _pipeline(doc_repo, chunk_repo, embedder, content_hash="NEW").run_for_source(SOURCE)

    assert chunk_repo.queried_hashes == [chunk_content_hash(EXPECTED_CHUNK)]
    assert result.chunks_reused == 1
    assert embedder.calls == []
    assert chunk_repo.upserts[0].embedding == [0.9, 0.1, 0.0]


def test_upserted_chunk_carries_its_content_hash():
    doc_repo, chunk_repo, embedder = FakeDocRepo(existing=None), FakeChunkRepo(), FakeEmbedder()

    _pipeline(doc_repo, chunk_repo, embedder).run_for_source(SOURCE)

    upserted = chunk_repo.upserts[0]
    assert upserted.content_hash == chunk_content_hash(upserted.chunk_text)


def test_old_chunks_deleted_before_new_upserts():
    doc_repo, chunk_repo, embedder = FakeDocRepo(existing=None), FakeChunkRepo(), FakeEmbedder()

    _pipeline(doc_repo, chunk_repo, embedder).run_for_source(SOURCE)

    # reuse map read first, delete before any upsert
    assert chunk_repo.events[0] == "map"
    assert chunk_repo.events.index("delete") < chunk_repo.events.index("upsert")


def test_pdf_content_type_uses_page_extraction(monkeypatch):
    import ingestion.knowledge.pipeline as pipeline_mod

    calls = {}

    def fake_extract_pages(content):
        calls["extract"] = content
        return [(1, "PDF BODY")]

    def fake_marked(pages):
        calls["marked"] = pages
        return "[Trang 1]\nPDF BODY"

    monkeypatch.setattr(pipeline_mod, "extract_pages", fake_extract_pages)
    monkeypatch.setattr(pipeline_mod, "pages_to_marked_text", fake_marked)

    doc_repo, chunk_repo, embedder = FakeDocRepo(existing=None), FakeChunkRepo(), FakeEmbedder()
    fetch = make_fetch(FakeFetchResult("H1", "application/pdf", b"%PDF-bytes"))
    pipe = KnowledgePipeline(registry=None, embedder=embedder,
                             doc_repo=doc_repo, chunk_repo=chunk_repo, fetch=fetch)

    pipe.run_for_source(SOURCE)

    assert calls["extract"] == b"%PDF-bytes"          # PDF path taken, not parse_html
    assert chunk_repo.upserts[0].chunk_text.startswith("[Trang 1]")
