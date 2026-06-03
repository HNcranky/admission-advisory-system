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


# --- run_for_local_file -----------------------------------------------------------

def _patch_hybrid(monkeypatch, result_or_factory):
    """Thay extract_pages_hybrid trong pipeline module; trả list content đã gọi."""
    calls = []

    def fake(content, ocr):
        calls.append(content)
        if callable(result_or_factory):
            return result_or_factory(content)
        return result_or_factory

    monkeypatch.setattr(pipeline_mod, "extract_pages_hybrid", fake)
    return calls


def test_new_local_file_ingests_with_null_topic_and_folder_doctype(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {"pdf_scanned/a-2026.pdf": b"%PDF-a"})
    _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    doc_repo, chunk_repo = FakeDocRepo(), FakeChunkRepo()
    pipe = _pipeline(doc_repo, chunk_repo)
    pdf_path = root / "pdf_scanned" / "a-2026.pdf"

    result = pipe.run_for_local_file(
        pdf_path, root, {}, ocr=lambda png: "x", classify=_classify(),
    )

    assert result.skipped is False
    assert result.source_url.startswith("file:///")
    assert result.school == "HUST" and result.year == 2026
    assert result.pages_text == 1 and result.pages_ocr == 0
    # doc + chunks mang metadata local đúng spec
    assert doc_repo.created[0].document_type == "pdf_scanned"
    assert doc_repo.created[0].school == "HUST"
    assert all(c.topic is None for c in chunk_repo.upserts)
    assert all(c.document_type == "pdf_scanned" for c in chunk_repo.upserts)
    assert all(c.year == 2026 for c in chunk_repo.upserts)
    assert all(c.source_url == result.source_url for c in chunk_repo.upserts)
    # mark_ingested với sha256 của bytes, gọi SAU upsert
    expected_hash = hashlib.sha256(b"%PDF-a").hexdigest()
    assert doc_repo.marked == [(1, expected_hash)]


def test_unchanged_file_without_override_skips_extract(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {"pdf_text/a.pdf": b"%PDF-a"})
    pdf_path = root / "pdf_text" / "a.pdf"
    url = pdf_path.resolve().as_uri()
    h = hashlib.sha256(b"%PDF-a").hexdigest()
    existing = KnowledgeDocument(
        school="HUST", document_type="pdf_text",
        source_url=url, content_hash=h, raw_text="[Trang 1]\nCũ",
    )
    extract_calls = _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    doc_repo = FakeDocRepo({url: existing})
    pipe = _pipeline(doc_repo)

    result = pipe.run_for_local_file(
        pdf_path, root, {}, ocr=lambda png: "x", classify=_classify(),
    )

    assert result == KnowledgeIngestResult(source_url=url, skipped=True)
    assert extract_calls == []        # không OCR lại, không extract lại
    assert doc_repo.marked == []


def test_override_on_unchanged_file_reingests_from_stored_raw_text(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {"pdf_text/a.pdf": b"%PDF-a"})
    pdf_path = root / "pdf_text" / "a.pdf"
    url = pdf_path.resolve().as_uri()
    h = hashlib.sha256(b"%PDF-a").hexdigest()
    existing = KnowledgeDocument(
        school="unknown", document_type="pdf_text",
        source_url=url, content_hash=h,
        raw_text="[Trang 1]\nVăn bản đã lưu từ lần OCR trước",
    )

    def explode(content, ocr):
        raise AssertionError("extract/OCR must not run for override re-ingest")

    monkeypatch.setattr(pipeline_mod, "extract_pages_hybrid", explode)
    doc_repo, chunk_repo = FakeDocRepo({url: existing}), FakeChunkRepo()
    pipe = _pipeline(doc_repo, chunk_repo)
    overrides = {"a.pdf": {"school": "NEU", "year": 2025}}

    result = pipe.run_for_local_file(
        pdf_path, root, overrides, ocr=lambda png: "x", classify=_classify(),
    )

    assert result.skipped is False
    assert result.school == "NEU" and result.year == 2025
    assert chunk_repo.upserts                              # re-chunk từ raw_text đã lưu
    assert all(c.school == "NEU" and c.year == 2025 for c in chunk_repo.upserts)
    assert "Văn bản đã lưu" in chunk_repo.upserts[0].chunk_text
    assert doc_repo.marked == [(1, h)]                     # re-mark, hash không đổi


# --- folder-intent cross-check ----------------------------------------------------

