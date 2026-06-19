# Program Retrieval Metadata Filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a soft, structure-independent `program` scalar filter to knowledge retrieval — resolve the program named in a question via `pg_trgm` and filter `vector_search` by it, falling back to vector-only when no confident match.

**Architecture:** A new Postgres `pg_trgm` GIN index on `knowledge_chunks.program` backs a `KnowledgeChunkRepository.resolve_program(question, school)` resolver (`word_similarity`, threshold-gated). `vector_search` gains an optional `program` filter. The QA service (both the `retrieve()` method and the LangGraph `retrieve_school` node) resolves the program once per query and forwards it; `None` ⇒ today's behavior.

**Tech Stack:** Python 3.12, Postgres 16 + pgvector + pg_trgm, psycopg2, LangGraph, pytest.

This is **Plan 1 of 3**. It ships value on the existing HUST corpus (whose chunks already carry `program` from the breadcrumb) with no ingestion changes. Plans 2 (program-from-seed) and 3 (NEU/UET seeds) are independent and can follow.

## Global Constraints

- **Never run `git push`.** Commit only; **no `Co-Authored-By` trailer or any AI/Claude attribution** in commit messages.
- Repositories take an injectable `connection_factory` and use the `services.db.cursor` (`_cursor`) context manager — never hand-roll `conn.close()`.
- Pydantic is **v2** (`model_config = ConfigDict(...)`).
- Migrations are numbered, **idempotent** SQL in `db/migrations/`; applied by `python -m db.setup_db` (and by `tests/conftest.py` for the test DB).
- Run tests with system Python: `python -m pytest -q` (this repo has no `.venv`; if your machine has one, use `.\.venv\Scripts\python.exe -m pytest -q`).
- Integration tests (DB-backed) carry `pytestmark = pytest.mark.integration` and depend on the `db_available` fixture; they need the Docker DB up (`docker compose up -d --wait db`).
- Retrieval must **degrade gracefully**: a missing/low program match returns `None` and never zeroes results.

---

## File Structure

- `db/migrations/020_knowledge_chunk_program_trgm.sql` — **create**: pg_trgm extension + GIN trigram index on `program`.
- `ingestion/config/settings.py` — **modify**: add `KNOWLEDGE_PROGRAM_MATCH_THRESHOLD`.
- `services/knowledge/repository.py` — **modify**: add `resolve_program`; add `program` param to `vector_search`.
- `services/knowledge/qa_service.py` — **modify**: `retrieve()` resolves + forwards `program`.
- `services/knowledge/qa_graph.py` — **modify**: `retrieve_school` node resolves + forwards `program`.
- `tests/integration/test_program_trgm_migration.py` — **create**.
- `tests/integration/test_resolve_program.py` — **create**.
- `tests/integration/test_vector_search_program_filter.py` — **create**.
- `tests/services/knowledge/test_qa_program_filter.py` — **create**.

---

### Task 1: Migration — pg_trgm extension + trigram index on `program`

**Files:**
- Create: `db/migrations/020_knowledge_chunk_program_trgm.sql`
- Test: `tests/integration/test_program_trgm_migration.py`

**Interfaces:**
- Produces: a Postgres extension `pg_trgm` and index `idx_knowledge_chunks_program_trgm` (GIN, `gin_trgm_ops`) on `knowledge_chunks.program`. Required by Tasks 3–4.

- [ ] **Step 1: Write the migration SQL**

`db/migrations/020_knowledge_chunk_program_trgm.sql`:

```sql
-- Trigram fuzzy matching on the program label so retrieval can resolve the
-- program named in a question (word_similarity) and scalar-filter by it.
-- Structure-independent: works regardless of how a page was chunked.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_program_trgm
    ON knowledge_chunks USING gin (program gin_trgm_ops);
```

- [ ] **Step 2: Write the failing integration test**

`tests/integration/test_program_trgm_migration.py`:

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


