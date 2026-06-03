# Phase 3 · Plan 04 — Repository Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the persistence the Phase 3 pipeline needs beyond Phase 2's `upsert_chunk`: a document repository (content-hash gate + create + final mark) and two chunk helpers (embedding-reuse map + delete-for-document).

**Architecture:** Extend the existing `services/knowledge/` package in place, following its psycopg2 / injectable `connection_factory` / Pydantic-model conventions. Add `KnowledgeDocument` to `models.py`; add `KnowledgeDocumentRepository`, the `chunk_content_hash` helper, and two methods on `KnowledgeChunkRepository` to `repository.py`. `chunk_content_hash` is the single source of truth for the reuse-map key so the pipeline (Plan 05) hashes new chunks identically.

**Tech Stack:** Python, psycopg2, Pydantic v2, pgvector, pytest.

**Spec:** [`2026-05-30-phase-3-data-collection-design.md`](../specs/2026-05-30-phase-3-data-collection-design.md) §6–§7. Schema (`knowledge_documents`, `knowledge_chunks`) already exists from Phase 2 migration `013`; **no new migration**.

---

### Task 1: `KnowledgeDocument` model

**Files:**
- Modify: `services/knowledge/models.py`
- Test: `tests/services/knowledge/test_models.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/services/knowledge/test_models.py`:
```python
from services.knowledge.models import KnowledgeDocument


def test_knowledge_document_defaults():
    doc = KnowledgeDocument(
        school="HUST",
        document_type="tuition_page",
        source_url="https://x/tuition",
    )
    assert doc.content_hash is None
    assert doc.raw_text is None
    assert doc.id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/knowledge/test_models.py::test_knowledge_document_defaults -v`
Expected: FAIL — `ImportError: cannot import name 'KnowledgeDocument'`.

- [ ] **Step 3: Write minimal implementation**

Append to `services/knowledge/models.py`:
```python
class KnowledgeDocument(BaseModel):
    school: str
    document_type: str
    source_url: str
    content_hash: str | None = None
    raw_text: str | None = None
    id: int | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/knowledge/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/models.py tests/services/knowledge/test_models.py
git commit -m "feat(knowledge): add KnowledgeDocument model"
```

---

### Task 2: `KnowledgeDocumentRepository`

**Files:**
- Modify: `services/knowledge/repository.py`
- Test: `tests/services/knowledge/test_document_repository.py`

- [ ] **Step 1: Write the failing test**

`tests/services/knowledge/test_document_repository.py`:
```python
from services.knowledge.models import KnowledgeDocument
from services.knowledge.repository import KnowledgeDocumentRepository


class FakeCursor:
    def __init__(self, fetchone_return=None, fetchall_return=None):
        self.statements = []
        self._fetchone = fetchone_return
        self._fetchall = fetchall_return or []
        self.rowcount = 0

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
    return KnowledgeDocumentRepository(connection_factory=lambda: connection)


def test_get_document_by_url_returns_model():
    row = (5, "HUST", "tuition_page", "https://x/t", "abc123", "raw text")
    conn = FakeConnection(fetchone_return=row)
    repo = _repo(conn)

    doc = repo.get_document_by_url("https://x/t")

    sql, params = conn.cursor_obj.statements[0]
    assert "FROM knowledge_documents" in sql
    assert "WHERE source_url = %s" in sql
    assert params == ("https://x/t",)
    assert doc.id == 5
    assert doc.content_hash == "abc123"
    assert doc.school == "HUST"


def test_get_document_by_url_returns_none_when_absent():
    conn = FakeConnection(fetchone_return=None)
    assert _repo(conn).get_document_by_url("https://nope") is None


def test_get_or_create_document_uses_on_conflict_and_omits_content_hash():
    conn = FakeConnection(fetchone_return=(9,))
    repo = _repo(conn)

    doc_id = repo.get_or_create_document(KnowledgeDocument(
        school="NEU", document_type="tuition_page",
        source_url="https://neu/t", raw_text="body",
    ))

    sql, params = conn.cursor_obj.statements[0]
    assert doc_id == 9
    assert "INSERT INTO knowledge_documents" in sql
    assert "ON CONFLICT (source_url) DO UPDATE" in sql
    # content_hash is intentionally NOT written here (set by mark_ingested)
    assert "content_hash" not in sql
    assert params == ("NEU", "tuition_page", "https://neu/t", "body")
    assert conn.committed is True


def test_mark_ingested_updates_hash_for_id():
    conn = FakeConnection()
    repo = _repo(conn)

    repo.mark_ingested(9, "deadbeef")

    sql, params = conn.cursor_obj.statements[0]
    assert "UPDATE knowledge_documents" in sql
    assert "SET content_hash = %s" in sql
    assert "WHERE id = %s" in sql
    assert params == ("deadbeef", 9)
    assert conn.committed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/knowledge/test_document_repository.py -v`
