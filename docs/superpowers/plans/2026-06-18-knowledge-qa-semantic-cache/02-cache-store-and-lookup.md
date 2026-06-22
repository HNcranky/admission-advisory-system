# Knowledge QA Cache — Plan 02: Cache Store & Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `QACacheRepository` with the answer-row half — `store` (write) and semantic `lookup` (nearest-by-cosine within scope, gated by threshold **and** dependency-version match) — plus the `CachedAnswer` result wrapper and a `from_cache` flag on `KnowledgeQAResult`.

**Architecture:** `store` serialises a `KnowledgeQAResult` into the `answer_json` JSONB column and stamps `dep_versions` + `expires_at`. `lookup` selects the single nearest cached row in the `(school, topic)` scope that has not expired, then returns it only if cosine ≥ threshold and the row's stored `dep_versions` still equals `current_versions(scope_keys(...))`. A version mismatch (an edited **or newly added** doc bumped a dependency scope) is treated as a miss. `lookup` returns a `CachedAnswer`, whose `to_result(from_cache=True)` rebuilds a `KnowledgeQAResult`.

**Tech Stack:** Python 3.12, psycopg2 (JSONB auto-decoded to dict on read; written via `json.dumps` + `::jsonb`), pgvector cosine (`<=>`), pytest.

## Global Constraints

- **Never run `git push`.** No `Co-Authored-By` / AI attribution in commits.
- Pydantic **v2**. New DB code uses injectable `connection_factory` + `services.db.cursor`; vectors via `services.db.vector_literal`.
- Cache methods stay plain (no internal swallowing) — callers wrap for graceful degradation (Plan 03).
- pgvector dimension is `EMBEDDING_DIM = 768`.
- **Depends on Plan 01** (migration 019, `services/knowledge/qa_cache.py` with `scope_keys`/`current_versions`, and the `qa_cache_clean` integration fixture).
- Run tests with `python -m pytest -q` (system Python 3.12). Integration tests need the Docker DB.

---

### Task 1: `from_cache` flag on `KnowledgeQAResult`

**Files:**
- Modify: `services/knowledge/models.py` (the `KnowledgeQAResult` model, ~line 37)
- Test: `tests/services/knowledge/test_qa_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `KnowledgeQAResult.from_cache: bool = False` (new optional field; existing constructions unaffected).

- [ ] **Step 1: Write the failing test**

Create `tests/services/knowledge/test_qa_models.py`:

```python
from services.knowledge.models import KnowledgeQAResult


def test_from_cache_defaults_false():
    assert KnowledgeQAResult(has_data=True, answer="x").from_cache is False


def test_from_cache_can_be_set():
    assert KnowledgeQAResult(has_data=True, answer="x", from_cache=True).from_cache is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/knowledge/test_qa_models.py -v`
Expected: FAIL — `TypeError`/validation error: unexpected keyword argument `from_cache`.

- [ ] **Step 3: Add the field**

In `services/knowledge/models.py`, in `KnowledgeQAResult`, add the field after `confidence`:

```python
class KnowledgeQAResult(BaseModel):
    has_data: bool
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    from_cache: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/knowledge/test_qa_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/models.py tests/services/knowledge/test_qa_models.py
git commit -m "feat(knowledge): add from_cache flag to KnowledgeQAResult"
```

---

### Task 2: `CachedAnswer` + `store`

**Files:**
- Modify: `services/knowledge/qa_cache.py` (imports + `CachedAnswer` + `store`)
- Test: `tests/services/knowledge/test_qa_cache_repository.py` (add cases)

**Interfaces:**
- Consumes: `services.db.vector_literal`, `Citation` + `KnowledgeQAResult` from `services/knowledge/models.py`, `QACacheRepository.connection_factory`.
- Produces:
  - `CachedAnswer(answer: str, citations: list[Citation], confidence: float)` with `to_result(from_cache: bool = False) -> KnowledgeQAResult`.
  - `QACacheRepository.store(school, topic, question, embedding, result, dep_versions, ttl_days) -> None` — inserts a row; `answer_json = {answer, citations:[{source_url, chunk_text}], confidence}`; `expires_at = NOW() + ttl_days`.

- [ ] **Step 1: Write the failing tests (FakeConnection)**

Append to `tests/services/knowledge/test_qa_cache_repository.py`:

```python
from services.knowledge.models import Citation, KnowledgeQAResult
from services.knowledge.qa_cache import CachedAnswer


