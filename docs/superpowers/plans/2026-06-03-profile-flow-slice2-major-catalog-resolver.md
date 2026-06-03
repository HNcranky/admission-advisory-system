# Slice 2 — Program Catalog + Tiered Major Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ánh xạ `free-text sở thích → program_id` mà **thêm ngành không phải sửa prompt/map** — bằng catalog ngành sống trong DB + matcher 3 tầng (alias → embedding pgvector → LLM chọn shortlist).

**Architecture:** Migration `015` tạo bảng `program_catalog_embeddings`. `build_major_catalog()` suy danh mục từ `canonical_admission_records`, embed bằng `GeminiEmbedder` (reuse theo `content_hash`), upsert. `resolve_majors()` chạy Tier1 alias (tái dùng `extract_preferred_majors`), Tier2 vector search top-K, Tier3 LLM chọn tập con trong shortlist. Cuối cùng cắm `resolve_majors` vào `build_profile_with_gateway`, **xóa** `MAJOR_ID_GUIDE`/`INTEREST_MAJOR_MAP`.

**Tech Stack:** Python 3, Postgres + pgvector (HNSW cosine), `google.genai` embeddings (768-dim, L2-normalized), Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-06-03-profile-flow-dst-redesign-design.md` §6. **Phụ thuộc:** Slice 1 (registry) đã merge.

> **Quy ước repo (CLAUDE.md):** KHÔNG `git push`; không attribution AI trong commit. Repository nhận `connection_factory` + dùng `_cursor` context manager (không hand-roll `conn.close()`). LLM/embedding call phải degrade gracefully + `logger.warning`.

---

## File Structure

- **Create** `db/migrations/015_program_catalog_embeddings.sql` — bảng + index.
- **Create** `services/profile/major_catalog_repository.py` — `ProgramCatalogRepository`, `ProgramCandidate`.
- **Create** `services/profile/major_catalog.py` — `build_major_catalog()` + helpers `_embed_input`, `_enrich`, `_load_canonical_programs`, `CatalogBuildReport`.
- **Create** `services/profile/build_major_catalog.py` — CLI `python -m services.profile.build_major_catalog`.
- **Create** `services/profile/major_resolver.py` — `resolve_majors()` + Tier3 helper.
- **Create** `tests/services/profile/test_major_resolver.py` — unit (fakes).
- **Create** `tests/services/profile/test_major_catalog_build.py` — unit (fakes).
- **Create** `tests/integration/test_major_catalog_integration.py` — DB smoke (skip nếu không có DB).
- **Modify** `services/profile_inference_service.py` — cắm `resolve_majors`, xóa `MAJOR_ID_GUIDE`/`INTEREST_MAJOR_MAP`/`_normalize_major_ids`/`_normalize_profile`.
- **Modify** `db/setup_db.py` — thêm `program_catalog_embeddings` vào `expected`.

---

## Task 1: Migration 015 — bảng `program_catalog_embeddings`

**Files:**
- Create: `db/migrations/015_program_catalog_embeddings.sql`
- Modify: `db/setup_db.py:101-113` (list `expected`)
- Test: `tests/integration/test_major_catalog_integration.py`

- [ ] **Step 1: Viết test integration thất bại (bảng tồn tại + search rỗng)**

Create `tests/integration/test_major_catalog_integration.py`:

```python
import pytest

from ingestion.storage.db_connection import get_connection


def _db_or_skip():
    try:
        conn = get_connection()
    except Exception:
        pytest.skip("Postgres not available")
    return conn


def test_program_catalog_table_exists():
    conn = _db_or_skip()
    try:
        cur = conn.cursor()
        cur.execute("SELECT to_regclass('public.program_catalog_embeddings')")
        assert cur.fetchone()[0] is not None, "run: python -m db.setup_db (migration 015)"
    finally:
        conn.close()
```

- [ ] **Step 2: Chạy để xác nhận FAIL/skip**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_major_catalog_integration.py -v`
Expected: nếu có DB → FAIL (`assert ... is not None`); nếu không có DB → SKIP.

- [ ] **Step 3: Viết migration**

Create `db/migrations/015_program_catalog_embeddings.sql`:

```sql
-- Catalog ngành để ánh xạ free-text -> program_id bằng semantic retrieval.
-- embedding là vector(768) — phải khớp ingestion.config.settings.EMBEDDING_DIM
-- và knowledge_chunks (migration 013).
CREATE TABLE IF NOT EXISTS program_catalog_embeddings (
    program_id      TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    aliases_text    TEXT NOT NULL DEFAULT '',
    field           TEXT,
    embed_input     TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    embedding       vector(768),
    source          TEXT NOT NULL DEFAULT 'canonical',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_embedding
    ON program_catalog_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_program_catalog_content_hash
    ON program_catalog_embeddings (content_hash);
```

