# Phase 3 · Plan 05 — Pipeline, CLI & Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Orchestrate fetch → parse → chunk → embed → upsert end-to-end with two-level hashing (content-hash skip + per-chunk embedding reuse), expose a CLI, and ship a post-ingest verification script.

**Architecture:** `ingestion/knowledge/pipeline.py` defines `KnowledgePipeline` composing the Plan 01–04 components (all injectable for tests). `run_for_source` implements the §6 flow exactly: skip on unchanged `content_hash`; otherwise create the document row, read the embedding-reuse map, chunk, embed only new chunk texts, delete old chunks, upsert fresh, and finally `mark_ingested`. `run_for_school` / `run_all` isolate per-source failures. `verify_corpus.py` reports chunk counts per (school, topic) and flags schools missing data.

**Tech Stack:** Python, psycopg2, google-genai, pytest.

**Spec:** [`2026-05-30-phase-3-data-collection-design.md`](../specs/2026-05-30-phase-3-data-collection-design.md) §6, §8, §9.

**Depends on:** Plans 01 (registry), 02 (chunker + pdf_pages), 03 (embedder), 04 (repository). All must be merged first.

---

### Task 1: `KnowledgePipeline.run_for_source` — the two-level-hashing core

**Files:**
- Create: `ingestion/knowledge/pipeline.py`
- Test: `tests/ingestion/knowledge/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_pipeline.py`:
```python
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

    def get_embedding_map_for_document(self, doc_id):
        self.events.append("map")
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


def test_old_chunks_deleted_before_new_upserts():
    doc_repo, chunk_repo, embedder = FakeDocRepo(existing=None), FakeChunkRepo(), FakeEmbedder()

    _pipeline(doc_repo, chunk_repo, embedder).run_for_source(SOURCE)

    # reuse map read first, delete before any upsert
    assert chunk_repo.events[0] == "map"
    assert chunk_repo.events.index("delete") < chunk_repo.events.index("upsert")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.pipeline'`.

- [ ] **Step 3: Write minimal implementation**

`ingestion/knowledge/pipeline.py`:
```python
import logging
from dataclasses import dataclass

from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.parsers.html_parser import parse_html
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

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeIngestResult:
    source_url: str
    skipped: bool
    chunks_total: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0


class KnowledgePipeline:
    def __init__(self, registry=None, embedder=None, doc_repo=None,
                 chunk_repo=None, fetch=None):
        self.registry = registry if registry is not None else KnowledgeRegistry()
        self.embedder = embedder if embedder is not None else GeminiEmbedder()
        self.doc_repo = doc_repo if doc_repo is not None else KnowledgeDocumentRepository()
        self.chunk_repo = chunk_repo if chunk_repo is not None else KnowledgeChunkRepository()
        self.fetch = fetch if fetch is not None else http_fetch

    def _extract_text(self, fetch_result, url: str) -> str:
        ctype = (fetch_result.content_type or "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            return pages_to_marked_text(extract_pages(fetch_result.raw_content))
        return parse_html(fetch_result.raw_content, url).text

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

        reuse = self.chunk_repo.get_embedding_map_for_document(doc_id)
        chunks = split_into_chunks(text)

        embeddings: list = [None] * len(chunks)
        to_embed_idx: list[int] = []
        to_embed_text: list[str] = []
        reused = 0
        for i, c in enumerate(chunks):
            h = chunk_content_hash(c.chunk_text)
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
                school=source.school,
                topic=source.topic,
                program=source.program,
                year=source.year,
                document_type=source.document_type,
                chunk_text=c.chunk_text,
                embedding=embeddings[i],
                source_url=source.source_url,
                span_start=c.span_start,
                span_end=c.span_end,
            ))

        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused)",
            source.source_url, len(chunks), len(to_embed_text), reused,
        )
        return KnowledgeIngestResult(
            source_url=source.source_url,
            skipped=False,
            chunks_total=len(chunks),
            chunks_embedded=len(to_embed_text),
            chunks_reused=reused,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_pipeline.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/pipeline.py tests/ingestion/knowledge/test_pipeline.py
git commit -m "feat(knowledge): add KnowledgePipeline with two-level hashing"
```

---

### Task 2: PDF vs HTML extraction dispatch