def test_pg_trgm_extension_installed(db_available):
    assert _fetch_scalar(
        "SELECT COUNT(*) FROM pg_extension WHERE extname = 'pg_trgm'"
    ) == 1


def test_program_trgm_index_exists(db_available):
    assert _fetch_scalar(
        "SELECT COUNT(*) FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname = %s",
        ("idx_knowledge_chunks_program_trgm",),
    ) == 1


def test_word_similarity_callable(db_available):
    # Proves pg_trgm's word_similarity is available for resolve_program.
    assert _fetch_scalar("SELECT word_similarity(%s, %s) > 0",
                         ("ô tô", "ngành kỹ thuật ô tô")) is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_program_trgm_migration.py -v`
Expected: FAIL (extension/index absent) — unless a previous run already migrated; if so, the test passes, which is also acceptable since the migration is idempotent.

- [ ] **Step 4: Apply the migration**

Run: `python -m db.setup_db`
Expected: completes without `⚠`; migration `020` listed/applied. (The test-DB conftest also applies it on the next pytest run.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_program_trgm_migration.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add db/migrations/020_knowledge_chunk_program_trgm.sql tests/integration/test_program_trgm_migration.py
git commit -m "feat(knowledge): pg_trgm extension + trigram index on chunk program"
```

---

### Task 2: Settings — program match threshold

**Files:**
- Modify: `ingestion/config/settings.py` (knowledge-chunking / QA settings block, near `KNOWLEDGE_QA_MIN_SCORE` ~line 81)

**Interfaces:**
- Produces: `KNOWLEDGE_PROGRAM_MATCH_THRESHOLD: float` (default `0.3`). Consumed by Task 3.

- [ ] **Step 1: Write the failing test**

Append to `tests/ingestion/test_knowledge_qa_settings.py` (existing file):

```python
def test_program_match_threshold_default():
    import importlib
    import ingestion.config.settings as s
    importlib.reload(s)
    assert s.KNOWLEDGE_PROGRAM_MATCH_THRESHOLD == 0.3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ingestion/test_knowledge_qa_settings.py::test_program_match_threshold_default -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'KNOWLEDGE_PROGRAM_MATCH_THRESHOLD'`.

- [ ] **Step 3: Add the setting**

In `ingestion/config/settings.py`, immediately after the `KNOWLEDGE_QA_MIN_SCORE` line, add:

```python
# Query-side program resolution (services/knowledge): the minimum
# word_similarity between a program label and the user's question for the
# program scalar filter to apply. Below it, retrieval stays vector-only so a
# weak/absent match never zeroes results.
KNOWLEDGE_PROGRAM_MATCH_THRESHOLD = float(
    os.getenv("KNOWLEDGE_PROGRAM_MATCH_THRESHOLD", 0.3)
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ingestion/test_knowledge_qa_settings.py::test_program_match_threshold_default -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/config/settings.py tests/ingestion/test_knowledge_qa_settings.py
git commit -m "feat(knowledge): add KNOWLEDGE_PROGRAM_MATCH_THRESHOLD setting"
```

---

### Task 3: Repository — `resolve_program`

**Files:**
- Modify: `services/knowledge/repository.py` (add method to `KnowledgeChunkRepository`; add settings import)
- Test: `tests/integration/test_resolve_program.py`

**Interfaces:**
- Consumes: `KNOWLEDGE_PROGRAM_MATCH_THRESHOLD` (Task 2); pg_trgm `word_similarity` (Task 1).
- Produces: `KnowledgeChunkRepository.resolve_program(self, question: str, school: str | None = None, threshold: float = KNOWLEDGE_PROGRAM_MATCH_THRESHOLD) -> str | None`.

- [ ] **Step 1: Write the failing integration test**

`tests/integration/test_resolve_program.py`:

