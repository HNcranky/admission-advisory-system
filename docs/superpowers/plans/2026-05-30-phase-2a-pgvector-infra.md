# Phase 2A — pgvector Infrastructure Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project's Postgres able to store/search embeddings and pin the embedding model/dimension as config, so later plans can create the corpus schema and repository.

**Architecture:** Swap the dev database image from `postgres:16-alpine` to `pgvector/pgvector:pg16` (drop-in, same data volume) so the `vector` extension is installable. Add two embedding constants to the existing settings module — these are the single source of truth for the model name and vector dimension used by the Phase 2 migration and the Phase 3 embedder.

**Tech Stack:** Docker Compose, PostgreSQL 16 + pgvector, Python (`ingestion/config/settings.py`), pytest.

**Plan order:** This is plan **2A** — it has no prerequisites and must be done **before 2B (migration)** and **2C (repository)**.

---

### Task 1: Embedding configuration constants

**Files:**
- Modify: `ingestion/config/settings.py` (append after the existing `GEMINI_OCR_MODEL` block, around line 54)
- Test: `tests/ingestion/test_embedding_settings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_embedding_settings.py`:

```python
from ingestion.config import settings


def test_embedding_dim_is_768():
    assert settings.EMBEDDING_DIM == 768


def test_embedding_model_defaults_to_gemini_embedding_001():
    assert settings.GEMINI_EMBEDDING_MODEL == "gemini-embedding-001"


def test_embedding_model_is_env_overridable(monkeypatch):
    # Reload the module under a patched env var to prove the override path works.
    import importlib

    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")
    reloaded = importlib.reload(settings)
    try:
        assert reloaded.GEMINI_EMBEDDING_MODEL == "text-embedding-004"
    finally:
        monkeypatch.delenv("GEMINI_EMBEDDING_MODEL", raising=False)
        importlib.reload(settings)  # restore defaults for other tests
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ingestion/test_embedding_settings.py -v`
Expected: FAIL with `AttributeError: module 'ingestion.config.settings' has no attribute 'EMBEDDING_DIM'`.

- [ ] **Step 3: Add the constants**

In `ingestion/config/settings.py`, immediately after the `GEMINI_OCR_MODEL = os.getenv(... "gemini-2.5-flash-lite" ...)` block, add:

```python
# --- Embeddings (knowledge corpus / RAG) ---------------------------------
# gemini-embedding-001 with Matryoshka truncation to 768 dims. Changing
# EMBEDDING_DIM later requires re-embedding the whole corpus because the
# knowledge_chunks.embedding column type is fixed to vector(EMBEDDING_DIM).
GEMINI_EMBEDDING_MODEL = os.getenv(
    "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", 768))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ingestion/test_embedding_settings.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/config/settings.py tests/ingestion/test_embedding_settings.py
git commit -m "$(cat <<'EOF'
feat(config): add embedding model + dimension constants for corpus

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Switch the dev database image to pgvector

**Files:**
- Modify: `docker-compose.yml` (the `db.image` line)

- [ ] **Step 1: Change the image**

In `docker-compose.yml`, change:

```yaml
  db:
    image: postgres:16-alpine
```

to:

```yaml
  db:
    image: pgvector/pgvector:pg16
```

Leave everything else (container name, env, ports, volume `advisory_pgdata`, healthcheck) unchanged — the data volume is preserved across the image swap.

- [ ] **Step 2: Recreate the container on the new image**

Run:

```bash
docker compose up -d db
```

Expected: the `advisory-db` container is recreated and reaches a healthy state (the existing `pg_isready` healthcheck passes). Existing data in `advisory_pgdata` is retained.

- [ ] **Step 3: Verify the vector extension is installable**

Run:

```bash
docker compose exec db psql -U postgres -d admission -c "CREATE EXTENSION IF NOT EXISTS vector;" -c "\dx vector"
```

Expected: output lists the `vector` extension (name + version), confirming the image ships pgvector. (Plan 2B's migration also runs this `CREATE EXTENSION`; running it here just proves the image is correct.)

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "$(cat <<'EOF'
chore(db): switch dev Postgres image to pgvector/pgvector:pg16

Drop-in replacement for postgres:16-alpine; same advisory_pgdata volume.
Required so the knowledge corpus can use the pgvector extension.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

- **Spec coverage:** Covers the Ops Changes in spec §5 (image swap, embedding config constants). The `pgvector` *pip* dependency from the spec is intentionally **omitted** — the repository (Plan 2C) formats vectors as `'[...]'` strings cast with `%s::vector` and never calls `register_vector`, so the package is unused (YAGNI). `db/setup_db.py` verify-list change lives in Plan 2B with the migration it validates.
- **Placeholders:** none — all code and commands are concrete.
- **Type consistency:** `EMBEDDING_DIM` (768) and `GEMINI_EMBEDDING_MODEL` ("gemini-embedding-001") are the names Plan 2B's migration comment and Plan 2C/Phase 3 reference.