def test_cached_answer_to_result_sets_has_data_and_from_cache():
    ca = CachedAnswer(
        answer="Học phí 35 triệu",
        citations=[Citation(source_url="http://u", chunk_text="t")],
        confidence=0.91,
    )
    res = ca.to_result(from_cache=True)
    assert isinstance(res, KnowledgeQAResult)
    assert res.has_data is True
    assert res.answer == "Học phí 35 triệu"
    assert res.confidence == 0.91
    assert res.from_cache is True
    assert res.citations[0].source_url == "http://u"


def test_store_inserts_with_vector_and_jsonb_casts():
    connection = FakeConnection()
    repo = _repo(connection)

    result = KnowledgeQAResult(
        has_data=True,
        answer="Học phí 35 triệu",
        citations=[Citation(source_url="http://u", chunk_text="đoạn")],
        confidence=0.91,
    )
    repo.store(
        school="HUST", topic="tuition", question="học phí?",
        embedding=[0.1, 0.2, 0.3], result=result,
        dep_versions={"s:HUST|t:tuition": 1}, ttl_days=30,
    )

    sql, params = connection.cursor_obj.statements[0]
    assert "INSERT INTO knowledge_qa_cache" in sql
    assert "%s::vector" in sql
    assert sql.count("%s::jsonb") == 2          # answer_json + dep_versions
    assert "make_interval(days => %s)" in sql
    # embedding serialised as a pgvector text literal
    assert "[0.1,0.2,0.3]" in params
    # answer_json carries the answer + citations
    assert '"Học phí 35 triệu"' in "".join(p for p in params if isinstance(p, str))
    assert '"s:HUST|t:tuition": 1' in "".join(p for p in params if isinstance(p, str))
    assert 30 in params
    assert connection.committed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_repository.py -v`
Expected: FAIL — `ImportError: cannot import name 'CachedAnswer'`.

- [ ] **Step 3: Extend imports + add `CachedAnswer` + `store`**

In `services/knowledge/qa_cache.py`, change the top imports from:

```python
from services.db import cursor as _cursor
from services.knowledge.scope import NATIONAL_SCHOOL
```

to:

```python
import json
from dataclasses import dataclass

from services.db import cursor as _cursor, vector_literal as _vector_literal
from services.knowledge.models import Citation, KnowledgeQAResult
from services.knowledge.scope import NATIONAL_SCHOOL


def _load_json(value):
    """psycopg2 decodes jsonb to a Python object by default; tolerate a raw
    string/bytes too (defensive — keeps unit fakes simple)."""
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value or {}


@dataclass
class CachedAnswer:
    answer: str
    citations: list
    confidence: float

    def to_result(self, from_cache: bool = False) -> KnowledgeQAResult:
        return KnowledgeQAResult(
            has_data=True,
            answer=self.answer,
            citations=list(self.citations),
            confidence=self.confidence,
            from_cache=from_cache,
        )
```

Then add the `store` method to `QACacheRepository` (after `bump_version`):

```python
    def store(self, school, topic, question, embedding, result,
              dep_versions, ttl_days) -> None:
        answer_json = {
            "answer": result.answer or "",
            "citations": [
                {"source_url": c.source_url, "chunk_text": c.chunk_text}
                for c in result.citations
            ],
            "confidence": result.confidence,
        }
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                """
                INSERT INTO knowledge_qa_cache
                    (school, topic, question, embedding, answer_json,
                     confidence, dep_versions, expires_at)
                VALUES (%s, %s, %s, %s::vector, %s::jsonb, %s, %s::jsonb,
                        NOW() + make_interval(days => %s))
                """,
                (
                    school, topic, question, _vector_literal(embedding),
                    json.dumps(answer_json, ensure_ascii=False),
                    result.confidence,
                    json.dumps(dep_versions, ensure_ascii=False),
                    ttl_days,
                ),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_repository.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/qa_cache.py tests/services/knowledge/test_qa_cache_repository.py
git commit -m "feat(knowledge): add CachedAnswer + cache store to QACacheRepository"
```

---

### Task 3: semantic `lookup` (threshold + version gate)

**Files:**
- Modify: `services/knowledge/qa_cache.py` (add `lookup`)
- Test: `tests/services/knowledge/test_qa_cache_lookup.py`

**Interfaces:**
- Consumes: `services.db.vector_literal`, `QACacheRepository.current_versions`, `QACacheRepository.scope_keys`, `_load_json`, `CachedAnswer`, `Citation`.
- Produces: `QACacheRepository.lookup(embedding, school, topic, threshold) -> CachedAnswer | None`. Returns the nearest non-expired row in scope **only if** `cosine >= threshold` AND stored `dep_versions == current_versions(scope_keys(school, topic))`; else `None`.

- [ ] **Step 1: Write the failing tests (scripted multi-query connection)**

Create `tests/services/knowledge/test_qa_cache_lookup.py`:

```python
from services.knowledge.qa_cache import CachedAnswer, QACacheRepository


