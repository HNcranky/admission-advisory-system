# PDF Ingest-by-URL (hybrid) Implementation Plan (3/4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `KnowledgePipeline.run_for_url(...)` — fetch a PDF by URL, run the **hybrid** extractor (text-layer + per-page OCR), classify the year, chunk/embed/upsert, and cite the school URL. This is the OCR-capable URL path that `run_for_source` lacks.

**Architecture:** Mirror the proven `run_for_local_file` flow but source bytes from `self.fetch(url)` instead of disk. `school` is supplied by the caller (the crawl config — authoritative, since a PDF found under `hust.edu.vn` is HUST), so the classifier is used only to fill `year`. Content-hash skip makes re-ingest idempotent. Reuses `extract_pages_hybrid`, `pages_to_marked_text`, `build_gateway_ocr`, `build_gateway_classifier`, `_chunk_embed_upsert` — all already imported in `pipeline.py`.

**Tech Stack:** Python 3.12, existing inference gateway + pgvector repos.

This is plan **3 of 4**. No dependency on plans 1–2 (it only touches the pipeline). Consumed by plan 4 (`ingest_manifest`).

---

### Task 1: `run_for_url` — fetch + hybrid extract + classify year + upsert

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (add method to `KnowledgePipeline`, after `run_for_local_file`, around line 222)
- Test: `tests/ingestion/knowledge/test_pipeline_url.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_pipeline_url.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_pipeline_url.py -q`
Expected: FAIL — `AttributeError: 'KnowledgePipeline' object has no attribute 'run_for_url'`

- [ ] **Step 3: Add `run_for_url` to `KnowledgePipeline`**

Insert this method into `ingestion/knowledge/pipeline.py` right after `run_for_local_file` (before `run_for_local_dir`, ~line 223). All names used (`hashlib`, `extract_pages_hybrid`, `build_gateway_ocr`, `build_gateway_classifier`, `pages_to_marked_text`, `KnowledgeDocument`) are already imported at the top of the module.

```python
    def run_for_url(self, url: str, *, school: str,
                    document_type: str = "crawled_pdf",
                    ocr=None, classify=None) -> KnowledgeIngestResult:
        """Ingest a PDF straight from its URL using the hybrid extractor
        (text-layer + OCR). `school` comes from the crawl config (authoritative);
        the classifier only fills `year`. Citation = the school URL."""
        if ocr is None:
            ocr = build_gateway_ocr()
        if classify is None:
            classify = build_gateway_classifier()

        fr = self.fetch(url)
        content = fr.raw_content
        content_hash = fr.content_hash or hashlib.sha256(content).hexdigest()

        existing = self.doc_repo.get_document_by_url(url)
        if existing is not None and existing.content_hash == content_hash:
            logger.info("Unchanged, skipping %s", url)
            return KnowledgeIngestResult(source_url=url, skipped=True)

        hybrid = extract_pages_hybrid(content, ocr)
        text = pages_to_marked_text(hybrid.to_page_tuples())
        first_pages = "\n\n".join(
            p.text for p in hybrid.pages[:2] if p.text.strip()
        )
        filename = url.rsplit("/", 1)[-1] or url
        # school is authoritative from config; take only the year, ignore the
        # classifier's school + its school=unknown warning (irrelevant here).
        year = classify(first_pages, filename, {}).year

        doc_id = self.doc_repo.get_or_create_document(KnowledgeDocument(
            school=school, document_type=document_type,
            source_url=url, raw_text=text,
        ))
        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text, school=school, topic=None, program=None, year=year,
            document_type=document_type, source_url=url,
        )
        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused), "
            "pages text/ocr/failed=%d/%d/%d",
            url, total, embedded, reused,
            hybrid.pages_text, hybrid.pages_ocr, hybrid.pages_failed,
        )
        return KnowledgeIngestResult(
            source_url=url, skipped=False,
            chunks_total=total, chunks_embedded=embedded, chunks_reused=reused,
            pages_text=hybrid.pages_text, pages_ocr=hybrid.pages_ocr,
            pages_ocr_failed=hybrid.pages_failed,
            school=school, year=year, warnings=[],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_pipeline_url.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/pipeline.py tests/ingestion/knowledge/test_pipeline_url.py
git commit -m "feat: add hybrid ingest-by-URL path to knowledge pipeline"
```

---

### Task 2: Content-hash skip for unchanged URLs

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (already covered by the skip branch from Task 1 — this task locks it with a test)
- Test: `tests/ingestion/knowledge/test_pipeline_url.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_pipeline_url.py
def test_run_for_url_skips_unchanged_by_content_hash(monkeypatch):
    url = "https://hust.edu.vn/x.pdf"
    existing = KnowledgeDocument(school="HUST", document_type="crawled_pdf",
                                 source_url=url, content_hash="h1",
                                 raw_text="[Trang 1]\nCũ")
    calls = _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    doc_repo, chunk_repo = FakeDocRepo({url: existing}), FakeChunkRepo()
    pipe = _pipeline(doc_repo, chunk_repo,
                     fetch=lambda u: FakeFetchResult(content_hash="h1"))

    result = pipe.run_for_url(url, school="HUST",
                              ocr=lambda png: "x", classify=_classify())

    assert result == KnowledgeIngestResult(source_url=url, skipped=True)
    assert calls == []                 # no extract/OCR when unchanged
    assert chunk_repo.upserts == []
    assert doc_repo.marked == []


def test_run_for_url_reingests_when_hash_differs(monkeypatch):
    url = "https://hust.edu.vn/x.pdf"
    existing = KnowledgeDocument(school="HUST", document_type="crawled_pdf",
                                 source_url=url, content_hash="OLD",
                                 raw_text="cũ")
    _patch_hybrid(monkeypatch, _hybrid([PAGE], text=1))
    doc_repo, chunk_repo = FakeDocRepo({url: existing}), FakeChunkRepo()
    pipe = _pipeline(doc_repo, chunk_repo,
                     fetch=lambda u: FakeFetchResult(content_hash="NEW"))

    result = pipe.run_for_url(url, school="HUST",
                              ocr=lambda png: "x", classify=_classify())

    assert result.skipped is False
    assert doc_repo.marked == [(1, "NEW")]
```

- [ ] **Step 2: Run test to verify it passes**

The skip branch already exists from Task 1, so these tests should pass immediately.
Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_pipeline_url.py -q`
Expected: PASS (4 passed)

If `test_run_for_url_skips_unchanged_by_content_hash` FAILS (e.g. extract ran), confirm the skip branch in `run_for_url` checks `existing.content_hash == content_hash` BEFORE calling `extract_pages_hybrid`.

- [ ] **Step 3: Run the full knowledge test suite to confirm no regression**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge -q`
Expected: PASS (existing local/ocr tests + new url tests all green)

- [ ] **Step 4: Commit**

```bash
git add tests/ingestion/knowledge/test_pipeline_url.py
git commit -m "test: lock content-hash skip and re-ingest for run_for_url"
```

---

## Done when
- `KnowledgePipeline.run_for_url(url, school=...)` ingests a PDF via the hybrid extractor, cites the URL, uses config `school` + classifier `year`, and is idempotent by content hash.
- `tests/ingestion/knowledge` is fully green.
- Next: plan 4 drives `run_for_url` from the manifest's `keep` entries.
