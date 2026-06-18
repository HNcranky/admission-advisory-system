# Knowledge QA Cache — Plan 01: Schema & Version Stamping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the cache schema (migration `019`), the three cache settings, and the version-stamping half of `QACacheRepository` (`scope_key_for`, `scope_keys`, `current_versions`, `bump_version`).

**Architecture:** A new idempotent SQL migration adds two tables — `knowledge_qa_cache` (answer rows) and `knowledge_qa_cache_version` (per-scope version counters). A new repository module `services/knowledge/qa_cache.py` exposes the scope-key helpers and the version read/bump operations, following the existing `KnowledgeChunkRepository` pattern (injectable `connection_factory`, `services.db.cursor`). The row store/lookup half is deliberately deferred to Plan 02.

**Tech Stack:** Python 3.12, psycopg2, pgvector (`pgvector/pgvector:pg16`), Postgres, pytest.

## Global Constraints

- **Never run `git push`.** `git commit` is allowed; **never** add a `Co-Authored-By` trailer or any AI/Claude attribution to commit messages.
- Pydantic is **v2** (`model_config = ConfigDict(...)`).
- New DB code uses an injectable `connection_factory` (default `services.knowledge.db.get_knowledge_db_connection`) and the `services.db.cursor` context manager — never hand-roll `conn.close()`.
- Cache faults must **degrade gracefully** (callers wrap and `logger.warning`); the cache never breaks QA or ingestion. (Enforced in Plans 03/04; keep repository methods plain — let callers wrap.)
- Migrations are numbered and idempotent (`IF NOT EXISTS`), discovered by `sorted(db/migrations/*.sql)`. The next free number is **019** (018 is the current max; note there are intentionally two `014_*.sql` files).
- pgvector dimension is `EMBEDDING_DIM = 768`.
- `NATIONAL_SCHOOL = "MOET"` from `services/knowledge/scope.py`.
- Run tests with `python -m pytest -q` (this repo has no `.venv`; use system Python 3.12). Integration tests need the Docker DB up: `docker compose up -d --wait db`. The `admission_test` DB auto-creates and auto-migrates at session start.

---

### Task 1: Migration `019_knowledge_qa_cache.sql`

**Files:**
- Create: `db/migrations/019_knowledge_qa_cache.sql`
- Test: `tests/integration/test_qa_cache_migration.py`

**Interfaces:**
- Consumes: nothing.
- Produces: tables `knowledge_qa_cache` (cols `id, school, topic, question, embedding vector(768), answer_json jsonb, confidence real, dep_versions jsonb, created_at, expires_at`) and `knowledge_qa_cache_version` (cols `scope_key text PK, version bigint, bumped_at`); indexes `idx_qa_cache_scope`, `idx_qa_cache_embedding` (hnsw), `idx_qa_cache_expires`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_qa_cache_migration.py`:

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


def test_qa_cache_tables_exist(db_available):
    for table in ("knowledge_qa_cache", "knowledge_qa_cache_version"):
        assert _fetch_scalar(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        ) == 1, f"missing table {table}"


def test_qa_cache_indexes_exist(db_available):
    for index in (
        "idx_qa_cache_scope",
        "idx_qa_cache_embedding",
        "idx_qa_cache_expires",
    ):
        assert _fetch_scalar(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = %s",
            (index,),
        ) == 1, f"missing index {index}"


def test_qa_cache_embedding_is_768_dim_vector(db_available):
    atttypmod = _fetch_scalar(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'knowledge_qa_cache' AND a.attname = 'embedding'
        """
    )
    assert atttypmod == 768
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_qa_cache_migration.py -v`
Expected: FAIL — `missing table knowledge_qa_cache` (the migration does not exist yet, so the session-start migration run never created it).

- [ ] **Step 3: Create the migration (verbatim from spec §Components)**

Create `db/migrations/019_knowledge_qa_cache.sql`:

```sql
CREATE TABLE IF NOT EXISTS knowledge_qa_cache (
    id           BIGSERIAL PRIMARY KEY,
    school       TEXT NOT NULL,
    topic        TEXT NOT NULL,
    question     TEXT NOT NULL,
    embedding    vector(768) NOT NULL,
    answer_json  JSONB NOT NULL,         -- {answer, citations, confidence}
    confidence   REAL NOT NULL,
    dep_versions JSONB NOT NULL,         -- {scope_key: version_at_write}
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qa_cache_scope
    ON knowledge_qa_cache (school, topic);
CREATE INDEX IF NOT EXISTS idx_qa_cache_embedding
    ON knowledge_qa_cache USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_qa_cache_expires
    ON knowledge_qa_cache (expires_at);

CREATE TABLE IF NOT EXISTS knowledge_qa_cache_version (
    scope_key TEXT PRIMARY KEY,
    version   BIGINT NOT NULL DEFAULT 1,
    bumped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_qa_cache_migration.py -v`