Expected: FAIL — `ImportError: cannot import name 'KnowledgeDocumentRepository'`.

- [ ] **Step 3: Write minimal implementation**

Add to `services/knowledge/repository.py` — first extend imports and add the class. At the top, change the model import line:
```python
from services.knowledge.models import KnowledgeChunk, ScoredChunk, KnowledgeDocument
```

Append at the end of the file:
```python
class KnowledgeDocumentRepository:
    def __init__(self, connection_factory=get_knowledge_db_connection):
        self.connection_factory = connection_factory

    def get_document_by_url(self, url: str) -> KnowledgeDocument | None:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, school, document_type, source_url, content_hash, raw_text "
            "FROM knowledge_documents WHERE source_url = %s",
            (url,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return None
        return KnowledgeDocument(
            id=row[0],
            school=row[1],
            document_type=row[2],
            source_url=row[3],
            content_hash=row[4],
            raw_text=row[5],
        )

    def get_or_create_document(self, doc: KnowledgeDocument) -> int:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_documents
                (school, document_type, source_url, raw_text)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_url) DO UPDATE SET
                school        = EXCLUDED.school,
                document_type = EXCLUDED.document_type,
                raw_text      = EXCLUDED.raw_text,
                fetched_at    = NOW()
            RETURNING id
            """,
            (doc.school, doc.document_type, doc.source_url, doc.raw_text),
        )
        doc_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return doc_id

    def mark_ingested(self, doc_id: int, content_hash: str) -> None:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            "UPDATE knowledge_documents "
            "SET content_hash = %s, ingested_at = NOW() WHERE id = %s",
            (content_hash, doc_id),
        )
        conn.commit()
        cur.close()
        conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/knowledge/test_document_repository.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/repository.py tests/services/knowledge/test_document_repository.py
git commit -m "feat(knowledge): add KnowledgeDocumentRepository"
```

---

### Task 3: `chunk_content_hash` + chunk-repo helpers

**Files:**
- Modify: `services/knowledge/repository.py`
- Test: `tests/services/knowledge/test_chunk_helpers.py`

- [ ] **Step 1: Write the failing test**

`tests/services/knowledge/test_chunk_helpers.py`:
```python
import hashlib

from services.knowledge.repository import (
    KnowledgeChunkRepository,
    chunk_content_hash,
)


class FakeCursor:
    def __init__(self, fetchall_return=None):
        self.statements = []
        self._fetchall = fetchall_return or []
        self.rowcount = len(self._fetchall)

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return self._fetchall

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
    return KnowledgeChunkRepository(connection_factory=lambda: connection)


def test_chunk_content_hash_is_sha256_of_utf8_text():
    text = "Học phí 2026"
    assert chunk_content_hash(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_get_embedding_map_keys_by_hash_and_parses_vector():
    rows = [("Học phí 2026", "[0.1,0.2,0.3]")]
    conn = FakeConnection(fetchall_return=rows)
    repo = _repo(conn)

    mapping = repo.get_embedding_map_for_document(7)

    sql, params = conn.cursor_obj.statements[0]
    assert "FROM knowledge_chunks" in sql
    assert "WHERE knowledge_document_id = %s" in sql
    assert "embedding IS NOT NULL" in sql
    assert params == (7,)
    key = chunk_content_hash("Học phí 2026")
    assert mapping[key] == [0.1, 0.2, 0.3]


def test_delete_chunks_for_document_runs_delete_and_commits():
    conn = FakeConnection()
    conn.cursor_obj.rowcount = 4
    repo = _repo(conn)

    deleted = repo.delete_chunks_for_document(7)

    sql, params = conn.cursor_obj.statements[0]
    assert "DELETE FROM knowledge_chunks" in sql
    assert "WHERE knowledge_document_id = %s" in sql
    assert params == (7,)
    assert deleted == 4
    assert conn.committed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/knowledge/test_chunk_helpers.py -v`
Expected: FAIL — `ImportError: cannot import name 'chunk_content_hash'`.

- [ ] **Step 3: Write minimal implementation**

