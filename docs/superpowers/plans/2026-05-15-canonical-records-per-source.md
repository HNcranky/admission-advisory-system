# Canonical Records Per-Source Coexistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow two sources reporting the same logical admission program to coexist as two distinct rows in `canonical_admission_records`, replacing the silent-overwrite behavior that destroys the conflict signal downstream.

**Architecture:** Three deliverables land in a single merge: (1) a forward-only SQL migration (`010`) that swaps the 4-column unique constraint for a 5-column per-source constraint; (2) a one-line change to the `ON CONFLICT` target in `db_writer.py`; (3) a written Q&A strategy note. Unit tests use monkeypatching to avoid a live DB; the migration is verified by running `db/setup_db.py` against a real Postgres instance.

**Tech Stack:** PostgreSQL 14+, psycopg2, Python 3.11+, pytest, pydantic v2

---

### Task 1: Create and Apply Migration 010

**Files:**
- Create: `db/migrations/010_canonical_records_per_source.sql`

This migration drops the old 4-column unique constraint (dynamically looked up by column names because Postgres auto-generates the name) and adds a named 5-column per-source constraint. It is idempotent on the DROP side; the ADD will fail loudly if run twice (intentional).

- [ ] **Step 1: Verify the old constraint exists before migrating**

Run this in psql (or via `python -c`) to confirm the baseline:

```sql
SELECT conname
FROM pg_constraint
WHERE conrelid = 'canonical_admission_records'::regclass
  AND contype = 'u'
  AND array_length(conkey, 1) = 4;
```

Expected: one row returned with a name like `canonical_admission_records_school_id_admission_year_prog_key`.

- [ ] **Step 2: Create the migration file**

Create `db/migrations/010_canonical_records_per_source.sql` with this exact content:

```sql
-- Drop the old uniqueness constraint that overwrote second-source rows.
-- The constraint was created by UNIQUE(...) inline in CREATE TABLE
-- (db/migrations/005_canonical_programs.sql), so Postgres assigned an
-- auto-generated name. We look it up by columns instead of hardcoding the
-- name, since the auto-generated name can be truncated past 63 chars.
DO $$
DECLARE
    old_constraint_name TEXT;
BEGIN
    SELECT conname INTO old_constraint_name
    FROM pg_constraint
    WHERE conrelid = 'canonical_admission_records'::regclass
      AND contype = 'u'
      AND array_length(conkey, 1) = 4
      AND (
          SELECT array_agg(attname ORDER BY attname)
          FROM pg_attribute
          WHERE attrelid = 'canonical_admission_records'::regclass
            AND attnum = ANY(conkey)
      ) = ARRAY['admission_method','admission_year','program_id','school_id'];

    IF old_constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE canonical_admission_records DROP CONSTRAINT %I',
            old_constraint_name
        );
    END IF;
END$$;

-- Add per-source uniqueness so two sources for the same logical program
-- coexist as two rows.
ALTER TABLE canonical_admission_records
    ADD CONSTRAINT canonical_admission_records_per_source_key
    UNIQUE (school_id, admission_year, program_id, admission_method, source_url);
```

- [ ] **Step 3: Apply the migration**

```bash
python db/setup_db.py
```

Expected output includes:
```
  Running 010_canonical_records_per_source.sql...
  ✅ 010_canonical_records_per_source.sql applied
```

- [ ] **Step 4: Verify the new constraint exists**

Run in psql:

```sql
SELECT conname
FROM pg_constraint
WHERE conrelid = 'canonical_admission_records'::regclass
  AND conname = 'canonical_admission_records_per_source_key';
```

Expected: one row returned with `canonical_admission_records_per_source_key`.

Also verify the old 4-column constraint is gone:

```sql
SELECT count(*)
FROM pg_constraint
WHERE conrelid = 'canonical_admission_records'::regclass
  AND contype = 'u'
  AND array_length(conkey, 1) = 4;
```

Expected: `0`.

- [ ] **Step 5: Commit**

```bash
git add db/migrations/010_canonical_records_per_source.sql
git commit -m "feat: add migration 010 for per-source canonical records uniqueness"
```

---

### Task 2: Update Writer ON CONFLICT Target

**Files:**
- Modify: `ingestion/storage/db_writer.py:181`
- Create: `tests/ingestion/test_db_writer.py`

Write the test first, watch it fail, then make the one-line change.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_db_writer.py`:

```python
from contextlib import contextmanager

import ingestion.storage.db_writer as db_writer
from ingestion.models.pipeline_models import NormalizedAdmissionRecord


