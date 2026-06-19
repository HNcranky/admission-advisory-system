# Program Metadata From Seed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a chunk's `program` metadata come from the seed (reliable on any school's HTML) with the HUST breadcrumb as fallback, and use that chosen program as the chunk's contextual header — so program identity no longer depends on HUST-specific page structure.

**Architecture:** `KnowledgePipeline.run_for_source` currently sets `program` from the breadcrumb-derived `content_label` only for `by_section`. This plan flips it to seed-first (`source.program or content_label`) for every strategy, and passes the chosen program as `context_label` so the `by_section` header carries it. The `chunker` is documented (no behavior change) to make its structure-aware-with-size-fallback nature explicit.

**Tech Stack:** Python 3.12, BeautifulSoup HTML parser, pytest.

This is **Plan 2 of 3**. It is independent of Plan 1 (retrieval) and can be implemented in either order; together they let Plan 3 (NEU/UET seeds) work end-to-end.

## Global Constraints

- **Never run `git push`.** Commit only; **no `Co-Authored-By` trailer or any AI/Claude attribution** in commit messages.
- Pydantic is **v2** (`model_config = ConfigDict(...)`).
- Run tests with system Python: `python -m pytest -q` (no `.venv` in this repo).
- LLM/IO call sites must **degrade gracefully**; this plan adds no new failure modes.
- Follow existing test style: self-contained fakes (see `tests/ingestion/knowledge/test_pipeline_url.py`).

---

## File Structure

- `ingestion/knowledge/pipeline.py` — **modify**: `run_for_source` program source + `context_label` (~lines 172-182).
- `ingestion/knowledge/chunker.py` — **modify**: docstring of `chunk_by_section` / `chunk_text` `by_section` branch (clarify generality; no behavior change).
- `tests/ingestion/knowledge/test_pipeline_program_from_seed.py` — **create**.

---

### Task 1: Pipeline — program from seed, breadcrumb fallback, header uses it

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (`run_for_source`, lines ~172-182)
- Modify: `ingestion/knowledge/chunker.py` (docstrings only)
- Test: `tests/ingestion/knowledge/test_pipeline_program_from_seed.py`

**Interfaces:**
- Consumes: `KnowledgeSource.program` (existing optional field, `registry/models.py:27`), `parse_html(...).content_label` (existing).
- Produces: every chunk row's `program` = `source.program or content_label`; the `by_section` chunk header (`context_label`) = that same value.

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_pipeline_program_from_seed.py`:

```python
from ingestion.knowledge.pipeline import KnowledgePipeline
from ingestion.knowledge.registry.models import KnowledgeSource


# HTML with a HUST-style breadcrumb ("Ky thuat O to") + an <h2> section.
PAGE = (
    b"<html><head><title>T</title></head><body><div class='container'>"
    b"<ol class='breadcrumb'><li class='breadcrumb-item active'>Ky thuat O to</li></ol>"
    b"<section><h2 class='sec-title'>Co hoi viec lam</h2><p>Ky su van hanh.</p></section>"
    b"</div></body></html>"
)


class FakeFetch:
    def __init__(self, content):
        self.raw_content = content
        self.content_type = "text/html"
        self.content_hash = "h1"


class FakeDocRepo:
    def __init__(self):
        self.marked = []

    def get_document_by_url(self, url):
        return None

    def get_or_create_document(self, doc):
        return 1

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


class FakeCache:
    def bump_version(self, key):
        return None


def _pipeline(chunk_repo):
    return KnowledgePipeline(
        registry=None, embedder=FakeEmbedder(), doc_repo=FakeDocRepo(),
        chunk_repo=chunk_repo, fetch=lambda u: FakeFetch(PAGE),
        cache_repo=FakeCache(),
    )


def _source(program):
    return KnowledgeSource(
        school="HUST", source_url="https://x/ky-thuat-o-to",
        document_type="program_overview_page", topic="program_overview",
        chunk_strategy="by_section", program=program, selector="div.container",
    )


