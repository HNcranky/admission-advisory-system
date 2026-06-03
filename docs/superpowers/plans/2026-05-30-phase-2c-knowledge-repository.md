# Phase 2C — KnowledgeChunkRepository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `services/knowledge/` package with Pydantic models and a `KnowledgeChunkRepository` exposing `upsert_chunk`, `search_by_metadata`, and `vector_search` over the corpus tables.

**Architecture:** Mirror the existing `services/chat/repository.py` pattern exactly — plain psycopg2, connection-per-call, an injectable `connection_factory` (so logic is unit-testable with a fake connection), and Pydantic models. Embeddings are passed to Postgres as a `'[...]'` string cast with `%s::vector` (psycopg2 would otherwise adapt a Python list to a Postgres array, not a vector). Metadata filter and ANN scan happen in one query in `vector_search`.

**Tech Stack:** Python, psycopg2, Pydantic, PostgreSQL + pgvector, pytest (`integration` marker for the gated round-trip).

**Prerequisite:** Plans **2A** and **2B** must be done first — the repository queries tables and indexes created by migration `013`, and the round-trip test needs the pgvector image running.

---

### Task 1: Package scaffold — models + connection helper

**Files:**
- Create: `services/knowledge/__init__.py`
- Create: `services/knowledge/db.py`
- Create: `services/knowledge/models.py`
- Test: `tests/services/knowledge/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/services/knowledge/test_models.py`:

```python
from services.knowledge.models import KnowledgeChunk, ScoredChunk


def test_knowledge_chunk_minimal_requires_only_school_and_text():
    chunk = KnowledgeChunk(school="VNU-UET", chunk_text="Học phí 2024...")
    assert chunk.school == "VNU-UET"
    assert chunk.topic is None
    assert chunk.embedding is None


def test_scored_chunk_extends_knowledge_chunk_with_score():
    scored = ScoredChunk(school="HUST", chunk_text="x", score=0.87)
    assert isinstance(scored, KnowledgeChunk)
    assert scored.score == 0.87
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/knowledge/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.knowledge'`.

- [ ] **Step 3: Create the package files**

Create `services/knowledge/__init__.py` (empty file).

Create `services/knowledge/db.py`:

```python
import psycopg2

from ingestion.config.settings import DB_CONFIG


def get_knowledge_db_connection():
    return psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database=DB_CONFIG["database"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
```

Create `services/knowledge/models.py`:

```python
from pydantic import BaseModel


class KnowledgeChunk(BaseModel):
    school: str
    topic: str | None = None
    program: str | None = None
    year: int | None = None
    document_type: str | None = None
    chunk_text: str
    embedding: list[float] | None = None
    source_url: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    knowledge_document_id: int | None = None


class ScoredChunk(KnowledgeChunk):
    score: float    # cosine similarity in [−1, 1]; Phase 4 thresholds on this
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/knowledge/test_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/__init__.py services/knowledge/db.py services/knowledge/models.py tests/services/knowledge/test_models.py
git commit -m "$(cat <<'EOF'
feat(knowledge): scaffold corpus package with chunk models

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `upsert_chunk`

**Files:**
- Create: `services/knowledge/repository.py`
- Test: `tests/services/knowledge/test_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/services/knowledge/test_repository.py` with the shared fakes and the first test:

```python
from services.knowledge.models import KnowledgeChunk
from services.knowledge.repository import KnowledgeChunkRepository


class FakeCursor:
    def __init__(self, fetchone_return=None, fetchall_return=None):
        self.statements = []
        self._fetchone = fetchone_return
        self._fetchall = fetchall_return or []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall

    def close(self):
        return None


class FakeConnection:
    def __init__(self, fetchone_return=None, fetchall_return=None):
        self.cursor_obj = FakeCursor(fetchone_return, fetchall_return)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def _repo(connection):
    return KnowledgeChunkRepository(connection_factory=lambda: connection)


def test_upsert_chunk_inserts_with_on_conflict_and_returns_id():
    connection = FakeConnection(fetchone_return=(42,))
    repo = _repo(connection)

    chunk = KnowledgeChunk(
        school="VNU-UET",
        topic="tuition",
        chunk_text="Học phí năm 2024 là ...",
        embedding=[0.1, 0.2, 0.3],
        source_url="http://uet/tuition",
        span_start=0,
        span_end=120,
    )
    chunk_id = repo.upsert_chunk(chunk)

    sql, params = connection.cursor_obj.statements[0]
    assert chunk_id == 42
    assert "INSERT INTO knowledge_chunks" in sql
    assert "ON CONFLICT (source_url, span_start, span_end) DO UPDATE" in sql
    assert "%s::vector" in sql
    # embedding is passed as a pgvector text literal, not a Python list
    assert "[0.1,0.2,0.3]" in params
    assert connection.committed is True