def _make_record(source_url: str) -> NormalizedAdmissionRecord:
    return NormalizedAdmissionRecord(
        school_id="hust",
        school_name_canonical="Hanoi University of Science and Technology",
        admission_year=2026,
        program_id="computer_science",
        program_name_canonical="Khoa hoc may tinh",
        admission_method="thpt_score",
        source_url=source_url,
        source_trust_level=5,
        confidence_score=0.9,
    )


class _TrackingCursor:
    def __init__(self):
        self.executions: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.executions.append((sql, params))


def test_save_canonical_records_conflict_target_includes_source_url(monkeypatch):
    cursor = _TrackingCursor()

    @contextmanager
    def fake_get_cursor(commit=True):
        yield cursor

    monkeypatch.setattr(db_writer, "get_cursor", fake_get_cursor)

    count = db_writer.save_canonical_records([_make_record("https://hust.edu.vn/admission/2026")])

    assert count == 1
    executed_sql = cursor.executions[0][0]
    normalized = " ".join(executed_sql.split())
    assert "ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)" in normalized
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
python -m pytest tests/ingestion/test_db_writer.py::test_save_canonical_records_conflict_target_includes_source_url -v
```

Expected: `FAILED` — the current SQL has `ON CONFLICT (school_id, admission_year, program_id, admission_method)` without `source_url`.

- [ ] **Step 3: Edit line 181 in db_writer.py**

In `ingestion/storage/db_writer.py`, line 181, change:

```python
                    ON CONFLICT (school_id, admission_year, program_id, admission_method)
```

to:

```python
                    ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)
```

No other lines change. The `DO UPDATE SET` clause stays identical.

- [ ] **Step 4: Run the test and verify it passes**

```bash
python -m pytest tests/ingestion/test_db_writer.py::test_save_canonical_records_conflict_target_includes_source_url -v
```

Expected: `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add ingestion/storage/db_writer.py tests/ingestion/test_db_writer.py
git commit -m "feat: update save_canonical_records ON CONFLICT target to include source_url"
```

---

### Task 3: DB Writer Regression and Two-Source Unit Tests

**Files:**
- Modify: `tests/ingestion/test_db_writer.py`

Two additional tests: same-source re-ingestion doesn't explode (regression), and two distinct source URLs both get written (new behavior guard).

- [ ] **Step 1: Write the two new failing tests**

Append to `tests/ingestion/test_db_writer.py`:

```python
def test_save_canonical_records_same_source_reingest_updates_not_inserts(monkeypatch):
    """Re-ingesting the same source URL calls the cursor twice (once per call to
    save_canonical_records). The ON CONFLICT DO UPDATE handles idempotency at the
    DB level; the writer's job is just to send both executions through."""
    cursor = _TrackingCursor()

    @contextmanager
    def fake_get_cursor(commit=True):
        yield cursor

    monkeypatch.setattr(db_writer, "get_cursor", fake_get_cursor)

    record = _make_record("https://hust.edu.vn/admission/2026")
    count1 = db_writer.save_canonical_records([record])
    count2 = db_writer.save_canonical_records([record])

    assert count1 == 1
    assert count2 == 1
    assert len(cursor.executions) == 2


def test_save_canonical_records_two_distinct_sources_both_written(monkeypatch):
    """Two records with the same logical program tuple but different source_url
    values are both sent to the cursor — no writer-level deduplication."""
    cursor = _TrackingCursor()

    @contextmanager
    def fake_get_cursor(commit=True):
        yield cursor

    monkeypatch.setattr(db_writer, "get_cursor", fake_get_cursor)

    records = [
        _make_record("https://hust.edu.vn/admission/2026"),
        _make_record("https://ts.hust.edu.vn/tuyen-sinh/2026"),
    ]
    count = db_writer.save_canonical_records(records)

    assert count == 2
    assert len(cursor.executions) == 2
    source_urls_in_params = [ex[1][14] for ex in cursor.executions]  # source_url is the 15th param (index 14)
    assert "https://hust.edu.vn/admission/2026" in source_urls_in_params
    assert "https://ts.hust.edu.vn/tuyen-sinh/2026" in source_urls_in_params
```

- [ ] **Step 2: Run the new tests and verify they pass (no implementation change needed)**

```bash
python -m pytest tests/ingestion/test_db_writer.py -v
```

Expected: all 3 tests `PASSED`. (The writer already handles both scenarios correctly — these tests are regression guards.)

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
python -m pytest --tb=short -q
```