- [ ] **Step 4: Thêm bảng vào `expected` của `db/setup_db.py`**

Trong list `expected` (kết thúc bằng `"knowledge_chunks",`), thêm dòng:

```python
    "knowledge_chunks",
    "program_catalog_embeddings",
]
```

- [ ] **Step 5: Áp migration & chạy lại test**

Run: `.\.venv\Scripts\python.exe -m db.setup_db`
Then: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_major_catalog_integration.py -v`
Expected: PASS (nếu có DB) — bảng tồn tại.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/015_program_catalog_embeddings.sql db/setup_db.py tests/integration/test_major_catalog_integration.py
git commit -m "feat(profile): add program_catalog_embeddings table (slice 2)"
```

---

## Task 2: `ProgramCatalogRepository`

**Files:**
- Create: `services/profile/major_catalog_repository.py`
- Test: `tests/integration/test_major_catalog_integration.py` (mở rộng)

- [ ] **Step 1: Viết test integration thất bại cho upsert + vector_search**

Append vào `tests/integration/test_major_catalog_integration.py`:

```python
from services.profile.major_catalog_repository import ProgramCatalogRepository


def test_upsert_and_vector_search_roundtrip():
    _db_or_skip().close()
    repo = ProgramCatalogRepository()
    vec = [0.0] * 768
    vec[0] = 1.0
    repo.upsert_program(
        program_id="__test_cs__", canonical_name="Khoa học Máy tính",
        aliases_text="computer science, cntt", field="technology",
        embed_input="Khoa học Máy tính. computer science, cntt",
        content_hash="hash_test_cs", embedding=vec, source="canonical",
    )
    hits = repo.vector_search_programs(vec, limit=5)
    ids = [h.program_id for h in hits]
    assert "__test_cs__" in ids
    top = next(h for h in hits if h.program_id == "__test_cs__")
    assert top.score > 0.99  # cùng vector → cosine ~1

    hashes = repo.get_program_content_hashes()
    assert hashes.get("__test_cs__") == "hash_test_cs"

    # cleanup
    repo.delete_program("__test_cs__")
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_major_catalog_integration.py::test_upsert_and_vector_search_roundtrip -v`
Expected: FAIL — `ModuleNotFoundError: services.profile.major_catalog_repository`.

- [ ] **Step 3: Viết repository**

Create `services/profile/major_catalog_repository.py`:

```python
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional

from ingestion.storage.db_connection import get_connection


@dataclass
class ProgramCandidate:
    program_id: str
    canonical_name: str
    score: float


def _vector_literal(embedding) -> Optional[str]:
    if embedding is None:
        return None
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


@contextmanager
def _cursor(connection_factory, commit: bool = False):
    """Yield a cursor, đảm bảo commit/rollback + cleanup connection."""
    conn = connection_factory()
    try:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


class ProgramCatalogRepository:
    def __init__(self, connection_factory=get_connection):
        self.connection_factory = connection_factory

    def upsert_program(self, *, program_id, canonical_name, aliases_text, field,
                       embed_input, content_hash, embedding, source="canonical") -> None:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                """
                INSERT INTO program_catalog_embeddings
                    (program_id, canonical_name, aliases_text, field,
                     embed_input, content_hash, embedding, source, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, NOW())
                ON CONFLICT (program_id) DO UPDATE SET
                    canonical_name = EXCLUDED.canonical_name,
                    aliases_text   = EXCLUDED.aliases_text,
                    field          = EXCLUDED.field,
                    embed_input    = EXCLUDED.embed_input,
                    content_hash   = EXCLUDED.content_hash,
                    embedding      = EXCLUDED.embedding,
                    source         = EXCLUDED.source,
                    updated_at     = NOW()
                """,
                (program_id, canonical_name, aliases_text, field,
                 embed_input, content_hash, _vector_literal(embedding), source),
            )

    def get_program_content_hashes(self) -> Dict[str, str]:
        """{program_id: content_hash} cho các dòng đã có embedding (để skip re-embed)."""
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                "SELECT program_id, content_hash FROM program_catalog_embeddings "
                "WHERE embedding IS NOT NULL"
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def vector_search_programs(self, embedding, limit: int = 8) -> List[ProgramCandidate]:
        literal = _vector_literal(embedding)
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                """
                SELECT program_id, canonical_name,
                       1 - (embedding <=> %s::vector) AS score
                FROM program_catalog_embeddings
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (literal, literal, limit),
            )
            return [ProgramCandidate(r[0], r[1], float(r[2])) for r in cur.fetchall()]

    def delete_program(self, program_id: str) -> None:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                "DELETE FROM program_catalog_embeddings WHERE program_id = %s",
                (program_id,),
            )

    def count(self) -> int:
        with _cursor(self.connection_factory) as cur:
            cur.execute("SELECT COUNT(*) FROM program_catalog_embeddings")
            return cur.fetchone()[0]
```

