# Knowledge QA Cache — Plan 04: Ingest Invalidation Hook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ingestion bump the cache version of the scope a document is written into, so that **adding or editing** a doc invalidates any cached QA answer that depended on that scope.

**Architecture:** `KnowledgePipeline` gains an injectable `cache_repo` (default `QACacheRepository()`) and a best-effort `_bump_cache(school, topic)` helper. After every successful `mark_ingested` in `run_for_source`, `run_for_local_file`, and `run_for_url`, the pipeline bumps `scope_key_for(school, topic)` — the same helper the cache read side uses, so keys always agree. Local/URL paths write `topic=None`, mapping to the school's wildcard scope `s:{school}|t:*`. A bump failure logs a warning and never fails ingestion.

**Tech Stack:** Python 3.12, the existing `KnowledgePipeline`, `QACacheRepository` (Plan 01), pytest, psycopg2/pgvector for the integration test.

## Global Constraints

- **Never run `git push`.** No `Co-Authored-By` / AI attribution in commits.
- Ingestion must **degrade gracefully**: a cache-bump failure logs a `logger.warning` and never aborts a source/file/url ingest.
- New collaborators are injectable (constructor param), mirroring `embedder`/`doc_repo`/`chunk_repo`/`fetch`.
- **Depends on Plan 01** only: `services/knowledge/qa_cache.py` must export `QACacheRepository` (with `bump_version`) and `scope_key_for`, and migration `019` must exist. (Independent of Plans 02/03.)
- `scope_key_for(school, None)` → `"s:{school}|t:*"`; `scope_key_for(school, topic)` → `"s:{school}|t:{topic}"`.
- Existing pipeline tests stay green untouched: the bump is best-effort (wrapped), so when those tests construct a pipeline with the default real `cache_repo`, a bump either no-ops (DB down → caught warning) or writes a harmless version row to the isolated `admission_test` DB (the cache integration tests truncate the cache tables and use `ITEST`-prefixed keys, so there is no contamination).
- Run tests with `python -m pytest -q` (system Python 3.12). The integration test needs the Docker DB.

---

### Task 1: Inject `cache_repo` + add `_bump_cache`

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (imports ~line 19, `__init__` ~line 67, add helper)
- Test: `tests/ingestion/knowledge/test_pipeline_cache_bump.py`

**Interfaces:**
- Consumes: `QACacheRepository`, `scope_key_for` from `services/knowledge/qa_cache.py`.
- Produces:
  - `KnowledgePipeline(__init__)` gains `cache_repo=None` (default → `QACacheRepository()`), stored as `self.cache_repo`.
  - `KnowledgePipeline._bump_cache(school, topic) -> None` — best-effort `self.cache_repo.bump_version(scope_key_for(school, topic))`.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingestion/knowledge/test_pipeline_cache_bump.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ingestion/knowledge/test_pipeline_cache_bump.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'cache_repo'`.

- [ ] **Step 3: Add the import**

In `ingestion/knowledge/pipeline.py`, after the existing import block:

```python
from services.knowledge.repository import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
    chunk_content_hash,
)
```

add:

```python
from services.knowledge.qa_cache import QACacheRepository, scope_key_for
```

- [ ] **Step 4: Add `cache_repo` to `__init__` and the helper**

Replace `KnowledgePipeline.__init__`:

```python
    def __init__(self, registry=None, embedder=None, doc_repo=None,
                 chunk_repo=None, fetch=None):
        self.registry = registry if registry is not None else KnowledgeRegistry()
        self.embedder = embedder if embedder is not None else GeminiEmbedder()
        self.doc_repo = doc_repo if doc_repo is not None else KnowledgeDocumentRepository()
        self.chunk_repo = chunk_repo if chunk_repo is not None else KnowledgeChunkRepository()
        self.fetch = fetch if fetch is not None else http_fetch