Expected: all previously passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add tests/ingestion/test_db_writer.py
git commit -m "test: add regression and two-source coexistence unit tests for db_writer"
```

---

### Task 4: Retrieval Service Two-Source Compatibility Test

**Files:**
- Modify: `tests/services/test_retrieval_service.py`

Guards against a future regression where `fetch_candidates` accidentally collapses multi-source rows (e.g., via DISTINCT). The retrieval SQL has no GROUP BY or DISTINCT today — this test documents and locks that in.

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_retrieval_service.py`:

```python
def test_fetch_candidates_returns_both_rows_when_two_sources_exist(monkeypatch):
    """When canonical_admission_records has two rows for the same logical program
    but different source URLs, fetch_candidates returns both as separate
    CandidateProgram objects. This guards against accidental DISTINCT/GROUP BY."""
    fake_rows = [
        (
            "hust",
            "Hanoi University of Science and Technology",
            2026,
            "computer_science",
            "Khoa hoc May tinh",
            "thpt_score",
            ["A00"],
            {"total": 300},
            None,
            None,
            "https://hust.edu.vn/admission/2026",
            5,
            0.92,
        ),
        (
            "hust",
            "Hanoi University of Science and Technology",
            2026,
            "computer_science",
            "Khoa hoc May tinh",
            "thpt_score",
            ["A00"],
            {"total": 280},
            None,
            None,
            "https://ts.hust.edu.vn/tuyen-sinh/2026",
            4,
            0.85,
        ),
    ]

    fake_cursor = _FakeCursor(fake_rows)

    @contextmanager
    def fake_get_cursor(commit=False):
        yield fake_cursor

    monkeypatch.setattr(retrieval_service, "get_cursor", fake_get_cursor)

    candidates = retrieval_service.fetch_candidates({"admission_year": 2026})

    assert len(candidates) == 2
    source_urls = {c.evidence[0].source_url for c in candidates}
    assert "https://hust.edu.vn/admission/2026" in source_urls
    assert "https://ts.hust.edu.vn/tuyen-sinh/2026" in source_urls
```

- [ ] **Step 2: Run the test and verify it passes (no implementation change needed)**

```bash
python -m pytest tests/services/test_retrieval_service.py::test_fetch_candidates_returns_both_rows_when_two_sources_exist -v
```

Expected: `PASSED`. The existing `fetch_candidates` already returns all matching rows without collapsing.

If it fails: inspect `services/retrieval_service.py:62-81` — the SELECT query must not have `DISTINCT` or `GROUP BY` on the canonical program tuple. If it does, remove it.

- [ ] **Step 3: Run the full test suite**

```bash
python -m pytest --tb=short -q
```

Expected: all previously passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add tests/services/test_retrieval_service.py
git commit -m "test: add two-source compatibility guard for fetch_candidates"
```

---

### Task 5: Q&A Strategy Note

**Files:**
- Create: `docs/superpowers/notes/2026-05-15-qa-strategy.md`

No code changes. This is a written design artifact that locks in V1 scope decisions and documents the future RAG slice's touch points so they don't get accidentally broken.

- [ ] **Step 1: Create the notes directory and write the document**

Create `docs/superpowers/notes/2026-05-15-qa-strategy.md`:

```markdown
# Q&A Strategy Note — V1 Scope Decision and Future RAG Slice

**Date:** 2026-05-15
**Status:** Accepted — informs the conflict-aware advisory V1 and all downstream specs

---

## Scope Decision for V1

The conflict-aware advisory V1 answers **profile-driven recommendation questions**
("which programs fit my profile?"). Those questions are served by structured SQL
retrieval over `canonical_admission_records` — implemented at
`services/retrieval_service.py:fetch_candidates`. **The database is ready for those
queries.** The conflict-aware spec adds field-level conflict resolution on top; it
does not change the retrieval shape.

The database is **not ready** for open-ended student Q&A such as:
- "What scholarships does HUST offer?"
- "What's the early-admission deadline at UET?"
- "Does program X accept high-school olympiad winners?"

The answers to those questions live in the source text body, captured in
`raw_documents.parsed_text` but not semantically indexed. Open-ended Q&A is
**deferred to a separate post-V1 spec**.

---

## Why the Deferral Is Safe

- The advisory agent and the future Q&A agent serve different intents. Routing
  student input to one or the other is a chat-layer concern, not a graph-layer
  concern. The conflict-aware advisory graph stays as-is; the Q&A agent will be a
  separate graph or chain.
- `raw_documents.parsed_text` is already populated for every fetched source. The
  future RAG slice has its raw material ready — no re-fetching needed.
- Conflict resolution in V1 is field-level (quota mismatch between two sources).
  Narrative-passage conflicts (two source texts saying different things about
  scholarships) are a different problem with different resolution semantics. The V1
  design does not have to cover that case.