class ScriptedCursor:
    """Returns queued results per execute() call, in order.

    Each entry is a dict: {"one": <fetchone result>, "all": <fetchall result>}.
    lookup() issues the candidate query (fetchone) first, then — only on a
    threshold pass — the version query (fetchall).
    """

    def __init__(self, results):
        self._results = list(results)
        self._i = -1
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        self._i += 1

    def fetchone(self):
        return self._results[self._i].get("one")

    def fetchall(self):
        return self._results[self._i].get("all", [])

    def close(self):
        return None


class ScriptedConnection:
    def __init__(self, results):
        self.cursor_obj = ScriptedCursor(results)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def _repo(results):
    conn = ScriptedConnection(results)
    return QACacheRepository(connection_factory=lambda: conn), conn


# scope_keys("HUST", "tuition") in order:
_KEYS = QACacheRepository.scope_keys("HUST", "tuition")
_ANSWER_JSON = {
    "answer": "Học phí 35 triệu",
    "citations": [{"source_url": "http://u", "chunk_text": "đoạn"}],
    "confidence": 0.91,
}
_FRESH_VERSIONS = {k: 1 for k in _KEYS}


def test_lookup_no_candidate_returns_none():
    repo, conn = _repo([{"one": None}])
    assert repo.lookup([0.1, 0.2], "HUST", "tuition", threshold=0.95) is None
    # candidate query only — no version query when there is no row
    sql, _ = conn.cursor_obj.statements[0]
    assert "FROM knowledge_qa_cache" in sql
    assert "ORDER BY embedding <=> %s::vector" in sql
    assert "expires_at > NOW()" in sql
    assert len(conn.cursor_obj.statements) == 1


def test_lookup_below_threshold_returns_none():
    # candidate row present but cosine score 0.80 < threshold 0.95
    repo, conn = _repo([{"one": (_ANSWER_JSON, 0.91, _FRESH_VERSIONS, 0.80)}])
    assert repo.lookup([0.1, 0.2], "HUST", "tuition", threshold=0.95) is None
    assert len(conn.cursor_obj.statements) == 1   # short-circuits before versions


def test_lookup_version_mismatch_returns_none():
    # score passes; stored versions are all 1, but the DB now reports none → 0
    repo, conn = _repo([
        {"one": (_ANSWER_JSON, 0.91, _FRESH_VERSIONS, 0.99)},
        {"all": []},   # current_versions → every scope 0 → mismatch
    ])
    assert repo.lookup([0.1, 0.2], "HUST", "tuition", threshold=0.95) is None
    assert len(conn.cursor_obj.statements) == 2