- [ ] **Step 4: Chạy lại test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_major_catalog_integration.py -v`
Expected: PASS (hoặc SKIP nếu không DB).

- [ ] **Step 5: Commit**

```bash
git add services/profile/major_catalog_repository.py tests/integration/test_major_catalog_integration.py
git commit -m "feat(profile): ProgramCatalogRepository with pgvector search (slice 2)"
```

---

## Task 3: `build_major_catalog()` (unit-testable với fakes)

**Files:**
- Create: `services/profile/major_catalog.py`
- Test: `tests/services/profile/test_major_catalog_build.py`

- [ ] **Step 1: Viết test thất bại với fake repo/embedder**

Create `tests/services/profile/test_major_catalog_build.py`:

```python
from services.profile.major_catalog import build_major_catalog, _embed_input
from services.knowledge.repository import chunk_content_hash


class FakeEmbedder:
    def __init__(self):
        self.embedded_texts = []

    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        self.embedded_texts.extend(texts)
        return [[0.1] * 768 for _ in texts]


class FakeBuildRepo:
    def __init__(self, existing=None):
        self._existing = existing or {}
        self.upserts = []

    def get_program_content_hashes(self):
        return dict(self._existing)

    def upsert_program(self, **kwargs):
        self.upserts.append(kwargs)


def _no_enrich(program_id):
    return ("", None)


def test_build_embeds_new_programs():
    rows = [("computer_science", "Khoa học Máy tính"),
            ("software_engineering", "Kỹ thuật Phần mềm")]
    repo, emb = FakeBuildRepo(), FakeEmbedder()
    report = build_major_catalog(source_programs=lambda: rows, repository=repo,
                                 embedder=emb, enrich=_no_enrich)
    assert report.total == 2
    assert report.embedded == 2
    assert report.reused == 0
    assert len(repo.upserts) == 2
    assert len(emb.embedded_texts) == 2


def test_build_skips_unchanged_by_content_hash():
    rows = [("computer_science", "Khoa học Máy tính")]
    unchanged_hash = chunk_content_hash(_embed_input("Khoa học Máy tính", ""))
    repo = FakeBuildRepo(existing={"computer_science": unchanged_hash})
    emb = FakeEmbedder()
    report = build_major_catalog(source_programs=lambda: rows, repository=repo,
                                 embedder=emb, enrich=_no_enrich)
    assert report.embedded == 0
    assert report.reused == 1
    assert repo.upserts == []           # không upsert dòng không đổi
    assert emb.embedded_texts == []     # không gọi embed


def test_build_skips_rows_without_program_id():
    rows = [(None, "Không có id"), ("law", "Luật")]
    repo, emb = FakeBuildRepo(), FakeEmbedder()
    report = build_major_catalog(source_programs=lambda: rows, repository=repo,
                                 embedder=emb, enrich=_no_enrich)
    assert report.total == 1
    assert [u["program_id"] for u in repo.upserts] == ["law"]
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_major_catalog_build.py -v`
Expected: FAIL — `ModuleNotFoundError: services.profile.major_catalog`.

- [ ] **Step 3: Viết `major_catalog.py`**

Create `services/profile/major_catalog.py`:

```python
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from ingestion.knowledge.embedder import GeminiEmbedder
from services.knowledge.repository import chunk_content_hash
from services.profile.major_catalog_repository import ProgramCatalogRepository
from services.profile_service import load_program_aliases

logger = logging.getLogger(__name__)


@dataclass
class CatalogBuildReport:
    total: int
    embedded: int
    reused: int


def _embed_input(canonical_name: str, aliases_text: str) -> str:
    base = (canonical_name or "").strip()
    aliases_text = (aliases_text or "").strip()
    return f"{base}. Tên gọi khác: {aliases_text}" if aliases_text else base


def _enrich(program_id: str) -> Tuple[str, Optional[str]]:
    """aliases_text + field từ programs.json nếu khớp program_id; else ("", None)."""
    alias_map = load_program_aliases()
    payload = alias_map.get(program_id)
    if not payload:
        return ("", None)
    aliases = [a for a in payload.get("aliases", []) if a]
    return (", ".join(aliases), None)


def _load_canonical_programs() -> List[Tuple[Optional[str], str]]:
    from ingestion.storage.db_connection import get_cursor
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT DISTINCT program_id, program_name_canonical "
            "FROM canonical_admission_records"
        )
        return [(row[0], row[1] or "") for row in cur.fetchall()]