Expected: PASS — the session fixture (`tests/conftest.py::_isolate_test_db`) re-runs all migrations idempotently at the start of this new pytest session, applying `019`.

(If the Docker DB is not running, the tests will SKIP with a remediation message — that is acceptable for DB-less runs but you must run them at least once with the DB up to verify.)

- [ ] **Step 5: Commit**

```bash
git add db/migrations/019_knowledge_qa_cache.sql tests/integration/test_qa_cache_migration.py
git commit -m "feat(db): add knowledge_qa_cache + version tables (migration 019)"
```

---

### Task 2: Cache settings

**Files:**
- Modify: `ingestion/config/settings.py` (append after the Knowledge QA retrieval block, near line 85)
- Test: `tests/services/knowledge/test_qa_cache_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `KNOWLEDGE_QA_CACHE_ENABLED: bool` (default `True`), `KNOWLEDGE_QA_CACHE_THRESHOLD: float` (default `0.95`), `KNOWLEDGE_QA_CACHE_TTL_DAYS: int` (default `30`).

- [ ] **Step 1: Write the failing test**

Create `tests/services/knowledge/test_qa_cache_settings.py`:

```python
from ingestion.config import settings


def test_cache_settings_have_spec_defaults():
    assert settings.KNOWLEDGE_QA_CACHE_ENABLED is True
    assert settings.KNOWLEDGE_QA_CACHE_THRESHOLD == 0.95
    assert settings.KNOWLEDGE_QA_CACHE_TTL_DAYS == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_settings.py -v`
Expected: FAIL — `AttributeError: module 'ingestion.config.settings' has no attribute 'KNOWLEDGE_QA_CACHE_ENABLED'`.

- [ ] **Step 3: Add the settings**

In `ingestion/config/settings.py`, immediately after the line
`KNOWLEDGE_QA_NATIONAL_TOP_K = int(os.getenv("KNOWLEDGE_QA_NATIONAL_TOP_K", 3))`
(end of the "Knowledge QA retrieval" block, ~line 85), add:

```python
# --- Knowledge QA semantic cache -----------------------------------------
# Cache repeated/paraphrased knowledge answers to cut Gemini generation calls.
# A HIT requires cosine >= THRESHOLD AND all dependency-scope versions current
# (see services/knowledge/qa_cache.py + docs spec 2026-06-18). TTL is a
# backstop only — correctness rests on version stamping. Any cache fault
# degrades to normal generation.
KNOWLEDGE_QA_CACHE_ENABLED = os.getenv(
    "KNOWLEDGE_QA_CACHE_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
KNOWLEDGE_QA_CACHE_THRESHOLD = float(os.getenv("KNOWLEDGE_QA_CACHE_THRESHOLD", 0.95))
KNOWLEDGE_QA_CACHE_TTL_DAYS = int(os.getenv("KNOWLEDGE_QA_CACHE_TTL_DAYS", 30))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/config/settings.py tests/services/knowledge/test_qa_cache_settings.py
git commit -m "feat(config): add knowledge QA cache settings"
```

---

### Task 3: `QACacheRepository` scope keys (pure helpers)

**Files:**
- Create: `services/knowledge/qa_cache.py`
- Test: `tests/services/knowledge/test_qa_cache_repository.py`

**Interfaces:**
- Consumes: `NATIONAL_SCHOOL` from `services/knowledge/scope.py`.
- Produces:
  - `scope_key_for(school: str, topic: str | None) -> str` — `"s:{school}|t:{topic or '*'}"`.
  - `QACacheRepository(connection_factory=get_knowledge_db_connection)`.
  - `QACacheRepository.scope_keys(school: str, topic: str) -> list[str]` — the 4 dependency keys.

- [ ] **Step 1: Write the failing test**

Create `tests/services/knowledge/test_qa_cache_repository.py`:

```python
from services.knowledge.qa_cache import QACacheRepository, scope_key_for
from services.knowledge.scope import NATIONAL_SCHOOL


def test_scope_key_for_concrete_topic():
    assert scope_key_for("HUST", "tuition") == "s:HUST|t:tuition"


def test_scope_key_for_null_topic_is_wildcard():
    assert scope_key_for("HUST", None) == "s:HUST|t:*"
    assert scope_key_for("HUST", "") == "s:HUST|t:*"


def test_scope_keys_returns_four_dependency_scopes():
    keys = QACacheRepository.scope_keys("HUST", "tuition")
    assert keys == [
        "s:HUST|t:tuition",
        "s:HUST|t:*",
        f"s:{NATIONAL_SCHOOL}|t:tuition",
        f"s:{NATIONAL_SCHOOL}|t:*",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.knowledge.qa_cache'`.

- [ ] **Step 3: Create the module with scope helpers**

Create `services/knowledge/qa_cache.py`:

```python
"""Postgres-backed semantic cache for Knowledge QA answers.

Mirrors KnowledgeChunkRepository: injectable connection_factory, all DB access
via services.db.cursor. The row store/lookup half is added in Plan 02; this
module starts with the scope-key helpers and the version-stamping operations
that the invalidation strategy rests on.
"""
from services.db import cursor as _cursor
from services.knowledge.scope import NATIONAL_SCHOOL


def scope_key_for(school: str, topic: str | None) -> str:
    """One scope_key for a (school, topic). NULL/empty topic → wildcard '*'.

    Both the read side (QACacheRepository.scope_keys) and the ingest bump derive
    their keys through this single helper, so they are guaranteed to agree.
    """
    return f"s:{school}|t:{topic if topic else '*'}"


class QACacheRepository:
    def __init__(self, connection_factory=None):
        # Imported lazily to mirror the knowledge repos and avoid importing the
        # DB layer at module import time.
        if connection_factory is None:
            from services.knowledge.db import get_knowledge_db_connection
            connection_factory = get_knowledge_db_connection
        self.connection_factory = connection_factory

    @staticmethod
    def scope_keys(school: str, topic: str) -> list[str]:
        """The four corpus scopes a concrete (school, topic) answer depends on:
        the school's own topic chunks, the school's wildcard (NULL-topic) docs,
        and the national-scope (MOET) equivalents merged into every school
        answer (qa_service._augment_with_national)."""
        return [
            scope_key_for(school, topic),
            scope_key_for(school, None),
            scope_key_for(NATIONAL_SCHOOL, topic),
            scope_key_for(NATIONAL_SCHOOL, None),
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_repository.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/qa_cache.py tests/services/knowledge/test_qa_cache_repository.py
git commit -m "feat(knowledge): add QACacheRepository scope-key helpers"
```

---

### Task 4: `current_versions` + `bump_version`

**Files:**
- Modify: `services/knowledge/qa_cache.py`
- Test: `tests/services/knowledge/test_qa_cache_repository.py` (add cases)

**Interfaces:**
- Consumes: `services.db.cursor`, `QACacheRepository.scope_keys`.
- Produces:
  - `QACacheRepository.current_versions(scope_keys) -> dict[str, int]` — version per key; **missing key → 0**.
  - `QACacheRepository.bump_version(scope_key: str) -> None` — upsert that creates the row at version 1, else increments.

- [ ] **Step 1: Write the failing unit tests (FakeConnection)**

Append to `tests/services/knowledge/test_qa_cache_repository.py`:

```python
class FakeCursor:
    def __init__(self, fetchall_return=None):
        self.statements = []
        self._fetchall = fetchall_return or []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return self._fetchall

    def fetchone(self):
        return None

    def close(self):
        return None


class FakeConnection:
    def __init__(self, fetchall_return=None):
        self.cursor_obj = FakeCursor(fetchall_return)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def _repo(connection):
    return QACacheRepository(connection_factory=lambda: connection)


def test_current_versions_defaults_missing_keys_to_zero():
    # DB knows only s:HUST|t:tuition = 3; the other 3 scopes are absent → 0.
    connection = FakeConnection(fetchall_return=[("s:HUST|t:tuition", 3)])
    repo = _repo(connection)

    versions = repo.current_versions(QACacheRepository.scope_keys("HUST", "tuition"))

    sql, params = connection.cursor_obj.statements[0]
    assert "scope_key = ANY(%s)" in sql
    assert versions == {
        "s:HUST|t:tuition": 3,
        "s:HUST|t:*": 0,
        "s:MOET|t:tuition": 0,
        "s:MOET|t:*": 0,
    }


def test_current_versions_empty_keys_makes_no_query():
    connection = FakeConnection()
    repo = _repo(connection)
    assert repo.current_versions([]) == {}
    assert connection.cursor_obj.statements == []


def test_bump_version_upserts_with_increment():
    connection = FakeConnection()
    repo = _repo(connection)

    repo.bump_version("s:HUST|t:*")

    sql, params = connection.cursor_obj.statements[0]
    assert "INSERT INTO knowledge_qa_cache_version (scope_key)" in sql
    assert "ON CONFLICT (scope_key) DO UPDATE" in sql
    assert "version = knowledge_qa_cache_version.version + 1" in sql
    assert params == ("s:HUST|t:*",)
    assert connection.committed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_repository.py -v`
Expected: FAIL — `AttributeError: 'QACacheRepository' object has no attribute 'current_versions'`.

- [ ] **Step 3: Implement the version methods**

In `services/knowledge/qa_cache.py`, add these two methods to `QACacheRepository` (after `scope_keys`):

```python
    def current_versions(self, scope_keys) -> dict[str, int]:
        keys = list(scope_keys)
        if not keys:
            return {}
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                "SELECT scope_key, version FROM knowledge_qa_cache_version "
                "WHERE scope_key = ANY(%s)",
                (keys,),
            )
            rows = cur.fetchall()
        found = {k: int(v) for k, v in rows}
        return {k: found.get(k, 0) for k in keys}

    def bump_version(self, scope_key: str) -> None:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                """
                INSERT INTO knowledge_qa_cache_version (scope_key)
                VALUES (%s)
                ON CONFLICT (scope_key) DO UPDATE SET
                    version = knowledge_qa_cache_version.version + 1,
                    bumped_at = NOW()
                """,
                (scope_key,),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_repository.py -v`
Expected: PASS (all cases, including Task 3).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/qa_cache.py tests/services/knowledge/test_qa_cache_repository.py
git commit -m "feat(knowledge): add cache version read/bump to QACacheRepository"
```

---

### Task 5: Integration — version bump round-trip + shared cleanup fixture

**Files:**
- Modify: `tests/integration/conftest.py` (add `qa_cache_clean` fixture)
- Test: `tests/integration/test_qa_cache_versions.py`

**Interfaces:**
- Consumes: real `knowledge_qa_cache_version` table (migration 019), `QACacheRepository.bump_version`, `QACacheRepository.current_versions`.
- Produces: `qa_cache_clean` pytest fixture (truncates both cache tables, guarded to `*_test` DBs) — reused by Plans 02 and 04.

- [ ] **Step 1: Add the shared cleanup fixture**

In `tests/integration/conftest.py`, append after the existing `clean_db` fixture:

```python
@pytest.fixture
def qa_cache_clean(db_available):
    """Truncate the QA cache tables before a test. Guarded so it can only ever
    run against the isolated `*_test` database."""
    assert DB_CONFIG["database"].endswith("_test"), (
        f"qa_cache_clean would truncate {DB_CONFIG['database']!r} — refusing; "
        "it must only run against the isolated test database."
    )
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE knowledge_qa_cache, knowledge_qa_cache_version "
                "RESTART IDENTITY"
            )
        conn.commit()
    finally:
        conn.close()
    yield
```

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration/test_qa_cache_versions.py`:

```python
import pytest

from services.knowledge.qa_cache import QACacheRepository

pytestmark = pytest.mark.integration


def test_bump_version_creates_then_increments(db_available, qa_cache_clean):
    repo = QACacheRepository()
    key = "s:ITEST|t:tuition"

    # absent → version 0
    assert repo.current_versions([key]) == {key: 0}

    repo.bump_version(key)
    assert repo.current_versions([key]) == {key: 1}

    repo.bump_version(key)
    assert repo.current_versions([key]) == {key: 2}


def test_current_versions_reports_zero_for_unknown_scopes(db_available, qa_cache_clean):
    repo = QACacheRepository()
    repo.bump_version("s:ITEST|t:tuition")

    versions = repo.current_versions(QACacheRepository.scope_keys("ITEST", "tuition"))
    assert versions["s:ITEST|t:tuition"] == 1
    assert versions["s:ITEST|t:*"] == 0
    assert versions["s:MOET|t:tuition"] == 0
    assert versions["s:MOET|t:*"] == 0
```

- [ ] **Step 3: Run tests to verify they pass (DB up)**

Run: `python -m pytest tests/integration/test_qa_cache_versions.py -v`
Expected: PASS with the Docker DB up (else SKIP). No prior "fail" step is needed here — the behaviour is already implemented in Task 4; this task proves it against real Postgres and establishes the reusable fixture.

- [ ] **Step 4: Run the full knowledge + integration slice for regressions**

Run: `python -m pytest tests/services/knowledge tests/integration/test_qa_cache_migration.py tests/integration/test_qa_cache_versions.py -q`
Expected: PASS (or SKIP for DB-dependent tests when the DB is down).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_qa_cache_versions.py
git commit -m "test(knowledge): integration coverage for cache version stamping"
```

---

## Self-Review (run after completing all tasks)

- **Spec coverage:** migration `019` tables/indexes (✓ Task 1); 3 settings (✓ Task 2); `scope_keys`/`current_versions`/`bump_version` and the `scope_key_for` bump-rule helper (✓ Tasks 3-4); `NATIONAL_SCHOOL` mapping (✓ Task 3 via `scope_key_for`). `store`/`lookup`/`CachedAnswer` are intentionally **out of scope** — Plan 02.
- **No placeholders:** every step has runnable code/SQL and an exact command.
- **Type consistency:** `scope_key_for(school, topic)` and `scope_keys` agree on the `"s:{school}|t:{topic or '*'}"` shape; `current_versions` returns `dict[str, int]` consumed unchanged by Plan 02's `lookup` and Plan 03's wiring.