```

with:

```python
    def __init__(self, registry=None, embedder=None, doc_repo=None,
                 chunk_repo=None, fetch=None, cache_repo=None):
        self.registry = registry if registry is not None else KnowledgeRegistry()
        self.embedder = embedder if embedder is not None else GeminiEmbedder()
        self.doc_repo = doc_repo if doc_repo is not None else KnowledgeDocumentRepository()
        self.chunk_repo = chunk_repo if chunk_repo is not None else KnowledgeChunkRepository()
        self.fetch = fetch if fetch is not None else http_fetch
        self.cache_repo = cache_repo if cache_repo is not None else QACacheRepository()

    def _bump_cache(self, school, topic) -> None:
        """A corpus change in this (school, topic) scope invalidates any cached
        QA answers that depend on it. Best-effort: a bump failure logs a warning
        and never fails ingestion (CLAUDE.md degrade-gracefully)."""
        try:
            self.cache_repo.bump_version(scope_key_for(school, topic))
        except Exception as exc:
            logger.warning(
                "knowledge QA cache bump failed for school=%r topic=%r: %r",
                school, topic, exc,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/ingestion/knowledge/test_pipeline_cache_bump.py -v`
Expected: PASS (the three `_bump_cache` cases).

- [ ] **Step 6: Commit**

```bash
git add ingestion/knowledge/pipeline.py tests/ingestion/knowledge/test_pipeline_cache_bump.py
git commit -m "feat(ingestion): add injectable cache_repo + _bump_cache to pipeline"
```

---

### Task 2: Bump after `mark_ingested` in all three runners

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (`run_for_source` ~line 162, `run_for_local_file` ~line 218, `run_for_url` ~line 271)
- Test: `tests/ingestion/knowledge/test_pipeline_cache_bump.py` (add cases)

**Interfaces:**
- Consumes: `self._bump_cache`, `self.doc_repo.mark_ingested`.
- Produces: each runner bumps exactly one scope after a successful ingest — `run_for_source` → `(source.school, source.topic)`; `run_for_local_file` → `(meta.school, None)`; `run_for_url` → `(school, None)`. Skipped (unchanged / selector-miss) ingests do **not** bump.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/knowledge/test_pipeline_cache_bump.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ingestion/knowledge/test_pipeline_cache_bump.py -v`
Expected: the four new runner tests FAIL — `assert [] == ["s:MOET|t:admission_policy"]` etc. (no bump wired yet); the three Task 1 `_bump_cache` cases still PASS.

- [ ] **Step 3: Wire the bump into `run_for_source`**

In `run_for_source`, the tail currently reads:

```python
        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused)",
            source.source_url, total, embedded, reused,
        )
```

Insert the bump immediately after `mark_ingested`:

```python
        self.doc_repo.mark_ingested(doc_id, content_hash)
        self._bump_cache(source.school, source.topic)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused)",
            source.source_url, total, embedded, reused,
        )
```

- [ ] **Step 4: Wire the bump into `run_for_local_file`**

In `run_for_local_file`, after `self.doc_repo.mark_ingested(doc_id, content_hash)` (the call that precedes the `logger.info("Ingested %s: ... pages text/ocr/failed...")` line), insert:

```python
        self.doc_repo.mark_ingested(doc_id, content_hash)
        self._bump_cache(meta.school, None)
```

(Local PDFs are written with `topic=None`, so the wildcard scope `s:{school}|t:*` is bumped.)

- [ ] **Step 5: Wire the bump into `run_for_url`**

In `run_for_url`, after `self.doc_repo.mark_ingested(doc_id, content_hash)` (the call before the final `logger.info`), insert:

```python
        self.doc_repo.mark_ingested(doc_id, content_hash)
        self._bump_cache(school, None)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/ingestion/knowledge/test_pipeline_cache_bump.py -v`
Expected: PASS (all seven cases).

- [ ] **Step 7: Run the full ingestion pipeline suite for regressions**

Run: `python -m pytest tests/ingestion/knowledge -q`
Expected: PASS. (Existing pipeline tests construct the pipeline with the default real `cache_repo`; their bumps are best-effort and do not affect their assertions.)

- [ ] **Step 8: Commit**

```bash
git add ingestion/knowledge/pipeline.py tests/ingestion/knowledge/test_pipeline_cache_bump.py
git commit -m "feat(ingestion): bump QA cache scope version after each ingest"
```

---

### Task 3: Integration — ingest invalidates a cached answer end-to-end

**Files:**
- Test: `tests/integration/test_qa_cache_ingest_invalidation.py`

**Interfaces:**
- Consumes: real `QACacheRepository` (Plans 01-02), `KnowledgePipeline` with `cache_repo` injected, the `qa_cache_clean` fixture (Plan 01 Task 5).
- Produces: proof that running an ingest through `run_for_source` bumps the doc's scope version in real Postgres, turning a previously-fresh cached answer into a miss.

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_qa_cache_ingest_invalidation.py`:

```python
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
```

- [ ] **Step 2: Run the integration test (DB up)**

Run: `python -m pytest tests/integration/test_qa_cache_ingest_invalidation.py -v`
Expected: PASS with the Docker DB up (else SKIP).

- [ ] **Step 3: Run the cache + ingestion slices for regressions**

Run: `python -m pytest tests/ingestion/knowledge tests/integration -q -k "qa_cache or pipeline or knowledge"`
Expected: PASS (DB-dependent tests SKIP when the DB is down).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_qa_cache_ingest_invalidation.py
git commit -m "test(ingestion): integration proof that ingest invalidates QA cache"
```

---

## Self-Review (run after completing all tasks)

- **Spec coverage (§Ingest hook + §Ingest bump rule + §testing):** bump after `mark_ingested` in all three runners (✓ Task 2); `(school, topic)` for sources, `(school, None)` → wildcard for local/url (✓ Task 2 + `scope_key_for`); skip paths do not bump (✓ `test_run_for_source_skip_unchanged_does_not_bump`); bump failure never fails ingestion (✓ `test_bump_cache_failure_is_swallowed`); the "additions" case — a new doc bumps the scope and invalidates an answer that never cited it — is the integration test (✓ Task 3, which adds a brand-new doc and checks the prior cached row goes stale).
- **No placeholders:** every step has exact code and an exact command.
- **Type consistency:** `_bump_cache(school, topic)` calls `scope_key_for(school, topic)` (Plan 01) → the exact key shape the read side computes via `scope_keys`; `cache_repo.bump_version(scope_key)` matches Plan 01's `bump_version` signature; the integration test reuses `store`/`lookup`/`current_versions`/`scope_keys` exactly as defined in Plans 01-02.