def build_major_catalog(*, source_programs: Optional[Callable] = None,
                        repository: Optional[ProgramCatalogRepository] = None,
                        embedder=None, enrich: Optional[Callable] = None) -> CatalogBuildReport:
    source_programs = source_programs or _load_canonical_programs
    repository = repository or ProgramCatalogRepository()
    embedder = embedder or GeminiEmbedder()
    enrich = enrich or _enrich

    existing = repository.get_program_content_hashes()

    prepared = []
    for program_id, canonical_name in source_programs():
        if not program_id:
            continue
        aliases_text, field = enrich(program_id)
        embed_input = _embed_input(canonical_name, aliases_text)
        content_hash = chunk_content_hash(embed_input)
        prepared.append((program_id, canonical_name, aliases_text, field, embed_input, content_hash))

    to_embed = [(p[0], p[4]) for p in prepared if existing.get(p[0]) != p[5]]
    vectors = {}
    if to_embed:
        embeddings = embedder.embed([t for _, t in to_embed], task_type="RETRIEVAL_DOCUMENT")
        vectors = {pid: emb for (pid, _), emb in zip(to_embed, embeddings)}

    embedded = reused = 0
    for program_id, canonical_name, aliases_text, field, embed_input, content_hash in prepared:
        emb = vectors.get(program_id)
        if emb is None:
            reused += 1
            continue
        repository.upsert_program(
            program_id=program_id, canonical_name=canonical_name,
            aliases_text=aliases_text, field=field, embed_input=embed_input,
            content_hash=content_hash, embedding=emb, source="canonical",
        )
        embedded += 1

    logger.info("major catalog build: total=%d embedded=%d reused=%d",
                len(prepared), embedded, reused)
    return CatalogBuildReport(total=len(prepared), embedded=embedded, reused=reused)
```

> `load_program_aliases` đã tồn tại trong `services/profile_service.py` và trả `{program_id: {canonical_name, aliases(normalized)}}`.

- [ ] **Step 4: Chạy lại test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_major_catalog_build.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/profile/major_catalog.py tests/services/profile/test_major_catalog_build.py
git commit -m "feat(profile): build_major_catalog with content-hash reuse (slice 2)"
```

---

## Task 4: CLI `python -m services.profile.build_major_catalog`

**Files:**
- Create: `services/profile/build_major_catalog.py`

- [ ] **Step 1: Viết CLI**

Create `services/profile/build_major_catalog.py`:

```python
import sys

from services.profile.major_catalog import build_major_catalog


def main() -> int:
    report = build_major_catalog()
    print(f"program catalog: total={report.total} embedded={report.embedded} reused={report.reused}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Chạy thử (cần DB + ingest dữ liệu trước)**

Run: `.\.venv\Scripts\python.exe -m services.profile.build_major_catalog`
Expected: in dòng `program catalog: total=… embedded=… reused=…`. Nếu chưa ingest record nào, `total=0` (vẫn hợp lệ). Chạy lần 2 → `embedded=0 reused=total` (reuse hoạt động).

- [ ] **Step 3: Commit**

```bash
git add services/profile/build_major_catalog.py
git commit -m "feat(profile): CLI to build/refresh program catalog (slice 2)"
```

---

## Task 5: `resolve_majors()` — Tier 1 alias

**Files:**
- Create: `services/profile/major_resolver.py`
- Test: `tests/services/profile/test_major_resolver.py`

- [ ] **Step 1: Viết test thất bại cho Tier1 (short-circuit, không gọi DB/embedder)**

Create `tests/services/profile/test_major_resolver.py`:

```python
import pytest

from services.profile.major_resolver import resolve_majors


class ExplodingRepo:
    def vector_search_programs(self, embedding, limit=8):
        raise AssertionError("Tier2 không được gọi khi Tier1 đã khớp")


class ExplodingEmbedder:
    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        raise AssertionError("embedder không được gọi khi Tier1 đã khớp")


def test_tier1_alias_match_short_circuits():
    # "kỹ thuật phần mềm" là alias của software_engineering trong programs.json.
    result = resolve_majors("em muốn học kỹ thuật phần mềm",
                            repository=ExplodingRepo(), embedder=ExplodingEmbedder())
    assert "software_engineering" in result
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_major_resolver.py -v`
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Viết khung resolver + Tier 1**

Create `services/profile/major_resolver.py`:

```python
import logging
from typing import List, Optional

from services.inference.models import InferenceError
from services.profile_service import extract_preferred_majors, normalize_text

logger = logging.getLogger(__name__)


def _dedupe(items: List[str]) -> List[str]:
    return list(dict.fromkeys(items))


