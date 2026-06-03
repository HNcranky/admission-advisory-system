# Plan 05: Local-Dir Pipeline + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m ingestion.knowledge.pipeline --local-dir data/knowledge` quét đệ quy `pdf_text/` + `pdf_scanned/`, hybrid extract (Plan 02) → classify metadata (Plan 03) → chunk/embed/upsert (tái dùng code sẵn có), idempotent theo content_hash, override re-ingest từ `raw_text` không tốn OCR, summary mỗi file 1 dòng + WARNING.

**Architecture:** (1) Refactor phần chunk→embed→upsert của `run_for_source` thành helper `_chunk_embed_upsert` dùng chung (không đổi hành vi, test cũ là lưới an toàn). (2) Method mới `run_for_local_file` xử lý 1 file (skip/override/extract/ingest) và `run_for_local_dir` quét folder + cô lập lỗi per-file (pattern `run_for_school`). (3) Mở rộng `KnowledgeIngestResult` với thống kê trang/school/year/warnings. (4) CLI thêm `--local-dir` mutually-exclusive với `--school/--all`. Chunk local ingest với `topic=None`, `document_type=<tên folder>`, `source_url=file:///...`.

**Tech Stack:** `pathlib` (`rglob`, `as_uri`), `hashlib.sha256` (cùng cách `http_fetcher` tính `content_hash`), fakes + `monkeypatch` theo style `tests/ingestion/knowledge/test_pipeline.py`.

**Phụ thuộc:** Plan 02 (`extract_pages_hybrid`, `build_gateway_ocr`, `HybridPagesResult`), Plan 03 (`load_overrides`, `metadata_from_override`, `build_gateway_classifier`, `ResolvedMetadata`). Plan 04 độc lập nhưng nên xong trước khi acceptance cuối (retrieval mới thấy chunk NULL-topic).

---

## Bối cảnh cho người chưa biết codebase

- `KnowledgePipeline.run_for_source` (`ingestion/knowledge/pipeline.py:44-113`) là luồng
  URL hiện tại: hash-skip → extract → chunk → embedding-reuse theo `content_hash` chunk
  (corpus-wide) → `delete_chunks_for_document` → `upsert_chunk` → `mark_ingested` **cuối cùng**.
  Thứ tự `mark_ingested` cuối là bất biến quan trọng: file fail giữa chừng sẽ không bị
  content-hash skip che ở lần chạy sau.
- Repos/embedder đều injectable qua constructor — test dùng fake, không DB.
- `pages_to_marked_text` (`ingestion/knowledge/pdf_pages.py:20`) nhận `[(page_no, text)]`,
  bỏ trang rỗng, prefix `[Trang N]` — `HybridPagesResult.to_page_tuples()` (Plan 02) khớp shape này.
- Layout folder người dùng (gitignored, KHÔNG commit tài liệu):

```
data/knowledge/
├── pdf_text/         ← PDF có text layer
├── pdf_scanned/      ← PDF scan
└── overrides.json    ← (tuỳ chọn) sửa metadata khi classify nhầm
```

---

### Task 1: Refactor `_chunk_embed_upsert` (không đổi hành vi)

**Files:**
- Modify: `ingestion/knowledge/pipeline.py:44-113`
- Test: `tests/ingestion/knowledge/test_pipeline.py` (KHÔNG sửa — chính là lưới an toàn)

