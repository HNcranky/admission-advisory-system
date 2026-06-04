import ingestion.knowledge.pipeline as pipeline_mod
from ingestion.knowledge.local_metadata import ResolvedMetadata
from ingestion.knowledge.pdf_ocr import HybridPage, HybridPagesResult
from ingestion.knowledge.pipeline import KnowledgeIngestResult, KnowledgePipeline
from services.knowledge.models import KnowledgeDocument


# --- self-contained fakes (style of test_pipeline_local.py) ----------------------

class FakeDocRepo:
    def __init__(self, existing_by_url=None):
        self.existing_by_url = existing_by_url or {}
        self.created = []
        self.marked = []
        self._next_id = 1

    def get_document_by_url(self, url):
        return self.existing_by_url.get(url)

    def get_or_create_document(self, doc):
        self.created.append(doc)
        doc_id = self._next_id
        self._next_id += 1
        return doc_id

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


class FakeFetchResult:
    def __init__(self, content=b"%PDF-x", content_hash="h1",
                 content_type="application/pdf"):
        self.raw_content = content
        self.content_hash = content_hash
        self.content_type = content_type


def _hybrid(pages, text=0, ocr=0, failed=0):
    return HybridPagesResult(pages=pages, pages_text=text, pages_ocr=ocr,
                             pages_failed=failed)


def _patch_hybrid(monkeypatch, result):
    calls = []

    def fake(content, ocr):
        calls.append(content)
        return result

    monkeypatch.setattr(pipeline_mod, "extract_pages_hybrid", fake)
    return calls


def _classify(school="HUST", year=2026):
    def classify(first_pages_text, filename, overrides):
        return ResolvedMetadata(school=school, year=year)
    return classify


PAGE = HybridPage(1, "Nội dung trang một đủ dài để thành một chunk.", "text_layer")


def _pipeline(doc_repo, chunk_repo, fetch):
    return KnowledgePipeline(registry=None, embedder=FakeEmbedder(),
                             doc_repo=doc_repo, chunk_repo=chunk_repo, fetch=fetch)


# --- run_for_url ------------------------------------------------------------------

def test_run_for_url_ingests_with_config_school_and_url_citation(monkeypatch):
    _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    doc_repo, chunk_repo = FakeDocRepo(), FakeChunkRepo()
    url = "https://hust.edu.vn/uploads/de-an-2026.pdf"
    pipe = _pipeline(doc_repo, chunk_repo,
                     fetch=lambda u: FakeFetchResult(content=b"%PDF-x", content_hash="h1"))

    result = pipe.run_for_url(url, school="HUST",
                              ocr=lambda png: "x", classify=_classify(year=2026))

    assert result.skipped is False
    assert result.source_url == url
    assert result.school == "HUST" and result.year == 2026
    assert result.pages_text == 1 and result.pages_ocr == 0
    # citation + metadata
    assert doc_repo.created[0].document_type == "crawled_pdf"
    assert doc_repo.created[0].source_url == url
    assert doc_repo.created[0].school == "HUST"
    assert all(c.topic is None for c in chunk_repo.upserts)
    assert all(c.school == "HUST" and c.year == 2026 for c in chunk_repo.upserts)
    assert all(c.source_url == url for c in chunk_repo.upserts)
    assert doc_repo.marked == [(1, "h1")]


def test_run_for_url_school_is_authoritative_over_classifier(monkeypatch):
    # classifier guesses a different/unknown school; config school wins.
    _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    doc_repo, chunk_repo = FakeDocRepo(), FakeChunkRepo()
    pipe = _pipeline(doc_repo, chunk_repo, fetch=lambda u: FakeFetchResult())

    result = pipe.run_for_url("https://neu.edu.vn/x.pdf", school="NEU",
                              ocr=lambda png: "x",
                              classify=_classify(school="unknown", year=2025))

    assert result.school == "NEU"          # from config, not classifier
    assert result.year == 2025             # year still taken from classifier
    assert all(c.school == "NEU" for c in chunk_repo.upserts)