def resolve_majors(text: str, *, known_state=None, top_k: int = 8,
                   score_threshold: float = 0.55, high_threshold: float = 0.70,
                   margin: float = 0.08, gateway=None, embedder=None,
                   repository=None) -> List[str]:
    """Free-text -> list[program_id]. Tiered, deterministic-first."""
    text = text or ""

    # Tier 1 — alias/exact match (rẻ, không LLM/embedding).
    hits = extract_preferred_majors(normalize_text(text))
    if hits:
        return _dedupe(hits)

    return []  # Tier 2/3 thêm ở Task 6/7
```

> `extract_preferred_majors` đã tồn tại; nhận text đã normalize, trả list program_id theo alias `programs.json`.

- [ ] **Step 4: Chạy lại test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_major_resolver.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add services/profile/major_resolver.py tests/services/profile/test_major_resolver.py
git commit -m "feat(profile): major resolver Tier1 alias matching (slice 2)"
```

---

## Task 6: `resolve_majors()` — Tier 2 embedding retrieval

**Files:**
- Modify: `services/profile/major_resolver.py`
- Test: `tests/services/profile/test_major_resolver.py`

- [ ] **Step 1: Viết test thất bại cho Tier2 (confident + degrade)**

Append vào `tests/services/profile/test_major_resolver.py`:

```python
from services.profile.major_catalog_repository import ProgramCandidate


class FakeEmbedderOK:
    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        return [[0.2] * 768 for _ in texts]


class FakeRepo:
    def __init__(self, candidates):
        self._candidates = candidates

    def vector_search_programs(self, embedding, limit=8):
        return self._candidates[:limit]


class FailingEmbedder:
    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        raise RuntimeError("embedding service down")


def test_tier2_confident_single_strong_candidate_returns_it():
    # Không khớp alias → vào Tier2. 1 ứng viên mạnh trên high_threshold.
    repo = FakeRepo([ProgramCandidate("data_science", "Khoa học Dữ liệu", 0.82)])
    result = resolve_majors("em thích phân tích dữ liệu lớn",
                            repository=repo, embedder=FakeEmbedderOK())
    assert result == ["data_science"]


def test_tier2_below_threshold_returns_empty():
    repo = FakeRepo([ProgramCandidate("law", "Luật", 0.40)])
    result = resolve_majors("câu nói mơ hồ",
                            repository=repo, embedder=FakeEmbedderOK())
    assert result == []


def test_tier2_embedder_failure_degrades_to_empty():
    repo = FakeRepo([ProgramCandidate("x", "X", 0.9)])
    result = resolve_majors("bất kỳ", repository=repo, embedder=FailingEmbedder())
    assert result == []
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_major_resolver.py -v`
Expected: FAIL — Tier2 chưa có (đang return []), `test_tier2_confident_...` mong `["data_science"]`.

- [ ] **Step 3: Cài Tier 2**

Trong `services/profile/major_resolver.py`, thay `return []  # Tier 2/3 ...` bằng:

```python
    # Tier 2 — embedding retrieval top-K từ DB (scale theo catalog, prompt cố định).
    from services.profile.major_catalog_repository import ProgramCatalogRepository
    repository = repository or ProgramCatalogRepository()
    if embedder is None:
        from ingestion.knowledge.embedder import GeminiEmbedder
        embedder = GeminiEmbedder()

    try:
        query_vec = embedder.embed([text], task_type="RETRIEVAL_QUERY")[0]
        candidates = repository.vector_search_programs(query_vec, limit=top_k)
    except Exception as exc:  # embedding/DB lỗi → degrade
        logger.warning("major resolver Tier2 embedding/search failed: %r", exc)
        return []

    strong = [c for c in candidates if c.score >= score_threshold]
    if not strong:
        return []

    confident = len(strong) == 1 or (strong[0].score - strong[1].score) > margin
    if confident:
        top = [c.program_id for c in strong if c.score >= high_threshold]
        return top or [strong[0].program_id]

    return [strong[0].program_id]  # Tier 3 thay phần này ở Task 7
```

- [ ] **Step 4: Chạy lại test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_major_resolver.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/profile/major_resolver.py tests/services/profile/test_major_resolver.py
git commit -m "feat(profile): major resolver Tier2 pgvector retrieval + degrade (slice 2)"
```

---

## Task 7: `resolve_majors()` — Tier 3 LLM chọn trong shortlist

**Files:**
- Modify: `services/profile/major_resolver.py`
- Test: `tests/services/profile/test_major_resolver.py`

- [ ] **Step 1: Viết test thất bại cho Tier3 (ambiguous → LLM chọn; LLM lỗi → fallback)**

Append vào `tests/services/profile/test_major_resolver.py`:

```python
from services.inference.models import InferenceError, InferenceResult


class FakeGatewayPick:
    def __init__(self, program_ids):
        self._ids = program_ids
        self.calls = 0

    def run(self, request):
        self.calls += 1
        return InferenceResult(
            agent_name=request.agent_name, model="fake", provider="fake",
            content="{}", parsed_data={"program_ids": self._ids},
        )