- [ ] **Step 1: Chạy test hiện có làm baseline**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge -q`
Expected: tất cả PASS (ghi lại số test pass).

- [ ] **Step 2: Tách helper**

Trong `class KnowledgePipeline` (`ingestion/knowledge/pipeline.py`), thêm method mới ngay sau `_extract_text` và rút gọn `run_for_source` thành:

```python
    def _chunk_embed_upsert(self, doc_id, text, *, school, topic, program,
                            year, document_type, source_url):
        """Chunk -> reuse/embed -> replace chunks for one document.

        Returns (chunks_total, chunks_embedded, chunks_reused).
        """
        chunks = split_into_chunks(text)
        hashes = [chunk_content_hash(c.chunk_text) for c in chunks]
        # Corpus-wide reuse: identical chunk text in ANY document reuses its
        # embedding, so re-ingestion never re-embeds text already seen.
        reuse = self.chunk_repo.get_embeddings_for_hashes(hashes)

        embeddings: list = [None] * len(chunks)
        to_embed_idx: list[int] = []
        to_embed_text: list[str] = []
        reused = 0
        for i, c in enumerate(chunks):
            h = hashes[i]
            if h in reuse:
                embeddings[i] = reuse[h]
                reused += 1
            else:
                to_embed_idx.append(i)
                to_embed_text.append(c.chunk_text)

        if to_embed_text:
            vectors = self.embedder.embed(to_embed_text)
            for idx, vec in zip(to_embed_idx, vectors):
                embeddings[idx] = vec

        self.chunk_repo.delete_chunks_for_document(doc_id)
        for i, c in enumerate(chunks):
            self.chunk_repo.upsert_chunk(KnowledgeChunk(
                knowledge_document_id=doc_id,
                school=school,
                topic=topic,
                program=program,
                year=year,
                document_type=document_type,
                chunk_text=c.chunk_text,
                content_hash=hashes[i],
                embedding=embeddings[i],
                source_url=source_url,
                span_start=c.span_start,
                span_end=c.span_end,
            ))
        return len(chunks), len(to_embed_text), reused

    def run_for_source(self, source) -> KnowledgeIngestResult:
        fr = self.fetch(source.source_url)
        content_hash = fr.content_hash

        existing = self.doc_repo.get_document_by_url(source.source_url)
        if existing is not None and existing.content_hash == content_hash:
            logger.info("Unchanged, skipping %s", source.source_url)
            return KnowledgeIngestResult(source_url=source.source_url, skipped=True)

        text = self._extract_text(fr, source.source_url)
        doc_id = self.doc_repo.get_or_create_document(KnowledgeDocument(
            school=source.school,
            document_type=source.document_type,
            source_url=source.source_url,
            raw_text=text,
        ))

        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text,
            school=source.school, topic=source.topic, program=source.program,
            year=source.year, document_type=source.document_type,
            source_url=source.source_url,
        )

        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused)",
            source.source_url, total, embedded, reused,
        )
        return KnowledgeIngestResult(
            source_url=source.source_url,
            skipped=False,
            chunks_total=total,
            chunks_embedded=embedded,
            chunks_reused=reused,
        )
```

(Body cũ của `run_for_source` từ `chunks = split_into_chunks(text)` đến vòng `upsert_chunk` chuyển nguyên văn vào helper — chỉ thay `source.xxx` bằng keyword args.)

- [ ] **Step 3: Chạy lại test, xác nhận không hồi quy**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge -q`
Expected: pass đúng bằng baseline Step 1 (đặc biệt `test_old_chunks_deleted_before_new_upserts` chốt thứ tự map→delete→upsert).

- [ ] **Step 4: Commit**

```powershell
git add ingestion\knowledge\pipeline.py
git commit -m "refactor: extract chunk-embed-upsert helper from run_for_source"
```

---

### Task 2: Mở rộng `KnowledgeIngestResult`

**Files:**
- Modify: `ingestion/knowledge/pipeline.py:20-26`
- Test: `tests/ingestion/knowledge/test_pipeline_local.py` (file mới)

- [ ] **Step 1: Viết failing test**

Tạo `tests/ingestion/knowledge/test_pipeline_local.py` (fakes tự chứa — file test này sẽ được các task sau bồi thêm):

```python
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
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pipeline_local.py -q`
Expected: FAILED — `AttributeError: 'KnowledgeIngestResult' object has no attribute 'pages_text'`.

- [ ] **Step 3: Mở rộng dataclass**

Trong `ingestion/knowledge/pipeline.py`, đổi import dataclass và mở rộng result:

```python
from dataclasses import dataclass, field
```

```python
@dataclass
class KnowledgeIngestResult:
    source_url: str
    skipped: bool
    chunks_total: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    # Local-PDF (hybrid OCR) stats — stay at defaults for URL sources.
    pages_text: int = 0
    pages_ocr: int = 0
    pages_ocr_failed: int = 0
    school: str = ""
    year: int | None = None
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Chạy test, xác nhận pass (cả test cũ — equality của dataclass vẫn đúng nhờ defaults)**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge -q`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\pipeline.py tests\ingestion\knowledge\test_pipeline_local.py
git commit -m "feat: extend KnowledgeIngestResult with OCR page stats and warnings"
```

---

### Task 3: `run_for_local_file` — ingest mới, skip, override re-ingest

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (imports + method mới)
- Test: `tests/ingestion/knowledge/test_pipeline_local.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

Thêm vào cuối `tests/ingestion/knowledge/test_pipeline_local.py`:

```python
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
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pipeline_local.py -q`
Expected: 3 test mới FAILED — `AttributeError: 'KnowledgePipeline' object has no attribute 'run_for_local_file'`.

- [ ] **Step 3: Implement**

Trong `ingestion/knowledge/pipeline.py`:

(a) Bổ sung imports đầu file:

```python
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.parsers.html_parser import parse_html
from ingestion.knowledge.local_metadata import (
    build_gateway_classifier,
    load_overrides,
    metadata_from_override,
)
from ingestion.knowledge.pdf_ocr import build_gateway_ocr, extract_pages_hybrid
from ingestion.knowledge.pdf_pages import extract_pages, pages_to_marked_text
from ingestion.knowledge.chunker import split_into_chunks
from ingestion.knowledge.embedder import GeminiEmbedder
from ingestion.knowledge.registry.knowledge_registry import KnowledgeRegistry
from services.knowledge.models import KnowledgeChunk, KnowledgeDocument
from services.knowledge.repository import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
    chunk_content_hash,
)
```

(b) Hằng số module (sau `logger = ...`):

```python
# Folder layout under --local-dir. Folder name doubles as document_type (D7);
# both folders run the SAME hybrid extractor — folder is intent, not command (D3).
LOCAL_FOLDERS = ("pdf_text", "pdf_scanned")
```

(c) Method mới trong `KnowledgePipeline` (đặt sau `run_for_source`):

```python
    def run_for_local_file(self, pdf_path: Path, root: Path, overrides: dict,
                           ocr, classify) -> KnowledgeIngestResult:
        content = pdf_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        source_url = pdf_path.resolve().as_uri()      # citation trỏ về file gốc
        folder = pdf_path.relative_to(root).parts[0]  # "pdf_text" | "pdf_scanned"
        override_entry = overrides.get(pdf_path.name)

        existing = self.doc_repo.get_document_by_url(source_url)
        if existing is not None and existing.content_hash == content_hash:
            if override_entry is None:
                logger.info("Unchanged, skipping %s", source_url)
                return KnowledgeIngestResult(source_url=source_url, skipped=True)
            # Override on an unchanged file: re-chunk from the stored raw_text —
            # no extract/OCR cost; chunk embeddings are reused by content_hash.
            meta = metadata_from_override(override_entry)
            text = existing.raw_text or ""
            warnings: list[str] = []
            pages_text = pages_ocr = pages_failed = 0
        else:
            hybrid = extract_pages_hybrid(content, ocr)
            text = pages_to_marked_text(hybrid.to_page_tuples())
            first_pages = "\n\n".join(
                p.text for p in hybrid.pages[:2] if p.text.strip()
            )
            meta = classify(first_pages, pdf_path.name, overrides)
            warnings = list(meta.warnings)
            warnings += _folder_intent_warnings(folder, hybrid, pdf_path.name)
            pages_text, pages_ocr, pages_failed = (
                hybrid.pages_text, hybrid.pages_ocr, hybrid.pages_failed,
            )

        doc_id = self.doc_repo.get_or_create_document(KnowledgeDocument(
            school=meta.school,
            document_type=folder,
            source_url=source_url,
            raw_text=text,
        ))
        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text,
            school=meta.school, topic=None, program=None, year=meta.year,
            document_type=folder, source_url=source_url,
        )
        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused), "
            "pages text/ocr/failed=%d/%d/%d",
            source_url, total, embedded, reused,
            pages_text, pages_ocr, pages_failed,
        )
        return KnowledgeIngestResult(
            source_url=source_url, skipped=False,
            chunks_total=total, chunks_embedded=embedded, chunks_reused=reused,
            pages_text=pages_text, pages_ocr=pages_ocr,
            pages_ocr_failed=pages_failed,
            school=meta.school, year=meta.year, warnings=warnings,
        )
```

(d) Helper module-level (đặt trên `class KnowledgePipeline` hoặc dưới `LOCAL_FOLDERS` — sẽ được Task 4 dùng tiếp). Tạm thời để cross-check trả rỗng, Task 4 sẽ TDD phần warning:

```python
def _folder_intent_warnings(folder: str, hybrid, filename: str) -> list[str]:
    """Quality gate D3: folder is intent; mismatch warns but never blocks."""
    return []
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge -q`
Expected: tất cả PASS (test mới + toàn bộ test cũ).

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\pipeline.py tests\ingestion\knowledge\test_pipeline_local.py
git commit -m "feat: ingest a single local PDF with hash skip and override re-ingest"
```

---

### Task 4: Folder-intent cross-check (quality gate)

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (`_folder_intent_warnings`)
- Test: `tests/ingestion/knowledge/test_pipeline_local.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

```python
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
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pipeline_local.py -q`
Expected: `test_pdf_text_file_mostly_ocr_warns_move_to_scanned` FAILED (stub trả rỗng); 2 test cross-check còn lại PASS.

- [ ] **Step 3: Implement cross-check**

Thay stub `_folder_intent_warnings` trong `ingestion/knowledge/pipeline.py`:

```python
def _folder_intent_warnings(folder: str, hybrid, filename: str) -> list[str]:
    """Quality gate D3: folder is intent; mismatch warns but never blocks."""
    total = hybrid.pages_text + hybrid.pages_ocr + hybrid.pages_failed
    if total == 0:
        return []
    ocr_needed = hybrid.pages_ocr + hybrid.pages_failed
    if folder == "pdf_text" and ocr_needed * 2 > total:
        return [
            f"{filename} có vẻ là scan (>50% trang phải OCR), "
            "nên chuyển sang pdf_scanned/"
        ]
    if folder == "pdf_scanned" and hybrid.pages_text == total:
        logger.info(
            "%s: toàn bộ trang có text layer — không tốn call OCR nào", filename,
        )
    return []
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pipeline_local.py -q`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\pipeline.py tests\ingestion\knowledge\test_pipeline_local.py
git commit -m "feat: warn when local PDF folder intent mismatches page reality"
```

---

### Task 5: `run_for_local_dir` — quét folder, cô lập lỗi per-file

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (method mới)
- Test: `tests/ingestion/knowledge/test_pipeline_local.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

```python
# --- run_for_local_dir ------------------------------------------------------------

def test_run_for_local_dir_scans_both_folders_recursively(tmp_path, monkeypatch):
    root = _make_tree(tmp_path, {
        "pdf_text/a.pdf": b"%PDF-a",
        "pdf_text/sub/b.pdf": b"%PDF-b",          # đệ quy
        "pdf_scanned/c.pdf": b"%PDF-c",
        "pdf_text/not-a-pdf.txt": b"bỏ qua",      # không phải *.pdf
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
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pipeline_local.py -q`
Expected: 4 test mới FAILED — `AttributeError: ... no attribute 'run_for_local_dir'`.

- [ ] **Step 3: Implement**

Thêm method vào `KnowledgePipeline` (sau `run_for_local_file`):

```python
    def run_for_local_dir(self, root, ocr=None, classify=None) -> list[KnowledgeIngestResult]:
        """Auto-discovery (D4): scan <root>/pdf_text + <root>/pdf_scanned for
        *.pdf recursively — no per-file registration anywhere."""
        root = Path(root)
        if ocr is None:
            ocr = build_gateway_ocr()
        if classify is None:
            classify = build_gateway_classifier()
        overrides = load_overrides(root)

        results: list[KnowledgeIngestResult] = []
        for folder in LOCAL_FOLDERS:
            folder_path = root / folder
            if not folder_path.is_dir():
                logger.warning("Local folder missing, skipping: %s", folder_path)
                continue
            for pdf_path in sorted(folder_path.rglob("*.pdf")):
                try:
                    results.append(
                        self.run_for_local_file(pdf_path, root, overrides, ocr, classify)
                    )
                except Exception as exc:  # one bad file must not abort the run
                    logger.error("Local file failed %s: %r", pdf_path, exc)
        return results
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge -q`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\pipeline.py tests\ingestion\knowledge\test_pipeline_local.py
git commit -m "feat: auto-discover and ingest local PDF folders with per-file isolation"
```

---

### Task 6: CLI `--local-dir` + summary

**Files:**
- Modify: `ingestion/knowledge/pipeline.py:131-151` (`_main`)
- Test: `tests/ingestion/knowledge/test_pipeline_local.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

```python
# --- CLI + summary ----------------------------------------------------------------

def test_main_local_dir_prints_ocr_summary_and_warnings(tmp_path, monkeypatch, capsys):
    canned = [
        KnowledgeIngestResult(
            source_url="file:///x/a.pdf", skipped=False,
            chunks_total=41, chunks_embedded=40, chunks_reused=1,
            pages_text=3, pages_ocr=12, pages_ocr_failed=0,
            school="HUST", year=2026,
            warnings=["scan.pdf có vẻ là scan (>50% trang phải OCR), nên chuyển sang pdf_scanned/"],
        ),
        KnowledgeIngestResult(source_url="file:///x/b.pdf", skipped=True),
    ]

    class FakePipeline:
        def run_for_local_dir(self, root):
            return canned

    monkeypatch.setattr(pipeline_mod, "KnowledgePipeline", lambda: FakePipeline())

    rc = pipeline_mod._main(["--local-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "school=HUST" in out
    assert "year=2026" in out
    assert "pages(text/ocr/fail)=3/12/0" in out
    assert "chunks=41" in out
    assert "WARN" in out and "pdf_scanned/" in out
    assert "SKIP   file:///x/b.pdf (unchanged)" in out


def test_main_local_dir_is_mutually_exclusive_with_school(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        pipeline_mod._main(["--local-dir", str(tmp_path), "--school", "HUST"])
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pipeline_local.py -q -k main`
Expected: `test_main_local_dir_prints_ocr_summary_and_warnings` FAILED (argparse chưa biết `--local-dir` → SystemExit 2). Test mutually-exclusive PASS sẵn (argparse coi arg lạ là lỗi) — nó là chốt regression sau khi thêm arg.