In `services/knowledge/repository.py`, add `import hashlib` at the top, and add the module-level helper next to `_vector_literal`:
```python
import hashlib


def chunk_content_hash(text: str) -> str:
    """Single source of truth for the embedding-reuse-map key (Plan 05)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_vector(raw) -> list[float]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(x) for x in raw]
    s = str(raw).strip().strip("[]")
    if not s:
        return []
    return [float(x) for x in s.split(",")]
```

Add these two methods to `KnowledgeChunkRepository` (alongside `upsert_chunk`):
```python
    def get_embedding_map_for_document(self, doc_id: int) -> dict[str, list[float]]:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            "SELECT chunk_text, embedding FROM knowledge_chunks "
            "WHERE knowledge_document_id = %s AND embedding IS NOT NULL",
            (doc_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            chunk_content_hash(chunk_text): _parse_vector(embedding)
            for chunk_text, embedding in rows
        }

    def delete_chunks_for_document(self, doc_id: int) -> int:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM knowledge_chunks WHERE knowledge_document_id = %s",
            (doc_id,),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return deleted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/knowledge/test_chunk_helpers.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/repository.py tests/services/knowledge/test_chunk_helpers.py
git commit -m "feat(knowledge): add chunk_content_hash + embedding-reuse-map helpers"
```

---

### Task 4: Gated integration round-trip

**Files:**
- Test: `tests/services/knowledge/test_document_repository_integration.py`

- [ ] **Step 1: Write the integration test**

`tests/services/knowledge/test_document_repository_integration.py`:
```python
import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG, EMBEDDING_DIM
from services.knowledge.models import KnowledgeChunk, KnowledgeDocument
from services.knowledge.repository import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
    chunk_content_hash,
)

pytestmark = pytest.mark.integration


def _vec(*head):
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


@pytest.fixture
def repos():
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
    return KnowledgeDocumentRepository(), KnowledgeChunkRepository()


def test_document_create_chunks_reuse_map_delete_and_mark(repos):
    doc_repo, chunk_repo = repos

    doc_id = doc_repo.get_or_create_document(KnowledgeDocument(
        school="VNU-UET", document_type="tuition_page",
        source_url="https://x/t", raw_text="body",
    ))
    # get_or_create is idempotent on source_url → same id
    assert doc_repo.get_or_create_document(KnowledgeDocument(
        school="VNU-UET", document_type="tuition_page",
        source_url="https://x/t", raw_text="body2",
    )) == doc_id

    chunk_repo.upsert_chunk(KnowledgeChunk(
        knowledge_document_id=doc_id, school="VNU-UET", topic="tuition",
        chunk_text="Học phí", embedding=_vec(1.0, 0.0),
        source_url="https://x/t", span_start=0, span_end=7,
    ))

    mapping = chunk_repo.get_embedding_map_for_document(doc_id)
    key = chunk_content_hash("Học phí")
    assert key in mapping
    assert mapping[key][0] == 1.0

    assert chunk_repo.delete_chunks_for_document(doc_id) == 1
    assert chunk_repo.get_embedding_map_for_document(doc_id) == {}

    # content_hash is None until mark_ingested
    assert doc_repo.get_document_by_url("https://x/t").content_hash is None
    doc_repo.mark_ingested(doc_id, "hash-final")
    assert doc_repo.get_document_by_url("https://x/t").content_hash == "hash-final"
```

- [ ] **Step 2: Run the integration test**

Run: `pytest tests/services/knowledge/test_document_repository_integration.py -v`
Expected: PASS if Postgres+pgvector is up (`docker compose up -d db && python -m db.setup_db`), otherwise SKIPPED with the remediation message.

- [ ] **Step 3: Commit**

```bash
git add tests/services/knowledge/test_document_repository_integration.py
git commit -m "test(knowledge): gated round-trip for document repo + chunk helpers"
```

---

### Task 5: Plan-level verification

- [ ] **Step 1: Run the full plan test suite (unit only)**

Run: `pytest tests/services/knowledge/test_models.py tests/services/knowledge/test_document_repository.py tests/services/knowledge/test_chunk_helpers.py -v`
Expected: PASS.

- [ ] **Step 2: Confirm Phase 2 chunk repo behavior still green**

Run: `pytest tests/services/knowledge/test_repository.py -v`
Expected: PASS (the existing 7 tests still pass — additions are non-breaking).

## Deliverable

`KnowledgeDocumentRepository` (gate / create / mark) + `KnowledgeChunkRepository.get_embedding_map_for_document` / `delete_chunks_for_document` + the shared `chunk_content_hash`. **Consumed by Plan 05 (pipeline).**