def test_upsert_chunk_passes_null_embedding_as_none():
    connection = FakeConnection(fetchone_return=(7,))
    repo = _repo(connection)

    repo.upsert_chunk(KnowledgeChunk(school="HUST", chunk_text="no embedding yet"))

    _, params = connection.cursor_obj.statements[0]
    assert None in params  # embedding literal is None → SQL NULL::vector
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/knowledge/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.knowledge.repository'`.

- [ ] **Step 3: Create the repository with `upsert_chunk`**

Create `services/knowledge/repository.py`:

```python
from services.knowledge.db import get_knowledge_db_connection
from services.knowledge.models import KnowledgeChunk, ScoredChunk


def _vector_literal(embedding):
    """Render a float list as a pgvector text literal '[a,b,c]', or None.

    psycopg2 adapts a Python list to a Postgres array, so we must hand it a
    string and cast it with %s::vector in the SQL.
    """
    if embedding is None:
        return None
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


class KnowledgeChunkRepository:
    def __init__(self, connection_factory=get_knowledge_db_connection):
        self.connection_factory = connection_factory

    def upsert_chunk(self, chunk: KnowledgeChunk) -> int:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_chunks
                (knowledge_document_id, school, program, year, document_type,
                 topic, chunk_text, embedding, source_url, span_start, span_end)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
            ON CONFLICT (source_url, span_start, span_end) DO UPDATE SET
                knowledge_document_id = EXCLUDED.knowledge_document_id,
                school        = EXCLUDED.school,
                program       = EXCLUDED.program,
                year          = EXCLUDED.year,
                document_type = EXCLUDED.document_type,
                topic         = EXCLUDED.topic,
                chunk_text    = EXCLUDED.chunk_text,
                embedding     = EXCLUDED.embedding,
                ingested_at   = NOW()
            RETURNING id
            """,
            (
                chunk.knowledge_document_id,
                chunk.school,
                chunk.program,
                chunk.year,
                chunk.document_type,
                chunk.topic,
                chunk.chunk_text,
                _vector_literal(chunk.embedding),
                chunk.source_url,
                chunk.span_start,
                chunk.span_end,
            ),
        )
        chunk_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return chunk_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/knowledge/test_repository.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/repository.py tests/services/knowledge/test_repository.py
git commit -m "$(cat <<'EOF'
feat(knowledge): add KnowledgeChunkRepository.upsert_chunk

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `search_by_metadata`

**Files:**
- Modify: `services/knowledge/repository.py`
- Test: `tests/services/knowledge/test_repository.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/services/knowledge/test_repository.py`:

```python
def _chunk_row(id=1, school="VNU-UET", topic="tuition"):
    # Column order: id, knowledge_document_id, school, program, year,
    # document_type, topic, chunk_text, source_url, span_start, span_end
    return (id, None, school, None, None, "tuition_page", topic,
            "chunk text", "http://uet/tuition", 0, 120)


def test_search_by_metadata_filters_school_only_when_topic_omitted():
    connection = FakeConnection(fetchall_return=[_chunk_row()])
    repo = _repo(connection)

    results = repo.search_by_metadata("VNU-UET")

    sql, params = connection.cursor_obj.statements[0]
    assert "WHERE school = %s" in sql
    assert "topic = %s" not in sql
    assert params == ("VNU-UET", 20)            # default limit
    assert results[0].school == "VNU-UET"
    assert results[0].chunk_text == "chunk text"