**Files:**
- Modify: `tests/ingestion/knowledge/test_pipeline.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/ingestion/knowledge/test_pipeline.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_pipeline.py::test_pdf_content_type_uses_page_extraction -v`
Expected: PASS already — the dispatch in `_extract_text` (written in Task 1) handles `application/pdf`. (This task documents and locks the behavior with a test; if it fails, the `"pdf" in ctype` branch is missing.)

- [ ] **Step 3: Commit**

```bash
git add tests/ingestion/knowledge/test_pipeline.py
git commit -m "test(knowledge): lock PDF vs HTML extraction dispatch"
```

---

### Task 3: `run_for_school` / `run_all` with per-source failure isolation

**Files:**
- Modify: `ingestion/knowledge/pipeline.py`
- Test: `tests/ingestion/knowledge/test_pipeline_runners.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_pipeline_runners.py`:
```python
from ingestion.knowledge.pipeline import KnowledgePipeline, KnowledgeIngestResult
from ingestion.knowledge.registry.models import KnowledgeSource


class FakeRegistry:
    def __init__(self, sources):
        self._sources = sources

    def get_sources_by_school(self, school):
        return [s for s in self._sources if s.school == school]

    def all_sources(self):
        return list(self._sources)

    def schools(self):
        out = []
        for s in self._sources:
            if s.school not in out:
                out.append(s.school)
        return out


def _src(school, url):
    return KnowledgeSource(school=school, source_url=url,
                           document_type="tuition_page", topic="tuition")


def test_run_for_school_isolates_failing_source():
    sources = [_src("HUST", "https://ok"), _src("HUST", "https://boom")]
    pipe = KnowledgePipeline(registry=FakeRegistry(sources))

    def fake_run(source):
        if source.source_url == "https://boom":
            raise RuntimeError("fetch exploded")
        return KnowledgeIngestResult(source_url=source.source_url, skipped=False, chunks_total=2)

    pipe.run_for_source = fake_run

    results = pipe.run_for_school("HUST")

    # the good source still produced a result; the bad one was swallowed
    assert [r.source_url for r in results] == ["https://ok"]


def test_run_all_iterates_every_school():
    sources = [_src("HUST", "https://h"), _src("NEU", "https://n")]
    pipe = KnowledgePipeline(registry=FakeRegistry(sources))
    pipe.run_for_source = lambda s: KnowledgeIngestResult(source_url=s.source_url, skipped=False)

    results = pipe.run_all()

    assert {r.source_url for r in results} == {"https://h", "https://n"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_pipeline_runners.py -v`
Expected: FAIL — `AttributeError: 'KnowledgePipeline' object has no attribute 'run_for_school'`.

- [ ] **Step 3: Write minimal implementation**

Append these methods to `KnowledgePipeline` in `ingestion/knowledge/pipeline.py`:
```python
    def run_for_school(self, school: str) -> list[KnowledgeIngestResult]:
        results: list[KnowledgeIngestResult] = []
        for source in self.registry.get_sources_by_school(school):
            try:
                results.append(self.run_for_source(source))
            except Exception as exc:  # one bad source must not abort the school
                logger.error("Source failed %s: %r", source.source_url, exc)
        return results

    def run_all(self) -> list[KnowledgeIngestResult]:
        results: list[KnowledgeIngestResult] = []
        for school in self.registry.schools():
            results.extend(self.run_for_school(school))
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_pipeline_runners.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/pipeline.py tests/ingestion/knowledge/test_pipeline_runners.py
git commit -m "feat(knowledge): add run_for_school/run_all with failure isolation"
```

---

### Task 4: CLI entry point

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (append at end of file)

- [ ] **Step 1: Add the CLI**

Append to the end of `ingestion/knowledge/pipeline.py`:
```python
def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingest knowledge corpus")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--school", help="ingest one school, e.g. HUST")
    group.add_argument("--all", action="store_true", help="ingest all schools")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pipeline = KnowledgePipeline()
    results = pipeline.run_all() if args.all else pipeline.run_for_school(args.school)

    for r in results:
        if r.skipped:
            print(f"SKIP   {r.source_url} (unchanged)")
        else:
            print(f"OK     {r.source_url}  chunks={r.chunks_total} "
                  f"embedded={r.chunks_embedded} reused={r.chunks_reused}")
    print(f"Done: {len(results)} source(s) processed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 2: Verify the CLI parses (no DB/network needed for --help)**

Run: `python -m ingestion.knowledge.pipeline --help`
Expected: usage text showing `--school` and `--all`, exit 0.

- [ ] **Step 3: Commit**

```bash
git add ingestion/knowledge/pipeline.py
git commit -m "feat(knowledge): add pipeline CLI entry point"
```

---

### Task 5: `verify_corpus.py`

**Files:**
- Create: `ingestion/knowledge/verify_corpus.py`
- Test: `tests/ingestion/knowledge/test_verify_corpus.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_verify_corpus.py`:
```python
from ingestion.knowledge import verify_corpus