```python
import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG
from services.knowledge.models import KnowledgeChunk
from services.knowledge.repository import KnowledgeChunkRepository

pytestmark = pytest.mark.integration


def _conn():
    return psycopg2.connect(**DB_CONFIG)


@pytest.fixture
def repo(db_available):
    r = KnowledgeChunkRepository(connection_factory=_conn)
    # Clean slate for this test's program labels.
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE school = 'TESTU'")
        c.commit()
    yield r
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE school = 'TESTU'")
        c.commit()


def _seed(repo, program, school="TESTU", url=None):
    repo.upsert_chunk(KnowledgeChunk(
        knowledge_document_id=None, school=school, program=program, year=None,
        document_type=None, topic="program_overview",
        chunk_text=f"{program} nội dung", content_hash=None, embedding=None,
        source_url=url or f"https://t/{program}", span_start=0, span_end=5,
    ))


def test_resolves_program_named_in_question(repo):
    _seed(repo, "Kỹ thuật Ô tô")
    _seed(repo, "Khoa học Máy tính")
    assert repo.resolve_program("cơ hội việc làm ngành Kỹ thuật Ô tô", "TESTU") \
        == "Kỹ thuật Ô tô"


def test_returns_none_when_no_program_named(repo):
    _seed(repo, "Kỹ thuật Ô tô")
    assert repo.resolve_program("phương thức xét tuyển của trường", "TESTU") is None


def test_scoped_by_school(repo):
    _seed(repo, "Kỹ thuật Ô tô", school="TESTU")
    # Same name under another school must not leak when school is given.
    assert repo.resolve_program("ngành Kỹ thuật Ô tô", "OTHERU") is None


def test_empty_question_returns_none(repo):
    _seed(repo, "Kỹ thuật Ô tô")
    assert repo.resolve_program("", "TESTU") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_resolve_program.py -v`
Expected: FAIL with `AttributeError: 'KnowledgeChunkRepository' object has no attribute 'resolve_program'`.

- [ ] **Step 3: Implement `resolve_program`**

In `services/knowledge/repository.py`, add the settings import near the top (after the existing imports):

```python
from ingestion.config.settings import KNOWLEDGE_PROGRAM_MATCH_THRESHOLD
```

Add this method to `KnowledgeChunkRepository` (e.g. directly above `vector_search`):

```python
    def resolve_program(self, question, school=None,
                        threshold=KNOWLEDGE_PROGRAM_MATCH_THRESHOLD):
        """Best program label whose name appears inside the question, or None.

        word_similarity(program, question) scores the (short) program label
        against the best-matching window of the (long) question. Scoped to
        `school` when given so labels don't collide across schools. Returns the
        top program only when its score clears `threshold`; otherwise None, so
        callers degrade to vector-only retrieval.
        """
        if not question:
            return None
        sql = (
            "SELECT program, MAX(word_similarity(program, %s)) AS sim "
            "FROM knowledge_chunks WHERE program IS NOT NULL"
        )
        params = [question]
        if school is not None:
            sql += " AND school = %s"
            params.append(school)
        sql += " GROUP BY program ORDER BY sim DESC LIMIT 1"
        with _cursor(self.connection_factory) as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
        if row is None or row[1] is None or row[1] < threshold:
            return None
        return row[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_resolve_program.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/repository.py tests/integration/test_resolve_program.py
git commit -m "feat(knowledge): resolve_program via pg_trgm word_similarity"
```

---

### Task 4: Repository — `program` filter in `vector_search`

**Files:**
- Modify: `services/knowledge/repository.py` (`vector_search`, ~lines 162-184)
- Test: `tests/integration/test_vector_search_program_filter.py`

**Interfaces:**
- Produces: `vector_search(self, embedding, school=None, topic=None, program=None, limit=5)` — when `program` is not `None`, adds `AND program = %s`.

- [ ] **Step 1: Write the failing integration test**

`tests/integration/test_vector_search_program_filter.py`:

```python
import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG
from services.knowledge.models import KnowledgeChunk
from services.knowledge.repository import KnowledgeChunkRepository

pytestmark = pytest.mark.integration

DIM = 768


def _conn():
    return psycopg2.connect(**DB_CONFIG)


@pytest.fixture
def repo(db_available):
    r = KnowledgeChunkRepository(connection_factory=_conn)
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE school = 'TESTU'")
        c.commit()
    yield r
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE school = 'TESTU'")
        c.commit()


def _seed(repo, program, url):
    repo.upsert_chunk(KnowledgeChunk(
        knowledge_document_id=None, school="TESTU", program=program, year=None,
        document_type=None, topic="program_overview",
        chunk_text=f"{program} nội dung", content_hash=None,
        embedding=[0.1] * DIM, source_url=url, span_start=0, span_end=5,
    ))


def test_program_filter_restricts_results(repo):
    _seed(repo, "Kỹ thuật Ô tô", "https://t/a")
    _seed(repo, "Khoa học Máy tính", "https://t/b")
    rows = repo.vector_search([0.1] * DIM, school="TESTU",
                              topic="program_overview", program="Kỹ thuật Ô tô")
    assert rows, "expected at least one match"
    assert {r.program for r in rows} == {"Kỹ thuật Ô tô"}


def test_no_program_returns_all(repo):
    _seed(repo, "Kỹ thuật Ô tô", "https://t/a")
    _seed(repo, "Khoa học Máy tính", "https://t/b")
    rows = repo.vector_search([0.1] * DIM, school="TESTU",
                              topic="program_overview", program=None)
    assert {r.program for r in rows} == {"Kỹ thuật Ô tô", "Khoa học Máy tính"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_vector_search_program_filter.py -v`
Expected: FAIL with `TypeError: vector_search() got an unexpected keyword argument 'program'`.

- [ ] **Step 3: Add the `program` parameter and filter**

In `services/knowledge/repository.py`, change the `vector_search` signature and insert the program filter **after** the topic filter, **before** the `ORDER BY`:

```python
    def vector_search(self, embedding, school=None, topic=None, program=None, limit=5):
        literal = _vector_literal(embedding)
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
            # NULL topic = wildcard: locally-ingested official PDFs are
            # multi-topic, so they stay candidates for every topic filter.
            sql += " AND (topic = %s OR topic IS NULL)"
            params.append(topic)
        if program is not None:
            # Exact match: the value comes FROM the DB via resolve_program.
            sql += " AND program = %s"
            params.append(program)
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.append(literal)
        params.append(limit)
        with _cursor(self.connection_factory) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [self._row_to_scored(row) for row in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_vector_search_program_filter.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full repository-related integration tests (no regressions)**

Run: `python -m pytest tests/integration -v`
Expected: PASS (or skip if DB down) — nothing newly broken.

- [ ] **Step 6: Commit**

```bash
git add services/knowledge/repository.py tests/integration/test_vector_search_program_filter.py
git commit -m "feat(knowledge): optional program scalar filter in vector_search"
```

---

### Task 5: QA service + graph — resolve and forward `program`

**Files:**
- Modify: `services/knowledge/qa_service.py` (`retrieve`, ~lines 151-159)
- Modify: `services/knowledge/qa_graph.py` (`retrieve_school` node, ~lines 41-45)
- Test: `tests/services/knowledge/test_qa_program_filter.py`

**Interfaces:**
- Consumes: `resolve_program` (Task 3), `vector_search(..., program=...)` (Task 4).
- Produces: both retrieval paths call `resolve_program(question_or_retrieval_query, school)` and forward the result to `vector_search`. The national-scope pass stays program-unfiltered.

- [ ] **Step 1: Write the failing unit test**

`tests/services/knowledge/test_qa_program_filter.py`:

```python
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class FakeEmbedder:
    def embed(self, texts, task_type=None):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeChunkRepo:
    def __init__(self):
        self.calls = []          # list of program kwargs seen by vector_search

    def resolve_program(self, question, school=None):
        return "Kỹ thuật Ô tô" if "Ô tô" in (question or "") else None

    def vector_search(self, embedding, school=None, topic=None,
                      program=None, limit=5):
        self.calls.append({"school": school, "topic": topic, "program": program})
        return []                # empty -> gate goes to no_data (no LLM needed)