def test_search_by_metadata_adds_topic_clause_when_given():
    connection = FakeConnection(fetchall_return=[_chunk_row()])
    repo = _repo(connection)

    repo.search_by_metadata("VNU-UET", topic="tuition", limit=5)

    sql, params = connection.cursor_obj.statements[0]
    assert "WHERE school = %s" in sql
    assert "AND topic = %s" in sql
    assert params == ("VNU-UET", "tuition", 5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/knowledge/test_repository.py -k search_by_metadata -v`
Expected: FAIL with `AttributeError: 'KnowledgeChunkRepository' object has no attribute 'search_by_metadata'`.

- [ ] **Step 3: Add the shared column list, row mapper, and method**

In `services/knowledge/repository.py`, add this module-level constant just below `_vector_literal`:

```python
# SELECT column order shared by the read methods (id is selected separately).
_CHUNK_COLUMNS = (
    "knowledge_document_id, school, program, year, document_type, "
    "topic, chunk_text, source_url, span_start, span_end"
)
```

Then add these methods inside `KnowledgeChunkRepository` (after `upsert_chunk`):

```python
    @staticmethod
    def _row_to_chunk(row) -> KnowledgeChunk:
        return KnowledgeChunk(
            knowledge_document_id=row[1],
            school=row[2],
            program=row[3],
            year=row[4],
            document_type=row[5],
            topic=row[6],
            chunk_text=row[7],
            source_url=row[8],
            span_start=row[9],
            span_end=row[10],
        )

    def search_by_metadata(self, school, topic=None, limit=20):
        conn = self.connection_factory()
        cur = conn.cursor()
        sql = f"SELECT id, {_CHUNK_COLUMNS} FROM knowledge_chunks WHERE school = %s"
        params = [school]
        if topic is not None:
            sql += " AND topic = %s"
            params.append(topic)
        sql += " ORDER BY id LIMIT %s"
        params.append(limit)
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [self._row_to_chunk(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_repository.py -v`
Expected: PASS (4 passed — the two upsert tests plus the two new ones).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/repository.py tests/services/knowledge/test_repository.py
git commit -m "$(cat <<'EOF'
feat(knowledge): add KnowledgeChunkRepository.search_by_metadata

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `vector_search`

**Files:**
- Modify: `services/knowledge/repository.py`
- Test: `tests/services/knowledge/test_repository.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/services/knowledge/test_repository.py`:

```python
def _scored_row(id=1, source_url="http://uet/tuition", score=0.91):
    # _chunk_row columns + trailing score
    return _chunk_row(id=id)[:8] + (source_url,) + _chunk_row(id=id)[9:] + (score,)


def test_vector_search_builds_cosine_query_with_filters():
    connection = FakeConnection(
        fetchall_return=[_scored_row(id=1, source_url="http://uet/a", score=0.9)]
    )
    repo = _repo(connection)

    results = repo.vector_search([0.1, 0.2], school="VNU-UET", topic="tuition", limit=3)

    sql, params = connection.cursor_obj.statements[0]
    assert "1 - (embedding <=> %s::vector) AS score" in sql
    assert "ORDER BY embedding <=> %s::vector" in sql
    assert "embedding IS NOT NULL" in sql
    assert "AND school = %s" in sql
    assert "AND topic = %s" in sql
    # literal appears twice (SELECT score + ORDER BY), filters between, limit last
    assert params == ("[0.1,0.2]", "VNU-UET", "tuition", "[0.1,0.2]", 3)
    assert results[0].score == 0.9
    assert results[0].source_url == "http://uet/a"


def test_vector_search_without_filters_omits_metadata_clauses():
    connection = FakeConnection(fetchall_return=[])
    repo = _repo(connection)

    repo.vector_search([1.0, 0.0])

    sql, params = connection.cursor_obj.statements[0]
    assert "school = %s" not in sql
    assert "topic = %s" not in sql
    assert params == ("[1.0,0.0]", "[1.0,0.0]", 5)   # default limit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/knowledge/test_repository.py -k vector_search -v`
Expected: FAIL with `AttributeError: 'KnowledgeChunkRepository' object has no attribute 'vector_search'`.

- [ ] **Step 3: Add the scored-row mapper and `vector_search`**

In `services/knowledge/repository.py`, add inside `KnowledgeChunkRepository` (after `search_by_metadata`):

```python
    @staticmethod
    def _row_to_scored(row) -> ScoredChunk:
        return ScoredChunk(
            knowledge_document_id=row[1],
            school=row[2],
            program=row[3],
            year=row[4],
            document_type=row[5],
            topic=row[6],
            chunk_text=row[7],
            source_url=row[8],
            span_start=row[9],
            span_end=row[10],
            score=row[11],
        )

    def vector_search(self, embedding, school=None, topic=None, limit=5):
        literal = _vector_literal(embedding)
        conn = self.connection_factory()
        cur = conn.cursor()
        sql = (
            f"SELECT id, {_CHUNK_COLUMNS}, "
            "1 - (embedding <=> %s::vector) AS score "
            "FROM knowledge_chunks WHERE embedding IS NOT NULL"
        )
        params = [literal]
        if school is not None:
            sql += " AND school = %s"
            params.append(school)
        if topic is not None:
            sql += " AND topic = %s"
            params.append(topic)
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.append(literal)
        params.append(limit)
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [self._row_to_scored(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_repository.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/repository.py tests/services/knowledge/test_repository.py
git commit -m "$(cat <<'EOF'
feat(knowledge): add KnowledgeChunkRepository.vector_search

Single query combining metadata filter and HNSW cosine ANN scan.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Gated integration round-trip

**Files:**
- Create: `tests/services/knowledge/test_repository_integration.py`

This proves the real pgvector path end-to-end. It auto-skips when Postgres is unreachable, so the default suite stays green without a DB.

- [ ] **Step 1: Write the integration test**

Create `tests/services/knowledge/test_repository_integration.py`:

```python
import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG, EMBEDDING_DIM
from services.knowledge.models import KnowledgeChunk
from services.knowledge.repository import KnowledgeChunkRepository

pytestmark = pytest.mark.integration


def _vec(*head):
    """A full-dimension embedding: `head` values followed by zero padding."""
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


@pytest.fixture
def knowledge_repo():
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
    return KnowledgeChunkRepository()


def test_upsert_then_vector_search_round_trip(knowledge_repo):
    a = KnowledgeChunk(
        school="VNU-UET", topic="tuition", chunk_text="A",
        embedding=_vec(1.0, 0.0), source_url="http://x/a",
        span_start=0, span_end=1,
    )
    b = KnowledgeChunk(
        school="VNU-UET", topic="tuition", chunk_text="B",
        embedding=_vec(0.0, 1.0), source_url="http://x/b",
        span_start=0, span_end=1,
    )
    id_a = knowledge_repo.upsert_chunk(a)
    id_b = knowledge_repo.upsert_chunk(b)
    assert id_a != id_b

    results = knowledge_repo.vector_search(
        _vec(0.9, 0.1), school="VNU-UET", topic="tuition", limit=2
    )
    assert [r.source_url for r in results] == ["http://x/a", "http://x/b"]
    assert results[0].score >= results[1].score


def test_upsert_is_idempotent_on_source_url_span(knowledge_repo):
    chunk = KnowledgeChunk(
        school="HUST", topic="curriculum", chunk_text="v1",
        embedding=_vec(1.0), source_url="http://x/c",
        span_start=0, span_end=5,
    )
    first = knowledge_repo.upsert_chunk(chunk)
    chunk.chunk_text = "v2"
    second = knowledge_repo.upsert_chunk(chunk)
    assert first == second  # same row updated, not duplicated

    rows = knowledge_repo.search_by_metadata("HUST", topic="curriculum")
    assert len(rows) == 1
    assert rows[0].chunk_text == "v2"
```

- [ ] **Step 2: Run with the DB up to verify it passes**

Ensure the corpus schema is applied (`docker compose up -d db && python -m db.setup_db`), then run:

Run: `python -m pytest tests/services/knowledge/test_repository_integration.py -v`
Expected: PASS (2 passed). The first test confirms the closer vector ranks first; the second confirms the `(source_url, span_start, span_end)` upsert updates in place.

- [ ] **Step 3: Confirm it skips cleanly without a DB**

Run (with the DB stopped, or `DB_PORT` pointed at nothing): `python -m pytest tests/services/knowledge/test_repository_integration.py -v`
Expected: SKIPPED (2 skipped) with the remediation message — no errors.

- [ ] **Step 4: Run the whole knowledge suite**

Run: `python -m pytest tests/services/knowledge/ -v`
Expected: the 6 unit tests PASS; the 2 integration tests PASS (DB up) or SKIP (DB down).

- [ ] **Step 5: Commit**

```bash
git add tests/services/knowledge/test_repository_integration.py
git commit -m "$(cat <<'EOF'
test(knowledge): gated round-trip for upsert + vector_search

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

- **Spec coverage:** Implements spec §3 (package `services/knowledge/`, models `KnowledgeChunk`/`ScoredChunk`, all three repository ops) and §4 (unit tests via fake `connection_factory` + one gated integration round-trip). Acceptance criterion "`KnowledgeChunkRepository` has 3 ops with unit tests + 1 round-trip" is fully covered.
- **Placeholders:** none — every method and test is written out in full.
- **Type consistency:** `_CHUNK_COLUMNS` order matches `_row_to_chunk`/`_row_to_scored` indices (row[1]=knowledge_document_id … row[10]=span_end, row[11]=score) and the `INSERT` column order in `upsert_chunk`. Table/column names (`knowledge_chunks`, `embedding`, `source_url`, `span_start`, `span_end`) match migration `013` from Plan 2B. `_vector_literal` output (`"[a,b,c]"`) matches what the unit tests assert in `params`. `EMBEDDING_DIM` (Plan 2A) sizes the integration vectors.
- **Deviation from spec:** the `pgvector` pip package listed in spec §5 is not used — the `%s::vector` text-literal cast removes the need for `register_vector`. Flagged in Plan 2A.