class FakeCursor:
    def __init__(self, fetchall_return=None, fetchone_return=None):
        self.statements = []
        self._fetchall = fetchall_return or []
        self._fetchone = fetchone_return

    def execute(self, sql, params=None):
        self.statements.append(sql)

    def fetchall(self):
        return self._fetchall

    def fetchone(self):
        return self._fetchone

    def close(self):
        return None


class FakeConnection:
    def __init__(self, fetchall_return=None, fetchone_return=None):
        self.cursor_obj = FakeCursor(fetchall_return, fetchone_return)

    def cursor(self):
        return self.cursor_obj

    def close(self):
        return None


class FakeRegistry:
    def __init__(self, schools):
        self._schools = schools

    def schools(self):
        return list(self._schools)


def test_find_missing_schools_flags_schools_with_no_chunks():
    counts = [("HUST", "tuition", 5), ("NEU", "tuition", 0)]
    missing = verify_corpus.find_missing_schools(["HUST", "NEU", "VNU-UET"], counts)
    assert missing == ["NEU", "VNU-UET"]   # NEU has only a 0-count row; VNU-UET absent


def test_collect_counts_runs_group_by_query():
    conn = FakeConnection(fetchall_return=[("HUST", "tuition", 3)])
    counts = verify_corpus.collect_counts(connection_factory=lambda: conn)
    assert counts == [("HUST", "tuition", 3)]
    assert "GROUP BY school, topic" in conn.cursor_obj.statements[0]


def test_main_returns_1_when_a_school_is_missing():
    conn = FakeConnection(fetchall_return=[("HUST", "tuition", 3)], fetchone_return=(0,))
    code = verify_corpus.main(
        connection_factory=lambda: conn,
        registry=FakeRegistry(["HUST", "NEU"]),
    )
    assert code == 1


def test_main_returns_0_when_all_schools_present():
    conn = FakeConnection(fetchall_return=[("HUST", "tuition", 3)], fetchone_return=(0,))
    code = verify_corpus.main(
        connection_factory=lambda: conn,
        registry=FakeRegistry(["HUST"]),
    )
    assert code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_verify_corpus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.verify_corpus'`.

- [ ] **Step 3: Write minimal implementation**

`ingestion/knowledge/verify_corpus.py`:
```python
from ingestion.knowledge.registry.knowledge_registry import KnowledgeRegistry
from services.knowledge.db import get_knowledge_db_connection


def collect_counts(connection_factory=get_knowledge_db_connection):
    conn = connection_factory()
    cur = conn.cursor()
    cur.execute(
        "SELECT school, topic, COUNT(*) FROM knowledge_chunks "
        "GROUP BY school, topic ORDER BY school, topic"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [(r[0], r[1], r[2]) for r in rows]


def count_null_embeddings(connection_factory=get_knowledge_db_connection) -> int:
    conn = connection_factory()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NULL")
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


def find_missing_schools(registry_schools, counts) -> list:
    present = {school for school, _topic, count in counts if count > 0}
    return [s for s in registry_schools if s not in present]


def main(connection_factory=get_knowledge_db_connection, registry=None) -> int:
    registry = registry or KnowledgeRegistry()
    counts = collect_counts(connection_factory)

    print("Chunk counts per school/topic:")
    for school, topic, count in counts:
        print(f"  {school:12} {(topic or '-'):22} {count}")

    nulls = count_null_embeddings(connection_factory)
    if nulls:
        print(f"WARNING: {nulls} chunk(s) have NULL embedding")

    missing = find_missing_schools(registry.schools(), counts)
    if missing:
        print(f"MISSING DATA for schools: {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_verify_corpus.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/verify_corpus.py tests/ingestion/knowledge/test_verify_corpus.py
git commit -m "feat(knowledge): add verify_corpus reporting script"
```

---

### Task 6: Gated end-to-end integration test

**Files:**
- Test: `tests/integration/test_knowledge_ingestion_e2e.py`