def test_pdf_text_file_mostly_ocr_warns_move_to_scanned(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {"pdf_text/scan.pdf": b"%PDF-s"})
    pages = [
        HybridPage(1, "ocr một", "ocr"),
        HybridPage(2, "ocr hai", "ocr"),
        HybridPage(3, "Trang có text layer dài đàng hoàng.", "text_layer"),
    ]
    _patch_hybrid(monkeypatch, _hybrid(pages, text=1, ocr=2))
    pipe = _pipeline()

    result = pipe.run_for_local_file(
        root / "pdf_text" / "scan.pdf", root, {},
        ocr=lambda png: "x", classify=_classify(),
    )

    assert any("pdf_scanned/" in w for w in result.warnings)


def test_pdf_text_file_minority_ocr_does_not_warn(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {"pdf_text/ok.pdf": b"%PDF-t"})
    pages = [
        HybridPage(1, "Trang text một.", "text_layer"),
        HybridPage(2, "Trang text hai.", "text_layer"),
        HybridPage(3, "ocr", "ocr"),
    ]
    _patch_hybrid(monkeypatch, _hybrid(pages, text=2, ocr=1))
    pipe = _pipeline()

    result = pipe.run_for_local_file(
        root / "pdf_text" / "ok.pdf", root, {},
        ocr=lambda png: "x", classify=_classify(),
    )

    assert result.warnings == []


def test_pdf_scanned_all_text_layer_is_info_not_warning(tmp_path, monkeypatch):
    # File bỏ "nhầm" vào pdf_scanned nhưng có text layer: chỉ INFO, không warning.
    root = _make_tree(tmp_path, {"pdf_scanned/text.pdf": b"%PDF-t"})
    _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    pipe = _pipeline()

    result = pipe.run_for_local_file(
        root / "pdf_scanned" / "text.pdf", root, {},
        ocr=lambda png: "x", classify=_classify(),
    )

    assert result.warnings == []      # không tốn OCR, không cần cảnh báo


# --- run_for_local_dir ------------------------------------------------------------

def test_run_for_local_dir_scans_both_folders_recursively(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {
        "pdf_text/a.pdf": b"%PDF-a",
        "pdf_text/sub/b.pdf": b"%PDF-b",          # đệ quy
        "pdf_scanned/c.pdf": b"%PDF-c",
        "pdf_text/not-a-pdf.txt": "bỏ qua".encode(),   # không phải *.pdf
    })
    _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    doc_repo, chunk_repo = FakeDocRepo(), FakeChunkRepo()
    pipe = _pipeline(doc_repo, chunk_repo)

    results = pipe.run_for_local_dir(root, ocr=lambda png: "x", classify=_classify())

    assert len(results) == 3
    assert all(r.source_url.startswith("file:///") for r in results)
    assert {d.document_type for d in doc_repo.created} == {"pdf_text", "pdf_scanned"}


def test_run_for_local_dir_reads_overrides_json(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {"pdf_text/a.pdf": b"%PDF-a"})
    (root / "overrides.json").write_text(
        '{"a.pdf": {"school": "NEU", "year": 2024}}', encoding="utf-8"
    )
    _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    seen = {}

    def classify(first_pages_text, filename, overrides):
        seen["overrides"] = overrides
        # classifier thật (resolve_metadata) sẽ ưu tiên override — mô phỏng:
        entry = overrides[filename]
        return ResolvedMetadata(school=entry["school"], year=entry["year"])

    results = _pipeline().run_for_local_dir(root, ocr=lambda png: "x", classify=classify)

    assert seen["overrides"] == {"a.pdf": {"school": "NEU", "year": 2024}}
    assert results[0].school == "NEU"


def test_one_failing_file_does_not_abort_the_run(tmp_path, monkeypatch):
    from ingestion.knowledge.pdf_ocr import HybridExtractionError

    root = _make_tree(tmp_path, {
        "pdf_text/bad.pdf": b"%PDF-bad",
        "pdf_text/good.pdf": b"%PDF-good",
    })

    def factory(content):
        if content == b"%PDF-bad":
            raise HybridExtractionError("no text at all")
        return _hybrid([PAGE], text=1)

    _patch_hybrid(monkeypatch, factory)
    doc_repo = FakeDocRepo()
    pipe = _pipeline(doc_repo)

    results = pipe.run_for_local_dir(root, ocr=lambda png: "x", classify=_classify())

    # file hỏng bị nuốt (đã log error), file tốt vẫn ingest
    assert len(results) == 1
    assert results[0].source_url.endswith("good.pdf")
    # file hỏng KHÔNG được mark_ingested → lần chạy sau còn retry
    assert len(doc_repo.marked) == 1


def test_missing_folder_is_tolerated(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {"pdf_text/a.pdf": b"%PDF-a"})   # không có pdf_scanned/
    _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))

    results = _pipeline().run_for_local_dir(root, ocr=lambda png: "x", classify=_classify())

    assert len(results) == 1