class FailingGateway:
    def run(self, request):
        raise InferenceError("llm down")


def _ambiguous_repo():
    # hai ứng viên sát điểm (< margin) → Tier3.
    return FakeRepo([
        ProgramCandidate("computer_science", "Khoa học Máy tính", 0.66),
        ProgramCandidate("software_engineering", "Kỹ thuật Phần mềm", 0.63),
    ])


def test_tier3_llm_picks_subset_from_shortlist():
    gw = FakeGatewayPick(["software_engineering"])
    result = resolve_majors("em thích tạo sản phẩm phần mềm",
                            repository=_ambiguous_repo(), embedder=FakeEmbedderOK(), gateway=gw)
    assert result == ["software_engineering"]
    assert gw.calls == 1


def test_tier3_filters_out_ids_not_in_shortlist():
    gw = FakeGatewayPick(["software_engineering", "hallucinated_id"])
    result = resolve_majors("...", repository=_ambiguous_repo(),
                            embedder=FakeEmbedderOK(), gateway=gw)
    assert result == ["software_engineering"]  # id ngoài shortlist bị loại


def test_tier3_llm_failure_falls_back_to_top_embedding():
    result = resolve_majors("...", repository=_ambiguous_repo(),
                            embedder=FakeEmbedderOK(), gateway=FailingGateway())
    assert result == ["computer_science"]  # top embedding


def test_tier3_not_called_when_confident():
    gw = FakeGatewayPick(["should_not_be_used"])
    repo = FakeRepo([ProgramCandidate("data_science", "KHDL", 0.85)])
    result = resolve_majors("phân tích dữ liệu", repository=repo,
                            embedder=FakeEmbedderOK(), gateway=gw)
    assert result == ["data_science"]
    assert gw.calls == 0  # confident → skip LLM (minimize_num_calls)
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_major_resolver.py -v`
Expected: FAIL — `test_tier3_llm_picks_subset_from_shortlist` mong `["software_engineering"]` nhưng đang trả `["computer_science"]` (placeholder Task 6).

- [ ] **Step 3: Cài Tier 3**

Trong `services/profile/major_resolver.py`, thay dòng `return [strong[0].program_id]  # Tier 3 ...` bằng:

```python
    # Tier 3 — LLM chọn TẬP CON liên quan trong shortlist (prompt = K ứng viên, cố định).
    if gateway is None:
        from services import build_default_gateway
        gateway = build_default_gateway()
    try:
        picked = _llm_pick_from_shortlist(text, strong, gateway)
        allowed = {c.program_id for c in strong}
        picked = [p for p in picked if p in allowed]
        return picked or [strong[0].program_id]
    except InferenceError as exc:
        logger.warning("major resolver Tier3 LLM failed, dùng top embedding: %r", exc)
        return [strong[0].program_id]
```

Và thêm helper ở cuối file:

```python
_PICK_PROMPT = (
    "Người dùng mô tả sở thích/định hướng học tập. Cho danh sách ngành ứng viên "
    "(id: tên). Chọn các id NGÀNH PHÙ HỢP NHẤT (có thể nhiều, có thể một). "
    'Trả JSON {"program_ids": [...]} chỉ gồm id trong danh sách, không giải thích.'
)


def _llm_pick_from_shortlist(text: str, strong, gateway) -> List[str]:
    from services.inference.models import InferenceRequest
    shortlist = "\n".join(f"- {c.program_id}: {c.canonical_name}" for c in strong)
    result = gateway.run(InferenceRequest(
        agent_name="major_resolver",
        task_type="major_disambiguation",
        system_prompt=_PICK_PROMPT,
        user_prompt=f'Mô tả: "{text}"\n\nỨng viên:\n{shortlist}',
        output_mode="json",
        temperature=0.0,
    ))
    data = result.parsed_data or {}
    ids = data.get("program_ids") or []
    return [str(i) for i in ids if isinstance(i, (str,))]
```

- [ ] **Step 4: Chạy lại test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_major_resolver.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add services/profile/major_resolver.py tests/services/profile/test_major_resolver.py
git commit -m "feat(profile): major resolver Tier3 LLM shortlist pick (slice 2)"
```

---

## Task 8: Cắm `resolve_majors` vào extraction & xóa hardcode

**Files:**
- Modify: `services/profile_inference_service.py`
- Test: `tests/agents/test_profile_agent.py`, `tests/services/profile/test_profile_inference_resolver.py` (mới)

- [ ] **Step 1: Viết test thất bại — extraction dùng resolver, không dùng MAJOR_ID_GUIDE**

Create `tests/services/profile/test_profile_inference_resolver.py`:

```python
import services.profile_inference_service as pis
from services.inference.models import InferenceResult