- [ ] **Step 1: Write the integration test**

`tests/integration/test_knowledge_ingestion_e2e.py`:
```python
from dataclasses import dataclass

import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG, EMBEDDING_DIM
from ingestion.knowledge.pipeline import KnowledgePipeline
from ingestion.knowledge.registry.models import KnowledgeSource
from services.knowledge.repository import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
)

pytestmark = pytest.mark.integration

HTML = b"<html><body><p>HELLO WORLD</p></body></html>"


@dataclass
class FakeFetchResult:
    content_hash: str
    content_type: str
    raw_content: bytes


class FakeEmbedder:
    """Deterministic full-dimension vectors; no API key, no network."""
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in texts]


@pytest.fixture
def clean_knowledge_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=2)
    except psycopg2.OperationalError:
        pytest.skip(
            "Postgres not reachable; run "
            "`docker compose up -d db && python -m db.setup_db` first."
        )
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE knowledge_chunks, knowledge_documents RESTART IDENTITY CASCADE"
        )
    conn.commit()
    conn.close()


def test_ingest_then_rerun_is_idempotent(clean_knowledge_db):
    source = KnowledgeSource(
        school="HUST", source_url="https://x/t",
        document_type="tuition_page", topic="tuition",
    )
    embedder = FakeEmbedder()
    fetch = lambda url: FakeFetchResult("HASH-1", "text/html", HTML)
    pipe = KnowledgePipeline(
        registry=None, embedder=embedder,
        doc_repo=KnowledgeDocumentRepository(),
        chunk_repo=KnowledgeChunkRepository(),
        fetch=fetch,
    )

    first = pipe.run_for_source(source)
    assert first.skipped is False
    assert first.chunks_total >= 1
    assert first.chunks_embedded == first.chunks_total
    assert len(embedder.calls) == 1

    # Re-run with identical content → content_hash gate skips everything.
    second = pipe.run_for_source(source)
    assert second.skipped is True
    assert len(embedder.calls) == 1   # embedder NOT called again

    # Corpus has exactly the first run's chunks (no duplicates).
    rows = KnowledgeChunkRepository().search_by_metadata("HUST", topic="tuition")
    assert len(rows) == first.chunks_total
```

- [ ] **Step 2: Run the integration test**

Run: `pytest tests/integration/test_knowledge_ingestion_e2e.py -v`
Expected: PASS with Postgres+pgvector up; otherwise SKIPPED with remediation message.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_knowledge_ingestion_e2e.py
git commit -m "test(knowledge): gated end-to-end idempotent ingestion test"
```

---

### Task 7: Full-suite verification + live smoke

- [ ] **Step 1: Run all Phase 3 unit tests**

Run: `pytest tests/ingestion/knowledge tests/ingestion/test_chunk_settings.py tests/services/knowledge -v`
Expected: all PASS (integration tests SKIP without DB).

- [ ] **Step 2: Confirm admission pipeline untouched**

Run: `git diff --name-only main -- ingestion/fetchers ingestion/parsers ingestion/pipeline ingestion/registry`
Expected: empty output (Phase 3 only *calls* these; never edits them).

- [ ] **Step 3: Live smoke (manual — needs DB, network, `GEMINI_API_KEY`)**

This is the real end-to-end exercise of acceptance criterion *"pipeline runs end-to-end"* and the place to validate the registry URLs from Plan 01.

```bash
docker compose up -d db
python -m db.setup_db
python -m ingestion.knowledge.pipeline --all
python -m ingestion.knowledge.verify_corpus
```

Expected: `OK ... chunks=N embedded=N reused=0` lines for reachable sources; `verify_corpus` prints non-zero counts for HUST, NEU, VNU-UET and exits 0.

If a source logs a fetch error (404/timeout), fix that URL in `ingestion/knowledge/registry/seeds/knowledge_sources.json` (correct official page for the same `document_type`/`topic`), commit the fix, and re-run. Then run once more to confirm idempotency:

```bash
python -m ingestion.knowledge.pipeline --all
```

Expected: every reachable source now prints `SKIP ... (unchanged)`.

## Deliverable

A working `python -m ingestion.knowledge.pipeline --all` that ingests the corpus with content-hash skipping and per-chunk embedding reuse, plus `python -m ingestion.knowledge.verify_corpus` for post-ingest auditing. **This completes Phase 3; Phase 4 (KnowledgeQA RAG) can now query the populated corpus.**