def test_seed_program_wins_over_breadcrumb():
    chunk_repo = FakeChunkRepo()
    _pipeline(chunk_repo).run_for_source(_source(program="Kỹ thuật Ô tô (canonical)"))
    assert chunk_repo.upserts, "expected chunks"
    assert all(c.program == "Kỹ thuật Ô tô (canonical)" for c in chunk_repo.upserts)
    # header uses the seed program, not the breadcrumb
    assert chunk_repo.upserts[0].chunk_text.startswith("Kỹ thuật Ô tô (canonical) — ")


def test_breadcrumb_used_when_seed_program_absent():
    chunk_repo = FakeChunkRepo()
    _pipeline(chunk_repo).run_for_source(_source(program=None))
    assert chunk_repo.upserts
    assert all(c.program == "Ky thuat O to" for c in chunk_repo.upserts)
    assert chunk_repo.upserts[0].chunk_text.startswith("Ky thuat O to — ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ingestion/knowledge/test_pipeline_program_from_seed.py -v`
Expected: FAIL — `test_seed_program_wins_over_breadcrumb` fails because today `program = content_label` for `by_section`, so `chunk.program == "Ky thuat O to"` (breadcrumb) instead of the seed value.

- [ ] **Step 3: Make program seed-first in `run_for_source`**

In `ingestion/knowledge/pipeline.py`, replace lines ~172-182:

```python
        strategy = getattr(source, "chunk_strategy", "size")
        # by_section uses the page label as both the chunk header and program tag
        program = content_label if strategy == "by_section" else source.program
        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text,
            school=source.school, topic=source.topic, program=program,
            year=source.year, document_type=source.document_type,
            source_url=source.source_url,
            chunk_strategy=strategy,
            context_label=content_label,
        )
```

with:

```python
        strategy = getattr(source, "chunk_strategy", "size")
        # Program identity is seed-first (reliable on any school's HTML); the
        # HUST breadcrumb-derived content_label is a fallback. The chunk header
        # (context_label) carries the same chosen program so by_section embeds
        # program identity regardless of page structure.
        program = source.program or content_label
        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text,
            school=source.school, topic=source.topic, program=program,
            year=source.year, document_type=source.document_type,
            source_url=source.source_url,
            chunk_strategy=strategy,
            context_label=program,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ingestion/knowledge/test_pipeline_program_from_seed.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Clarify the chunker docstring (no behavior change)**

In `ingestion/knowledge/chunker.py`, update the `chunk_by_section` docstring (line ~79) and the `by_section` bullet in `chunk_text` (lines ~111-113) to state the generality. Replace the `chunk_by_section` docstring line:

```python
    """Split markdown text on '## ' headings; prepend '{label} — {section}'."""
```

with:

```python
    """Structure-aware chunking with a size-split fallback.

    Splits markdown text on '## ' headings when present; each section becomes a
    chunk prefixed with '{label} — {section}'. When the page has NO '## '
    headings (e.g. free-prose NEU/UET overviews), the whole body is size-split
    via split_into_chunks, each part prefixed with just '{label}'. So the
    strategy never degrades below size chunking and always carries the program
    label — it is not HUST-section-specific despite the name.
    """
```

- [ ] **Step 6: Run the full chunker + pipeline suites (no regressions)**

Run: `python -m pytest tests/ingestion/knowledge/test_chunker.py tests/ingestion/knowledge/test_pipeline.py tests/ingestion/knowledge/test_pipeline_url.py tests/ingestion/test_pipeline_section_chunking.py -q`
Expected: PASS — existing behavior unchanged.

- [ ] **Step 7: Commit**

```bash
git add ingestion/knowledge/pipeline.py ingestion/knowledge/chunker.py tests/ingestion/knowledge/test_pipeline_program_from_seed.py
git commit -m "feat(knowledge): seed-first program metadata + program-labeled chunk header"
```

---

## Self-Review Notes (coverage map)

- Spec §1 program-from-seed → Task 1 Step 3; `context_label=program` → Task 1 Step 3; convention (seed program = canonical) documented in the spec, enforced by seed authors in Plan 3.
- Spec §2 chunker documented-as-general, no behavior change → Task 1 Step 5; existing `by_section` size-fallback verified by the existing `test_chunker.py` (Step 6).
- HUST-unchanged guarantee covered by `test_breadcrumb_used_when_seed_program_absent` (seeds with no `program` still use the breadcrumb).
- No placeholders; the only doc-only step (Step 5) is a docstring, not a code contract.
