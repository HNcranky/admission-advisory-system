import hashlib

import ingestion.knowledge.pipeline as pipeline_mod
from ingestion.knowledge.local_metadata import ResolvedMetadata
from ingestion.knowledge.pdf_ocr import HybridPage, HybridPagesResult
from ingestion.knowledge.pipeline import KnowledgeIngestResult, KnowledgePipeline
from services.knowledge.models import KnowledgeDocument


# --- fakes (tự chứa, style test_pipeline.py) -------------------------------------

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
    def __init__(self, reuse_map=None):
        self.reuse_map = reuse_map or {}
        self.upserts = []

    def get_embeddings_for_hashes(self, hashes):
        return dict(self.reuse_map)

    def delete_chunks_for_document(self, doc_id):
        return 0

    def upsert_chunk(self, chunk):
        self.upserts.append(chunk)
        return len(self.upserts)


class FakeEmbedder:
    def __init__(self, dim=3):
        self.dim = dim
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0] + [0.0] * (self.dim - 1) for _ in texts]


def _pipeline(doc_repo=None, chunk_repo=None, embedder=None):
    return KnowledgePipeline(
        registry=None,
        embedder=embedder or FakeEmbedder(),
        doc_repo=doc_repo or FakeDocRepo(),
        chunk_repo=chunk_repo or FakeChunkRepo(),
        fetch=lambda url: None,   # luồng local không bao giờ fetch
    )


def _make_tree(tmp_path, files):
    """files: {"pdf_text/a.pdf": b"%PDF-a", ...} -> root path."""
    for rel, data in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return tmp_path


def _hybrid(pages, text=0, ocr=0, failed=0):
    return HybridPagesResult(
        pages=pages, pages_text=text, pages_ocr=ocr, pages_failed=failed,
    )


def _classify(school="HUST", year=2026, warnings=()):
    def classify(first_pages_text, filename, overrides):
        return ResolvedMetadata(school=school, year=year, warnings=list(warnings))
    return classify


PAGE = HybridPage(1, "Nội dung trang một đủ dài để thành một chunk.", "text_layer")


# --- KnowledgeIngestResult mở rộng ------------------------------------------------

def test_ingest_result_new_fields_default_to_zero_empty():
    result = KnowledgeIngestResult(source_url="file:///x.pdf", skipped=True)
    assert result.pages_text == 0
    assert result.pages_ocr == 0
    assert result.pages_ocr_failed == 0
    assert result.school == ""
    assert result.year is None
    assert result.warnings == []