class FakeGateway:
    def is_available(self):
        return True

    def run(self, request):
        # LLM KHÔNG còn trả preferred_majors (id) nữa — chỉ các slot khác.
        return InferenceResult(
            agent_name=request.agent_name, model="fake", provider="fake",
            content="{}", parsed_data={"total_score": 26.0},
        )


def test_extraction_uses_resolver_for_majors(monkeypatch):
    monkeypatch.setattr(pis, "resolve_majors",
                        lambda text, **kw: ["software_engineering"])
    profile = pis.build_profile_with_gateway("em thích làm app", FakeGateway())
    assert profile.preferred_majors == ["software_engineering"]
    assert profile.total_score == 26.0
    assert "preferred_majors" not in profile.missing_slots


def test_no_hardcoded_major_maps_remain():
    assert not hasattr(pis, "INTEREST_MAJOR_MAP")
    assert not hasattr(pis, "MAJOR_ID_GUIDE")
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_profile_inference_resolver.py -v`
Expected: FAIL — `MAJOR_ID_GUIDE`/`INTEREST_MAJOR_MAP` còn tồn tại; `resolve_majors` chưa được dùng.

- [ ] **Step 3: Viết lại `services/profile_inference_service.py`**

Thay toàn bộ nội dung file bằng (xóa `MAJOR_ID_GUIDE`, `INTEREST_MAJOR_MAP`, `_normalize_major_ids`, `_normalize_profile`; prompt không liệt kê id ngành; majors do resolver lo):

```python
import logging

from pydantic import ValidationError

from agents.models import StudentProfile
from services.inference.models import InferenceError, InferenceRequest
from services.profile.major_resolver import resolve_majors
from services.profile.slots import missing_critical_slots
from services.profile_service import build_profile

logger = logging.getLogger(__name__)


PROFILE_SYSTEM_PROMPT = """
Trích xuất hồ sơ tư vấn tuyển sinh từ tin nhắn của học sinh Việt Nam.
Trả JSON với các khóa (dùng null cho vô hướng chưa biết, [] cho list chưa biết):
- total_score: số hoặc null
- subject_combination: mã tổ hợp như "A00", "A01", "D01" hoặc null
- preferred_schools: danh sách trường học sinh nhắc tới
- location_preference: tỉnh/khu vực muốn học (vd "Ha Noi", "Mien Bac") hoặc null
- tuition_budget: chuỗi mô tả ngân sách học phí hoặc null
- constraints: list ràng buộc khác (gia đình, học bổng, công việc) hoặc []
KHÔNG cần trả preferred_majors — hệ thống tự suy ngành từ sở thích.
"""


def build_profile_with_gateway(user_query: str, gateway) -> StudentProfile:
    if hasattr(gateway, "is_available") and not gateway.is_available():
        profile = build_profile(user_query)
    else:
        try:
            result = gateway.run(
                InferenceRequest(
                    agent_name="profile_agent",
                    task_type="profile_extraction",
                    system_prompt=PROFILE_SYSTEM_PROMPT.strip(),
                    user_prompt=user_query,
                    output_mode="json",
                    temperature=0.0,
                )
            )
        except InferenceError as exc:
            logger.warning("profile extraction gateway failed, using rule-based: %r", exc)
            profile = build_profile(user_query)
        else:
            try:
                data = dict(result.parsed_data or {})
                data.pop("preferred_majors", None)  # majors do resolver lo
                data.pop("missing_slots", None)
                profile = StudentProfile(**data)
            except ValidationError as exc:
                logger.warning("profile JSON failed schema validation, using rule-based: %r", exc)
                profile = build_profile(user_query)

    # preferred_majors: tiered resolver (alias -> embedding -> LLM). Degrade -> [].
    try:
        majors = resolve_majors(user_query, known_state=profile)
    except Exception as exc:  # an toàn tuyệt đối: không bao giờ raise lên caller
        logger.warning("resolve_majors failed: %r", exc)
        majors = []
    if majors:
        profile.preferred_majors = majors
    elif not profile.preferred_majors:
        # giữ alias-hit từ build_profile (rule path) nếu có; else rỗng
        profile.preferred_majors = profile.preferred_majors

    profile.missing_slots = missing_critical_slots(profile)
    return profile