def test_lookup_hit_returns_cached_answer():
    repo, conn = _repo([
        {"one": (_ANSWER_JSON, 0.91, _FRESH_VERSIONS, 0.99)},
        {"all": [(k, 1) for k in _KEYS]},   # current == stored → hit
    ])
    hit = repo.lookup([0.1, 0.2], "HUST", "tuition", threshold=0.95)
    assert isinstance(hit, CachedAnswer)
    assert hit.answer == "Học phí 35 triệu"
    assert hit.confidence == 0.91
    assert hit.citations[0].source_url == "http://u"
    assert hit.citations[0].chunk_text == "đoạn"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_lookup.py -v`
Expected: FAIL — `AttributeError: 'QACacheRepository' object has no attribute 'lookup'`.

- [ ] **Step 3: Implement `lookup`**

In `services/knowledge/qa_cache.py`, add to `QACacheRepository` (after `store`):

```python
    def lookup(self, embedding, school, topic, threshold) -> "CachedAnswer | None":
        literal = _vector_literal(embedding)
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                """
                SELECT answer_json, confidence, dep_versions,
                       1 - (embedding <=> %s::vector) AS score
                FROM knowledge_qa_cache
                WHERE school = %s AND topic = %s AND expires_at > NOW()
                ORDER BY embedding <=> %s::vector
                LIMIT 1
                """,
                (literal, school, topic, literal),
            )
            row = cur.fetchone()
        if row is None:
            return None
        answer_json, confidence, dep_versions, score = row
        if score is None or float(score) < threshold:
            return None
        stored = {k: int(v) for k, v in _load_json(dep_versions).items()}
        current = self.current_versions(self.scope_keys(school, topic))
        if stored != current:
            return None
        data = _load_json(answer_json)
        citations = [
            Citation(source_url=c.get("source_url", ""), chunk_text=c.get("chunk_text", ""))
            for c in data.get("citations", [])
        ]
        return CachedAnswer(
            answer=str(data.get("answer") or ""),
            citations=citations,
            confidence=float(confidence),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_qa_cache_lookup.py -v`
Expected: PASS (all four cases).

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/qa_cache.py tests/services/knowledge/test_qa_cache_lookup.py
git commit -m "feat(knowledge): add semantic cache lookup with version gate"
```

---

### Task 4: Integration — store→lookup round-trip, miss, stale-on-bump

**Files:**
- Test: `tests/integration/test_qa_cache_roundtrip.py`

**Interfaces:**
- Consumes: real `knowledge_qa_cache` + `knowledge_qa_cache_version` (migration 019), the full `QACacheRepository`, and the `qa_cache_clean` fixture (Plan 01 Task 5).
- Produces: end-to-end proof of HIT, distance MISS, and version-bump invalidation against real pgvector.

- [ ] **Step 1: Write the failing/real integration test**

Create `tests/integration/test_qa_cache_roundtrip.py`:

```python
import pytest

from services.knowledge.models import Citation, KnowledgeQAResult
from services.knowledge.qa_cache import QACacheRepository

pytestmark = pytest.mark.integration

_SCHOOL, _TOPIC = "ITEST", "tuition"


def _result():
    return KnowledgeQAResult(
        has_data=True,
        answer="Học phí ITEST 35 triệu/năm.",
        citations=[Citation(source_url="http://itest/fee", chunk_text="đoạn học phí")],
        confidence=0.91,
    )


def _store_fresh(repo, embedding):
    dep = repo.current_versions(repo.scope_keys(_SCHOOL, _TOPIC))
    repo.store(_SCHOOL, _TOPIC, "học phí ITEST?", embedding, _result(), dep, ttl_days=30)


def test_store_then_lookup_round_trip(db_available, qa_cache_clean):
    repo = QACacheRepository()
    vec = [0.1] * 768
    _store_fresh(repo, vec)

    hit = repo.lookup(vec, _SCHOOL, _TOPIC, threshold=0.95)
    assert hit is not None
    assert hit.answer == "Học phí ITEST 35 triệu/năm."
    assert hit.citations[0].source_url == "http://itest/fee"


def test_lookup_misses_on_distant_embedding(db_available, qa_cache_clean):
    repo = QACacheRepository()
    stored_vec = [1.0] + [0.0] * 767
    _store_fresh(repo, stored_vec)

    far_vec = [0.0, 1.0] + [0.0] * 766   # orthogonal → cosine 0
    assert repo.lookup(far_vec, _SCHOOL, _TOPIC, threshold=0.95) is None


def test_bumping_a_dependency_scope_makes_row_stale(db_available, qa_cache_clean):
    repo = QACacheRepository()
    vec = [0.1] * 768
    _store_fresh(repo, vec)
    assert repo.lookup(vec, _SCHOOL, _TOPIC, threshold=0.95) is not None

    # A new/edited doc in the school's wildcard scope bumps that version.
    repo.bump_version("s:ITEST|t:*")
    assert repo.lookup(vec, _SCHOOL, _TOPIC, threshold=0.95) is None
```

- [ ] **Step 2: Run the test (DB up)**

Run: `python -m pytest tests/integration/test_qa_cache_roundtrip.py -v`
Expected: PASS with the Docker DB up (else SKIP). If a real failure surfaces (e.g. JSONB decode or vector dim), debug with superpowers:systematic-debugging before proceeding.

- [ ] **Step 3: Run the whole knowledge + cache slice for regressions**

Run: `python -m pytest tests/services/knowledge tests/integration -q -k "qa_cache or knowledge"`
Expected: PASS (DB-dependent tests SKIP when the DB is down).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_qa_cache_roundtrip.py
git commit -m "test(knowledge): integration round-trip + stale-on-bump for QA cache"
```

---

## Self-Review (run after completing all tasks)

- **Spec coverage:** `lookup` nearest-by-cosine within `(school, topic)` + `expires_at > NOW()`, threshold gate, version-equality gate (✓ Task 3); `store` with `answer_json`/`dep_versions`/TTL (✓ Task 2); `CachedAnswer.to_result(from_cache=True)` + `from_cache` field (✓ Tasks 1-2); integration round-trip, distance miss, stale-on-bump (✓ Task 4). The "additions bump a scope → stale even if not cited" case is exercised by `test_bumping_a_dependency_scope_makes_row_stale`.
- **No placeholders:** all steps contain runnable code/SQL and exact commands.
- **Type consistency:** `lookup` returns `CachedAnswer | None`; `CachedAnswer.to_result` returns `KnowledgeQAResult` (consumed by Plan 03's `answer()` via `hit.to_result(from_cache=True)`). `store` signature `(school, topic, question, embedding, result, dep_versions, ttl_days)` matches the Plan 03 call site exactly.
