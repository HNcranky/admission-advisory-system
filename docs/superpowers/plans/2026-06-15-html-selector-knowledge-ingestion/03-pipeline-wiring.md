# Plan 03 — Pipeline wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thread `source.selector` through `run_for_source` → `_extract_text` → `parse_html`, and on a selector miss skip the source with a warning and zero DB writes.

**Architecture:** `_extract_text` gains a `selector` parameter (ignored, with a warning, on the PDF branch). `run_for_source` passes `source.selector` and catches `ContentSelectorNotFound`, returning `skipped=True` so the batch driver continues to the next URL.

**Tech Stack:** Python, pytest. **Depends on Plan 01** (`ContentSelectorNotFound`) and **Plan 02** (`KnowledgeSource.selector`).

---

### Task 1: selector-aware `run_for_source`

**Files:**
- Modify: `ingestion/knowledge/pipeline.py`
- Test: `tests/ingestion/knowledge/test_pipeline_source.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/ingestion/knowledge/test_pipeline_source.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_pipeline_source.py -v`
Expected: FAIL — the selector miss currently is not caught, so `_find_content_area` is never reached (selector isn't passed yet); the hit test sees the wrong region or `run_for_source` ignores `selector`.

- [ ] **Step 3: Import the exception**

In `ingestion/knowledge/pipeline.py`, update the html_parser import:

```python
from ingestion.parsers.html_parser import ContentSelectorNotFound, parse_html
```

- [ ] **Step 4: Add `selector` to `_extract_text`**

Replace the existing `_extract_text` method body with:

```python
    def _extract_text(self, fetch_result, url: str, selector: str | None = None) -> str:
        ctype = (fetch_result.content_type or "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            if selector is not None:
                logger.warning("selector %r ignored for PDF source %s", selector, url)
            return pages_to_marked_text(extract_pages(fetch_result.raw_content))
        return parse_html(fetch_result.raw_content, url, selector=selector).text
```

- [ ] **Step 5: Pass the selector and catch the miss in `run_for_source`**

In `run_for_source`, replace the line:

```python
        text = self._extract_text(fr, source.source_url)
```

with:

```python
        try:
            text = self._extract_text(fr, source.source_url, source.selector)
        except ContentSelectorNotFound:
            logger.warning(
                "selector %r not found on %s — skipping (fix selector and re-run)",
                source.selector, source.source_url,
            )
            return KnowledgeIngestResult(source_url=source.source_url, skipped=True)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_pipeline_source.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Regression — existing pipeline tests**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/ -q`
Expected: PASS (existing registry/pipeline/runner tests unaffected; `_extract_text`'s new arg defaults to `None`).

- [ ] **Step 8: Commit**

```bash
git add ingestion/knowledge/pipeline.py tests/ingestion/knowledge/test_pipeline_source.py
git commit -m "feat(knowledge): per-source selector in run_for_source, skip on miss"
```

---

### Task 2: end-to-end sanity (manual, optional)

**Files:** none (uses the real corpus + DB).

- [ ] **Step 1: Add a real seed entry**

In `ingestion/knowledge/registry/seeds/knowledge_sources.json`, add an entry for the target page (e.g. a TSA/HSA page) with a verified `selector`:

```json
{"school": "MOET", "source_url": "https://...", "document_type": "faq",
 "topic": "admission_policy", "fetch_strategy": "http", "selector": "#content"}
```

- [ ] **Step 2: Ingest and verify**

```bash
docker compose up -d --wait db
.venv/bin/python -m ingestion.knowledge.pipeline --school MOET
.venv/bin/python -m ingestion.knowledge.verify_corpus
```

Expected: the new source ingests; `verify_corpus` shows chunks under `school=MOET`; the chunk text contains the page's main content and none of its menu/footer.