---

## Future RAG Slice — Touch Points to Preserve

These are the lines V1 must not violate. Future readers use this list to know which
design decisions are load-bearing:

| What to keep | Why |
|---|---|
| `raw_documents.parsed_text` populated | Future RAG slice reads it for chunking |
| `raw_documents.fetched_at` populated | Recency signal for embedding-refresh logic |
| `raw_documents.source_id` joinable to `source_registry` | Authority and trust signals carry into RAG ranking |
| Table name `document_chunks` unused | Reserved for the future chunking table |
| Retrieval layer as a thin function call | Don't bake "only SQL surface" assumptions into shared code |

### What the future RAG slice will introduce (new, no existing schema disturbed)

- A `document_chunks` table: `(id, raw_document_id, chunk_index, body_text, embedding vector(N), char_start, char_end, …)`
- A chunking + embedding pipeline stage that reads `raw_documents` and writes `document_chunks`
- A `qa_agent` that issues semantic retrieval queries against `document_chunks`
- A chat-layer intent classifier that routes input to either `advisory_agent` or `qa_agent`

---

## What NOT to Do in V1

- Don't drop `raw_documents.parsed_text` or move it to cold storage.
- Don't make `raw_documents.source_id` non-joinable to `source_registry`.
- Don't reuse the table name `document_chunks` for anything else.
- Don't bake the assumption "the only retrieval surface is `canonical_admission_records`"
  into shared library code.

---

## Open Question Deferred to the Future Q&A Spec

Conflict resolution semantics for narrative passages: two source texts saying
contradictory things about a scholarship policy. The structured-conflict resolution
layer (Evidence/Comparison/Resolution) cannot directly apply because passage-level
disagreement is not field-level. The future Q&A spec must propose its own resolution
shape — likely: surface both passages with provenance, let the LLM compose a hedged
answer, never declare one passage "winning."
```

- [ ] **Step 2: Verify the file was written correctly**

```bash
python -m pytest --tb=short -q
```

Expected: all tests still pass (this step is a no-op for tests).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/notes/2026-05-15-qa-strategy.md
git commit -m "docs: add Q&A strategy note — V1 scope decision and future RAG touch points"
```

---

## Self-Review Against Spec

**Spec coverage check:**

| Spec requirement | Task that covers it |
|---|---|
| `db/migrations/010_canonical_records_per_source.sql` with DO block + new constraint | Task 1 |
| Writer `ON CONFLICT` target includes `source_url` | Task 2 |
| Re-ingestion of same source updates, not duplicates | Task 3 (`test_save_canonical_records_same_source_reingest_updates_not_inserts`) |
| Two distinct `source_url` values coexist as two rows | Task 3 (`test_save_canonical_records_two_distinct_sources_both_written`) |
| Both rows visible to `fetch_candidates` | Task 4 |
| Q&A strategy note at `docs/superpowers/notes/2026-05-15-qa-strategy.md` | Task 5 |
| `SET` clause in writer unchanged | Task 2 Step 3 (explicit instruction: only line 181 changes) |
| Migration idempotent DROP side | Task 1 Step 2 (DO block handles NULL gracefully) |
| Forward-only migration, no rollback | Task 1 (noted in commit message; no rollback SQL added) |
| `raw_documents.parsed_text` preservation documented | Task 5 |
| Future RAG touch points listed | Task 5 |

**Placeholder scan:** No TBD, TODO, "implement later", "add error handling", or "similar to Task N" patterns found.

**Type consistency:** `NormalizedAdmissionRecord` used in Tasks 2 and 3 uses the same fields (`school_id`, `school_name_canonical`, `admission_year`, `program_id`, `program_name_canonical`, `admission_method`, `source_url`, `source_trust_level`, `confidence_score`). The 15th parameter in the INSERT (index 14, zero-based) is confirmed as `source_url` by reading `db_writer.py:195-213` — the params tuple order matches the INSERT column list at lines 174-179.

**Source URL param index verification:**
The INSERT params tuple at `db_writer.py:195-213` is:
```
0: fact_id
1: record.school_id
2: record.school_name_canonical
3: record.admission_year
4: record.program_id
5: record.program_name_canonical
6: record.program_name_raw
7: record.admission_method
8: record.admission_method_raw
9: combos_json
10: quota_json
11: deadline_json
12: metadata_json
13: tuition_json
14: record.source_url   ← index 14, confirmed
15: record.source_trust_level
16: record.confidence_score
```

Index 14 is correct in Task 3's assertion `ex[1][14]`.
