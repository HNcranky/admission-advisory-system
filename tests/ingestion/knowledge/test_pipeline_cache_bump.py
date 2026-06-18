import ingestion.knowledge.pipeline as pipeline_mod
from ingestion.knowledge.local_metadata import ResolvedMetadata
from ingestion.knowledge.pdf_ocr import HybridPage, HybridPagesResult
from ingestion.knowledge.pipeline import KnowledgePipeline
from ingestion.knowledge.registry.models import KnowledgeSource
from services.knowledge.models import KnowledgeDocument


class FakeDocRepo:
    def __init__(self, existing_by_url=None):
        self.existing_by_url = existing_by_url or {}
        self.marked = []
        self._n = 1

    def get_document_by_url(self, url):
        return self.existing_by_url.get(url)

    def get_or_create_document(self, doc):
        i = self._n
        self._n += 1
        return i

    def mark_ingested(self, doc_id, content_hash):
        self.marked.append((doc_id, content_hash))


class FakeChunkRepo:
    def get_embeddings_for_hashes(self, hashes):
        return {}

    def delete_chunks_for_document(self, doc_id):
        return 0

    def upsert_chunk(self, chunk):
        return 1


class FakeEmbedder:
    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeCacheRepo:
    def __init__(self, raises=False):
        self.bumps = []
        self._raises = raises

    def bump_version(self, scope_key):
        self.bumps.append(scope_key)
        if self._raises:
            raise RuntimeError("cache down")


class FakeHtml:
    def __init__(self, content_hash="h1"):
        self.raw_content = (
            b"<html><body><div>Noi dung chinh cua trang du dai de tao thanh "
            b"mot chunk hop le va du tu.</div></body></html>"
        )
        self.content_hash = content_hash
        self.content_type = "text/html"


class FakeFetchResult:
    def __init__(self, content=b"%PDF-x", content_hash="h1",
                 content_type="application/pdf"):
        self.raw_content = content
        self.content_hash = content_hash
        self.content_type = content_type


def _classify(school="HUST", year=2026):
    def classify(first_pages_text, filename, overrides):
        return ResolvedMetadata(school=school, year=year)
    return classify


def _patch_hybrid(monkeypatch):
    page = HybridPage(1, "Nội dung trang một đủ dài để thành một chunk.", "text_layer")
    result = HybridPagesResult(pages=[page], pages_text=1, pages_ocr=0, pages_failed=0)
    monkeypatch.setattr(pipeline_mod, "extract_pages_hybrid", lambda content, ocr: result)


def _pipe(cache, doc_repo=None, chunk_repo=None, fetch=None):
    return KnowledgePipeline(
        registry=None, embedder=FakeEmbedder(),
        doc_repo=doc_repo or FakeDocRepo(),
        chunk_repo=chunk_repo or FakeChunkRepo(),
        fetch=fetch, cache_repo=cache,
    )


def test_bump_cache_uses_topic_key():
    cache = FakeCacheRepo()
    _pipe(cache)._bump_cache("HUST", "tuition")
    assert cache.bumps == ["s:HUST|t:tuition"]


def test_bump_cache_null_topic_is_wildcard():
    cache = FakeCacheRepo()
    _pipe(cache)._bump_cache("HUST", None)
    assert cache.bumps == ["s:HUST|t:*"]


def test_bump_cache_failure_is_swallowed():
    cache = FakeCacheRepo(raises=True)
    _pipe(cache)._bump_cache("HUST", "tuition")   # must not raise
    assert cache.bumps == ["s:HUST|t:tuition"]


def test_run_for_source_bumps_topic_scope():
    cache = FakeCacheRepo()
    source = KnowledgeSource(school="MOET", source_url="https://x",
                             document_type="faq", topic="admission_policy",
                             selector=None)
    pipe = _pipe(cache, fetch=lambda u: FakeHtml())
    pipe.run_for_source(source)
    assert cache.bumps == ["s:MOET|t:admission_policy"]


def test_run_for_source_skip_unchanged_does_not_bump():
    cache = FakeCacheRepo()
    url = "https://x"
    existing = KnowledgeDocument(school="MOET", document_type="faq",
                                 source_url=url, content_hash="h1", raw_text="cũ")
    source = KnowledgeSource(school="MOET", source_url=url, document_type="faq",
                             topic="admission_policy", selector=None)
    pipe = _pipe(cache, doc_repo=FakeDocRepo({url: existing}),
                 fetch=lambda u: FakeHtml(content_hash="h1"))
    result = pipe.run_for_source(source)
    assert result.skipped is True
    assert cache.bumps == []


def test_run_for_url_bumps_wildcard_scope(monkeypatch):
    _patch_hybrid(monkeypatch)
    cache = FakeCacheRepo()
    pipe = _pipe(cache, fetch=lambda u: FakeFetchResult(content_hash="h1"))
    pipe.run_for_url("https://hust.edu.vn/de-an.pdf", school="HUST",
                     ocr=lambda png: "x", classify=_classify())
    assert cache.bumps == ["s:HUST|t:*"]


def test_run_for_local_file_bumps_wildcard_scope(tmp_path, monkeypatch):
    _patch_hybrid(monkeypatch)
    folder = tmp_path / "pdf_text"
    folder.mkdir()
    pdf = folder / "de-an.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    cache = FakeCacheRepo()
    pipe = _pipe(cache)
    pipe.run_for_local_file(pdf, tmp_path, overrides={}, ocr=lambda png: "x",
                            classify=_classify(school="HUST", year=2026))
    assert cache.bumps == ["s:HUST|t:*"]