- [ ] **Step 3: Sửa `_main`**

Thay toàn bộ `_main` trong `ingestion/knowledge/pipeline.py`:

```python
def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingest knowledge corpus")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--school", help="ingest one school, e.g. HUST")
    group.add_argument("--all", action="store_true", help="ingest all schools")
    group.add_argument(
        "--local-dir",
        help="ingest local PDFs from <dir>/pdf_text and <dir>/pdf_scanned",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pipeline = KnowledgePipeline()
    if args.local_dir:
        results = pipeline.run_for_local_dir(Path(args.local_dir))
    elif args.all:
        results = pipeline.run_all()
    else:
        results = pipeline.run_for_school(args.school)

    for r in results:
        if r.skipped:
            print(f"SKIP   {r.source_url} (unchanged)")
        elif r.source_url.startswith("file://"):
            print(f"OK     {r.source_url} school={r.school} year={r.year} "
                  f"pages(text/ocr/fail)={r.pages_text}/{r.pages_ocr}/{r.pages_ocr_failed} "
                  f"chunks={r.chunks_total}")
        else:
            print(f"OK     {r.source_url}  chunks={r.chunks_total} "
                  f"embedded={r.chunks_embedded} reused={r.chunks_reused}")
        for w in r.warnings:
            print(f"WARN   {w}")
    print(f"Done: {len(results)} source(s) processed")
    return 0
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge -q`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\pipeline.py tests\ingestion\knowledge\test_pipeline_local.py
git commit -m "feat: add --local-dir CLI with per-file OCR summary and warnings"
```

---

### Task 7: `.gitignore` + acceptance cuối

**Files:**
- Modify: `.gitignore` (thêm cuối file)

- [ ] **Step 1: Gitignore folder tài liệu**

Thêm vào cuối `.gitignore`:

```text

# Local knowledge corpus (official PDFs, not committed)
data/knowledge/
```

- [ ] **Step 2: Xác nhận ignore hoạt động**

```powershell
New-Item -ItemType Directory -Force data\knowledge\pdf_text, data\knowledge\pdf_scanned
git status --porcelain data\knowledge
```

Expected: `git status` không liệt kê gì dưới `data/knowledge/`.

- [ ] **Step 3: Chạy toàn bộ test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: tất cả PASS (integration/e2e cần Docker DB bật, nếu không sẽ skip).

- [ ] **Step 4: Acceptance thủ công (cần GEMINI key trong shell + vài PDF thật)**

```powershell
# Thả 1 PDF text vào data\knowledge\pdf_text\ và 1 PDF scan vào data\knowledge\pdf_scanned\
.\.venv\Scripts\python.exe -m ingestion.knowledge.pipeline --local-dir data\knowledge
# Chạy LẦN 2 ngay sau đó:
.\.venv\Scripts\python.exe -m ingestion.knowledge.pipeline --local-dir data\knowledge
```

Expected lần 1: mỗi file một dòng `OK <file:///...> school=... year=... pages(text/ocr/fail)=... chunks=...`, kèm `WARN` nếu school=unknown / folder lệch.
Expected lần 2: toàn bộ `SKIP ... (unchanged)` — **G6 idempotent: không OCR lại, không embed lại**.

- [ ] **Step 5: Commit**

```powershell
git add .gitignore
git commit -m "chore: gitignore local knowledge corpus folder"
```

---

## Định nghĩa hoàn thành (Plan 05)

- Thả file vào folder → `--local-dir` → xong, không đăng ký JSON (G2).
- PDF lai xử lý đúng từng trang qua `extract_pages_hybrid` (G3).
- Không còn "lặng lẽ biến mất": file 0 chữ raise và KHÔNG `mark_ingested`; trang fail
  đếm vào `pages_ocr_failed` và in trong summary (G4).
- File không đổi → re-run skip hoàn toàn (G6); override trên file đã ingest → re-chunk
  từ `raw_text`, không OCR.
- Chunk local: `topic=None`, `document_type=<folder>`, `source_url=file:///...`,
  `school`/`year` từ resolver (Plan 03) — kết hợp Plan 04 là chunk truy xuất được ngay.
- `.\.venv\Scripts\python.exe -m pytest -q` xanh toàn bộ.