```

> Ghi chú: `build_profile` (rule path) vẫn tự chạy Tier1 alias qua `extract_preferred_majors`, nên fallback offline vẫn có ngành khi user nhắc tên rõ ràng.

- [ ] **Step 4: Chạy test mới + test profile_agent hiện có**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_profile_inference_resolver.py tests/agents/test_profile_agent.py -v`
Expected: PASS test mới. Với `tests/agents/test_profile_agent.py`:
- `test_profile_agent_uses_injected_gateway` dùng FakeGateway trả `{"preferred_majors":["economics"],...}`. Sau thay đổi, `preferred_majors` từ LLM bị bỏ và resolver chạy trên "Em muon hoc nganh kinh te". `economics` là alias? Kiểm tra `programs.json` (economics có alias "kinh tế"/"economics"). Nếu Tier1 khớp → `["economics"]`, test vẫn assert đúng. **Nếu không khớp** (do resolver gọi embedder thật → lỗi/None trong môi trường test) → cập nhật test đó để monkeypatch `resolve_majors` trả `["economics"]` (giống Step 1). Áp dụng monkeypatch tương tự cho 2 test extract còn lại.

- [ ] **Step 5: Sửa các test profile_agent bị ảnh hưởng (nếu cần)**

Trong `tests/agents/test_profile_agent.py`, các test gọi `profile_agent` thật qua `build_profile_with_gateway` (chỉ `test_profile_agent_uses_injected_gateway`). Thêm đầu test:

```python
    import services.profile_inference_service as pis
    monkeypatch.setattr(pis, "resolve_majors", lambda text, **kw: ["economics"])
```

(thêm tham số `monkeypatch` vào test). Các test khác đã monkeypatch `build_profile_with_gateway` nên không ảnh hưởng.

- [ ] **Step 6: Chạy full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS. Sửa nốt nếu còn test tham chiếu symbol đã xóa.

- [ ] **Step 7: Commit**

```bash
git add services/profile_inference_service.py tests/services/profile/test_profile_inference_resolver.py tests/agents/test_profile_agent.py
git commit -m "feat(profile): use tiered resolver for majors, drop hardcoded major maps (slice 2, G1)"
```

---

## Task 9: Test chống hồi quy cho G1 — thêm program_id mới không cần sửa code

**Files:**
- Create: `tests/services/profile/test_resolver_scales.py`

- [ ] **Step 1: Viết test khẳng định catalog mở rộng được mà không đụng prompt/map**

Create `tests/services/profile/test_resolver_scales.py`:

```python
from services.profile.major_catalog_repository import ProgramCandidate
from services.profile.major_resolver import resolve_majors


class FakeEmbedder:
    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        return [[0.3] * 768 for _ in texts]


class FakeRepo:
    def __init__(self, candidates):
        self._candidates = candidates

    def vector_search_programs(self, embedding, limit=8):
        return self._candidates[:limit]


def test_brand_new_program_id_resolves_without_code_change():
    """Ngành mới 'quantum_computing' chỉ tồn tại trong catalog (DB), KHÔNG nằm
    trong bất kỳ prompt/map hardcode nào — resolver vẫn trả về được."""
    repo = FakeRepo([ProgramCandidate("quantum_computing", "Máy tính Lượng tử", 0.88)])
    result = resolve_majors("em mê máy tính lượng tử và vật lý",
                            repository=repo, embedder=FakeEmbedder())
    assert result == ["quantum_computing"]
```

- [ ] **Step 2: Chạy để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_resolver_scales.py -v`
Expected: PASS — chứng minh G1 (thêm ngành = thêm dòng catalog, không sửa code).

- [ ] **Step 3: Commit**

```bash
git add tests/services/profile/test_resolver_scales.py
git commit -m "test(profile): regression guard — new program_id resolves via catalog only (slice 2)"
```

---

## Self-Review (đã thực hiện khi viết plan)

**Spec coverage (§6):** Migration 015 (Task 1); repository pgvector (Task 2); build + content-hash reuse + nguồn canonical store (Task 3); CLI refresh §10-B (Task 4); resolver Tier1/2/3 + degrade + minimize_num_calls (Task 5–7); cắm vào extraction + xóa hardcode = G1 (Task 8); regression G1 (Task 9). ✔

**Placeholder scan:** Không TBD/TODO; mọi step có code/command. Placeholder "Tier 2/3 thêm ở Task N" là return tạm có chủ đích, được thay ở task sau (TDD). ✔

**Type consistency:** `ProgramCandidate(program_id, canonical_name, score)`, `resolve_majors(text, *, ...)`, `ProgramCatalogRepository.vector_search_programs/upsert_program/get_program_content_hashes`, `build_major_catalog(*, source_programs, repository, embedder, enrich)`, `CatalogBuildReport(total, embedded, reused)`, `_embed_input(canonical_name, aliases_text)` dùng nhất quán giữa các task & test. ✔

**Rủi ro:** Test phụ thuộc DB được `_db_or_skip`/skip an toàn; test resolver/build dùng fakes nên chạy không cần DB/mạng. Thay đổi hành vi extraction (Task 8) kèm cập nhật test bị ảnh hưởng.
