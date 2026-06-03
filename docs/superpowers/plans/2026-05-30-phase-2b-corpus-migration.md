# Phase 2B — Knowledge Corpus Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `knowledge_documents` and `knowledge_chunks` tables (plus the `vector` extension and the metadata + HNSW indexes) via one idempotent SQL migration, integrated into the existing migration runner.

**Architecture:** Add `db/migrations/013_knowledge_corpus.sql` — picked up automatically by `db/setup_db.py`'s glob runner. The migration is idempotent (`CREATE ... IF NOT EXISTS`). A gated integration test asserts the schema objects exist after `python -m db.setup_db`, auto-skipping when no DB is reachable.

**Tech Stack:** PostgreSQL 16 + pgvector, raw SQL migrations, `db/setup_db.py`, pytest (`integration` marker).

**Prerequisite:** Plan **2A** must be done first (the `pgvector/pgvector:pg16` image must be running, otherwise `CREATE EXTENSION vector` fails). Do this **before** Plan 2C.

---

### Task 1: Failing integration test for the corpus schema

**Files:**
- Create: `tests/integration/test_knowledge_corpus_migration.py`

This test uses the existing `db_available` fixture from `tests/integration/conftest.py`, which auto-skips when Postgres is unreachable.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_knowledge_corpus_migration.py`:

```python
import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG

pytestmark = pytest.mark.integration


def _fetch_scalar(sql, params=None):
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_vector_extension_installed(db_available):
    assert _fetch_scalar(
        "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'"
    ) == 1


def test_knowledge_tables_exist(db_available):
    for table in ("knowledge_documents", "knowledge_chunks"):
        assert _fetch_scalar(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        ) == 1, f"missing table {table}"


def test_metadata_and_vector_indexes_exist(db_available):
    for index in (
        "idx_knowledge_chunks_school_topic",
        "idx_knowledge_chunks_embedding",
    ):
        assert _fetch_scalar(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = %s",
            (index,),
        ) == 1, f"missing index {index}"


def test_embedding_column_is_768_dim_vector(db_available):
    # pgvector stores the dimension in pg_attribute.atttypmod for the column.
    atttypmod = _fetch_scalar(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'knowledge_chunks' AND a.attname = 'embedding'
        """
    )
    assert atttypmod == 768
```

- [ ] **Step 2: Run test to verify it fails**

Ensure the DB is up (`docker compose up -d db`), then run:

Run: `python -m pytest tests/integration/test_knowledge_corpus_migration.py -v`
Expected: FAIL (tables/indexes do not exist yet). If the DB is **not** running, the tests SKIP instead — start the DB so you see real failures before implementing.

---

### Task 2: Write the migration

**Files:**
- Create: `db/migrations/013_knowledge_corpus.sql`

- [ ] **Step 1: Write the migration SQL**

Create `db/migrations/013_knowledge_corpus.sql`:

```sql
-- Knowledge corpus: unstructured documents + embedded chunks for RAG.
-- Separate from raw_documents (admission fetch pipeline) on purpose.
-- embedding is vector(768) — must match ingestion.config.settings.EMBEDDING_DIM.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id              SERIAL PRIMARY KEY,
    school          TEXT NOT NULL,
    document_type   TEXT NOT NULL,          -- tuition_page | curriculum_pdf | faq | handbook | scholarship_policy
    source_url      TEXT NOT NULL UNIQUE,   -- UNIQUE → re-fetch upserts, no duplicates
    content_hash    TEXT,
    raw_text        TEXT,
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id                    SERIAL PRIMARY KEY,
    knowledge_document_id INTEGER REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    school                TEXT NOT NULL,
    program               TEXT,
    year                  INTEGER,
    document_type         TEXT,
    topic                 TEXT,             -- tuition | curriculum | scholarship | dormitory | career | ...
    chunk_text            TEXT NOT NULL,
    embedding             vector(768),      -- nullable: allows chunk-then-embed / re-embed
    source_url            TEXT,
    span_start            INTEGER,
    span_end              INTEGER,
    ingested_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_url, span_start, span_end)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_school_topic
    ON knowledge_chunks (school, topic);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
```

- [ ] **Step 2: Apply migrations**

Run: `python -m db.setup_db`
Expected: console shows `013_knowledge_corpus.sql applied` with no error. (Earlier migrations report "already exists"-style success; that's the idempotent path.)

- [ ] **Step 3: Run the integration test to verify it passes**

Run: `python -m pytest tests/integration/test_knowledge_corpus_migration.py -v`
Expected: PASS (4 passed) — extension, both tables, both indexes, and the 768-dim embedding column all present.

- [ ] **Step 4: Verify idempotency (re-run is safe)**

Run: `python -m db.setup_db`
Expected: `013_knowledge_corpus.sql applied` again with no error (all statements are `IF NOT EXISTS`). Re-run the test once more — still PASS.

- [ ] **Step 5: Commit**

```bash
git add db/migrations/013_knowledge_corpus.sql tests/integration/test_knowledge_corpus_migration.py
git commit -m "$(cat <<'EOF'
feat(db): add knowledge corpus migration (013)

Create knowledge_documents + knowledge_chunks with the vector extension,
a (school, topic) btree index, and an HNSW cosine index on vector(768).
Idempotent; gated integration test asserts the schema after setup_db.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Register the new tables in setup_db verification

**Files:**
- Modify: `db/setup_db.py` (the `expected` list inside `verify_tables()`, around lines 101-111)

- [ ] **Step 1: Add the tables to the expected list**

In `db/setup_db.py`, inside `verify_tables()`, extend the `expected` list to include the two new tables:

```python
    expected = [
    "source_registry",
    "discovered_resources",
    "raw_documents",
    "extracted_facts",
    "canonical_admission_records",
    "advisory_runs",
    "chat_sessions",
    "chat_messages",
    "chat_advisory_runs",
    "knowledge_documents",
    "knowledge_chunks",
]
```

- [ ] **Step 2: Verify the table report is green**

Run: `python -m db.setup_db`
Expected: in the "Tables in 'admission'" report, both `knowledge_documents` and `knowledge_chunks` show `✅`, and the run ends with `✅ Setup complete!`.

- [ ] **Step 3: Commit**

```bash
git add db/setup_db.py
git commit -m "$(cat <<'EOF'
chore(db): verify knowledge corpus tables in setup_db

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

- **Spec coverage:** Implements spec §1 (schema/migration `013`), §2 (both indexes), and §5's `db/setup_db.py` verify-list change. Acceptance criteria "migration idempotent + integrated", "both indexes exist", and "HNSW works with vector(768)" are each asserted by a test in Task 1.
- **Placeholders:** none — full SQL and full test code provided.
- **Type consistency:** Table names (`knowledge_documents`, `knowledge_chunks`), index names (`idx_knowledge_chunks_school_topic`, `idx_knowledge_chunks_embedding`), and the `vector(768)` column match the names Plan 2C's repository queries against. The `768` literal matches `EMBEDDING_DIM` from Plan 2A.