def _service(repo):
    # gateway=object(): never invoked because empty chunks short-circuit to no_data.
    return KnowledgeQAService(
        chunk_repository=repo, embedder=FakeEmbedder(),
        gateway=object(), cache=None,
    )


def test_retrieve_method_forwards_resolved_program():
    repo = FakeChunkRepo()
    svc = _service(repo)
    svc.retrieve("cơ hội việc làm ngành Kỹ thuật Ô tô", "HUST", "program_overview")
    school_call = repo.calls[0]
    assert school_call["program"] == "Kỹ thuật Ô tô"


def test_graph_retrieve_node_forwards_program():
    repo = FakeChunkRepo()
    svc = _service(repo)
    svc.answer("cơ hội việc làm ngành Kỹ thuật Ô tô", "HUST", "program_overview")
    # First (school-scoped) call carries the resolved program...
    assert repo.calls[0]["school"] == "HUST"
    assert repo.calls[0]["program"] == "Kỹ thuật Ô tô"
    # ...the national-scope augmentation call must NOT filter by program.
    national = [c for c in repo.calls if c["school"] != "HUST"]
    assert national and all(c["program"] is None for c in national)


def test_non_program_question_uses_no_filter():
    repo = FakeChunkRepo()
    svc = _service(repo)
    svc.retrieve("phương thức xét tuyển", "HUST", "admission_policy")
    assert repo.calls[0]["program"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/knowledge/test_qa_program_filter.py -v`
Expected: FAIL — `retrieve()`/graph still call `vector_search` without `program`, so `calls[0]["program"]` is `None` in the first test.

- [ ] **Step 3: Update `retrieve()` in `qa_service.py`**

Replace the body of `retrieve` (lines ~151-159) with:

```python
    def retrieve(self, question: str, school, topic):
        """Production-equivalent retrieval (embed → resolve program → vector_search
        → national augment), exposed so the eval curation can freeze the same
        chunks production would surface. Mirrors answer()'s retrieval branch."""
        embedding = self.embed_query(question)
        program = self._chunk_repository.resolve_program(question, school)
        chunks = self._chunk_repository.vector_search(
            embedding, school=school, topic=topic, program=program, limit=self._top_k
        )
        return self._augment_with_national(embedding, school, topic, chunks)
```

- [ ] **Step 4: Update the `retrieve_school` node in `qa_graph.py`**

Replace the `retrieve_school` node (lines ~41-45) with:

```python
    def retrieve_school(state: KQAState) -> KQAState:
        program = service._chunk_repository.resolve_program(
            state.retrieval_query or state.question, state.school
        )
        state.chunks = service._chunk_repository.vector_search(
            state.embedding, school=state.school, topic=state.topic,
            program=program, limit=service._top_k,
        )
        return state
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/services/knowledge/test_qa_program_filter.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the knowledge service + chat QA tests (no regressions)**

Run: `python -m pytest tests/services/knowledge tests/services/chat -q`
Expected: PASS (DB-backed ones skip if the DB is down).

- [ ] **Step 7: Commit**

```bash
git add services/knowledge/qa_service.py services/knowledge/qa_graph.py tests/services/knowledge/test_qa_program_filter.py
git commit -m "feat(knowledge): resolve and apply program filter in QA retrieval"
```

---

## Self-Review Notes (coverage map)

- Spec §3 migration → Task 1. §3 settings → Task 2. §3 `resolve_program` → Task 3. §3 `vector_search` filter → Task 4. §3 qa_service + graph wiring + national-pass-unfiltered → Task 5.
- §5 edge cases covered by tests: no match → None (Task 3 `test_returns_none...`, `test_empty_question...`), school scope (Task 3 `test_scoped_by_school`), national pass unfiltered (Task 5 `test_graph_retrieve_node...`), non-program topic no-op (Task 5 `test_non_program_question...`).
- Signatures consistent across tasks: `resolve_program(question, school=None, threshold=...)`, `vector_search(embedding, school=None, topic=None, program=None, limit=5)`.
