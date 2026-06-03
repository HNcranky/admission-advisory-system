# Plan 03: Integration Test Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `tests/integration/` suite that exercises the full ingestion pipeline against the Docker Postgres DB and verifies canonical-record writes. Tests must auto-skip when the DB is unreachable so CI and DB-less development workflows keep working.

**Architecture:** Register a custom pytest marker `integration` via a top-level `pyproject.toml`. Provide two session/function-scoped fixtures in `tests/integration/conftest.py`:
- `db_available` — attempts a 2-second psycopg2 connection; calls `pytest.skip(...)` with a clear remediation message if it fails. Cached per session.
- `clean_db` — depends on `db_available`; truncates the canonical-records table before each test using it.

Two integration tests cover the spec's E2E acceptance criteria: (a) end-to-end pipeline run for `vnu_uet` writes 20 rows, (b) the per-source unique constraint is present (regression guard for Plan 02).

**Tech Stack:** pytest, psycopg2, the in-repo `IngestionPipeline` and `save_canonical_records` helpers.

**Prerequisites:** Plan 01 and Plan 02 complete (DB container healthy; `python -m db.setup_db` idempotent).

**Pre-flight:** Before starting this plan, ensure the DB has the schema applied. If you reset the volume since Plan 02:

```powershell
docker compose up -d --wait db
python -m db.setup_db
```

Several tasks below depend on the `canonical_admission_records` table existing. If a step errors with `relation "canonical_admission_records" does not exist`, return to this pre-flight.

---

### Task 1: Create `pyproject.toml` with the `integration` marker

Pytest emits a `PytestUnknownMarkWarning` (or fails under `--strict-markers`) for un-registered markers. Register `integration` once at the project root.

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Confirm no existing `pyproject.toml` / `pytest.ini` / `setup.cfg`**

Run: `ls D:/Work/advisory-agent/pyproject.toml D:/Work/advisory-agent/pytest.ini D:/Work/advisory-agent/setup.cfg 2>$null`

Expected: empty output (no such files yet). If any one exists, ADD the marker to that file instead of creating `pyproject.toml`.

- [ ] **Step 2: Write the minimal config file**

Create `pyproject.toml` at repo root with exactly:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests that require a live Postgres database",
]
```

No `[project]` table, no build system — pytest only needs the `ini_options` table. Keeping the file minimal avoids accidentally turning the repo into a packaged library.

- [ ] **Step 3: Verify pytest sees the marker**

Run: `python -m pytest --markers | findstr integration`

Expected: prints `@pytest.mark.integration: tests that require a live Postgres database`.

- [ ] **Step 4: Confirm the rest of the test suite still collects cleanly**

Run: `python -m pytest --collect-only --ignore=tests/services/test_reasoning_inference_service.py -q 2>&1 | Select-Object -Last 5`

Expected: ends with `N tests collected` (N matches the count from before this plan). No warnings about unknown markers.

> `--ignore=tests/services/test_reasoning_inference_service.py` works around a pre-existing import error (`reason_candidates_with_gateway` symbol missing) that lives on `main` and is unrelated to this work. Remove the `--ignore` once that test is fixed in a separate change.

---

### Task 2: Create the `tests/integration/` package skeleton

**Files:**
- Create: `tests/integration/__init__.py`

- [ ] **Step 1: Create the empty package marker**

Create `tests/integration/__init__.py` with no content (zero bytes is fine; the file's existence is what matters for pytest's collection).

- [ ] **Step 2: Verify the new folder is discovered by pytest**

Run: `python -m pytest tests/integration/ --collect-only`

Expected: prints `no tests ran in N s` or `collected 0 items` — directory exists but is empty. No errors.

---

### Task 3: Write the `db_available` skip-fixture (TDD)

This is the first piece of real behavior. Write the test first.

**Files:**
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_conftest_fixtures.py`

- [ ] **Step 1: Write the failing test for the skip behavior**

Create `tests/integration/test_conftest_fixtures.py` with:

```python
import pytest

pytestmark = pytest.mark.integration


def test_db_available_fixture_lets_tests_run_when_db_is_reachable(db_available):
    """Sanity check: when DB is up, the fixture yields without skipping."""
    # If we got here, db_available did not call pytest.skip().
    assert True
```

- [ ] **Step 2: Run the test to confirm it FAILS for the right reason**

Run: `python -m pytest tests/integration/test_conftest_fixtures.py -v`

Expected: `ERRORS` section with `fixture 'db_available' not found`. (Not a skip, not a pass — a collection error.)

- [ ] **Step 3: Implement the fixture**

Create `tests/integration/conftest.py` with:

```python
"""Fixtures for integration tests that need a live Postgres DB.

The DB is expected to be running in Docker (`docker compose up -d db`) with
the schema applied (`python -m db.setup_db`). Tests using `db_available`
auto-skip with a clear remediation message if the DB is unreachable so the
suite stays green for DB-less development and CI.
"""

import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG


_REMEDIATION = (
    "Postgres not reachable at "
    f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}. "
    "Run `docker compose up -d db && python -m db.setup_db` first."
)


@pytest.fixture(scope="session")
def db_available():
    """Skip the test session unless Postgres is reachable.

    Scoped to the session so we pay the connection cost at most once per run.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=2)
    except psycopg2.OperationalError:
        pytest.skip(_REMEDIATION)
    else:
        conn.close()
```

- [ ] **Step 4: Run the test — expect PASS when DB is up**

Run: `python -m pytest tests/integration/test_conftest_fixtures.py -v`

Expected: 1 passed.

- [ ] **Step 5: Verify the skip path by killing the DB**

Run:

```powershell
docker compose stop db
python -m pytest tests/integration/test_conftest_fixtures.py -v
docker compose start db
```

Expected from the middle command: 1 skipped with the message `Postgres not reachable at localhost:5432/admission. Run \`docker compose up -d db && python -m db.setup_db\` first.`

Wait ~5 seconds after `docker compose start db` so the healthcheck recovers before the next task.

---

### Task 4: Write the `clean_db` truncate-fixture (TDD)

Add a function-scoped fixture that wipes `canonical_admission_records` between tests so each test starts clean. Keep `source_registry` seed data intact.

**Files:**
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/test_conftest_fixtures.py`

- [ ] **Step 1: Append the failing test**

Append to `tests/integration/test_conftest_fixtures.py`:

```python
def test_clean_db_truncates_canonical_records(clean_db):
    """After clean_db runs, canonical_admission_records is empty."""
    import psycopg2
    from ingestion.config.settings import DB_CONFIG

    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM canonical_admission_records")
        count = cur.fetchone()[0]
    conn.close()

    assert count == 0
```

- [ ] **Step 2: Run to see the fixture missing**

Run: `python -m pytest tests/integration/test_conftest_fixtures.py::test_clean_db_truncates_canonical_records -v`

Expected: `fixture 'clean_db' not found` error.

- [ ] **Step 3: Implement `clean_db` in conftest**

Append to `tests/integration/conftest.py`:

```python
@pytest.fixture
def clean_db(db_available):
    """Truncate canonical_admission_records before each test.

    `source_registry` is intentionally NOT truncated — it is seed data that
    the pipeline assumes is already present.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE canonical_admission_records "
                "RESTART IDENTITY CASCADE"
            )
        conn.commit()
    finally:
        conn.close()
    yield
```

- [ ] **Step 4: Run both fixture tests — both PASS**

Run: `python -m pytest tests/integration/test_conftest_fixtures.py -v`

Expected: 2 passed.

- [ ] **Step 5: Stress test — insert a row, then re-run the truncate test**

Run:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "INSERT INTO canonical_admission_records (school_id, school_name_canonical, admission_year, program_id, admission_method, source_url) VALUES ('test', 'Test School', 2026, 'test_prog', 'test_method', 'http://example.com');"
python -m pytest tests/integration/test_conftest_fixtures.py::test_clean_db_truncates_canonical_records -v
```

Expected: 1 passed. The fixture wiped the test row before the assertion ran.

---

### Task 5: Write the pipeline E2E smoke test

This is the headline acceptance test from the spec: run the full `vnu_uet` pipeline, write to DB, query back, count rows.

**Files:**
- Create: `tests/integration/test_db_writer_e2e.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_db_writer_e2e.py` with:

```python
"""E2E smoke tests: pipeline → save_canonical_records → DB query."""

import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.storage.db_writer import save_canonical_records

pytestmark = pytest.mark.integration


def _count_vnu_uet_rows():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM canonical_admission_records "
                "WHERE school_id = %s AND admission_year = %s",
                ("vnu_uet", 2026),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_vnu_uet_pipeline_persists_twenty_canonical_records(clean_db):
    records = IngestionPipeline().run_for_school("vnu_uet")
    assert len(records) == 20, (
        f"Pipeline produced {len(records)} records, expected 20 (PDF source "
        "only after dự bị fix). If the upstream PDF changed, update this "
        "assertion."
    )

    saved = save_canonical_records(records)
    assert saved == 20

    assert _count_vnu_uet_rows() == 20
```

- [ ] **Step 2: Run the new test — expect PASS**

Run: `python -m pytest tests/integration/test_db_writer_e2e.py::test_vnu_uet_pipeline_persists_twenty_canonical_records -v`

Expected: 1 passed. The test:
1. Runs the pipeline (network fetch of the UET article + PDF; can take 5–15 seconds).
2. Asserts 20 normalized records (PDF only after dự bị filter).
3. Upserts to DB.
4. Re-queries; expects exactly 20 rows for `school_id='vnu_uet'`.

If the test fails with `count == 0` after `saved == 20`: the `save_canonical_records` call swallowed an exception. Inspect logs.

If the test fails with `len(records) != 20`: either the upstream PDF changed or the parser regressed. Investigate before adjusting the expected count.

- [ ] **Step 3: Confirm idempotency — run the test a second time**

Run the same command again.

Expected: still 1 passed. The `clean_db` fixture truncates between runs, and `save_canonical_records` uses `ON CONFLICT DO UPDATE`, so re-runs produce identical row counts.

---

### Task 6: Write the per-source uniqueness regression guard

Plan 02 patched migration 010; lock that fix in with a test.

**Files:**
- Modify: `tests/integration/test_db_writer_e2e.py`

- [ ] **Step 1: Append the failing test**

Append to `tests/integration/test_db_writer_e2e.py`:

```python
def test_canonical_records_have_per_source_unique_constraint(db_available):
    """Migration 010 must install canonical_admission_records_per_source_key.

    Without this constraint, ON CONFLICT in db_writer.py silently fails to
    upsert per-source rows.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'canonical_admission_records'::regclass
                  AND contype = 'u'
                """
            )
            names = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    assert "canonical_admission_records_per_source_key" in names, (
        "Migration 010 has not been applied or the constraint name drifted. "
        "Re-run `python -m db.setup_db`."
    )
```

- [ ] **Step 2: Run the constraint test**

Run: `python -m pytest tests/integration/test_db_writer_e2e.py::test_canonical_records_have_per_source_unique_constraint -v`

Expected: 1 passed.

If it fails: ensure Plan 02 was completed and `python -m db.setup_db` was rerun after the migration 010 patch.

---

### Task 7: Verify the full integration suite

Confirm everything written so far co-exists with the existing unit suite.

**Files:**
- No file changes.

- [ ] **Step 1: Run only the integration suite**

Run: `python -m pytest -m integration -v`

Expected: 4 passed (2 fixture sanity tests + 2 E2E tests in `test_db_writer_e2e.py`).

- [ ] **Step 2: Run only the NON-integration suite — must not require DB**

Run: `python -m pytest -m "not integration" --ignore=tests/services/test_reasoning_inference_service.py -q 2>&1 | Select-Object -Last 5`

Expected: ends with `N passed[, 2 failed]` — the two pre-existing failures (`tests/agents/test_profile_agent.py::test_profile_agent_uses_injected_gateway` and `tests/services/test_profile_inference_service.py::test_build_profile_with_gateway_falls_back_when_gateway_is_unavailable`) live on `main` and are unrelated to this work. Crucially: **no new failures and no collection errors.** The `--ignore` skips the pre-existing collection error in `test_reasoning_inference_service.py`.

- [ ] **Step 3: Verify the skip path globally**

Run:

```powershell
docker compose stop db
python -m pytest -m integration -v
docker compose start db
```

Expected from the middle command: 4 skipped (every integration test skipped via the `db_available` chain). Zero failed, zero errored.

Wait ~5 seconds for the container to become healthy again before continuing.

---

### Plan-03 acceptance gate

All of the following must be true before moving to Plan 04:

- [ ] `pyproject.toml` registers the `integration` marker; `pytest --markers` confirms it.
- [ ] `tests/integration/` contains `__init__.py`, `conftest.py`, `test_conftest_fixtures.py`, `test_db_writer_e2e.py`.
- [ ] `python -m pytest -m integration -v` passes 4 tests with DB up.
- [ ] `python -m pytest -m integration -v` skips 4 tests with DB down (no failures).
- [ ] `python -m pytest -m "not integration"` passes the pre-existing test count (no regressions).

### Commit checklist (user runs `git commit` themselves)

Suggested staging:

```bash
git add pyproject.toml tests/integration/
```

Suggested message:

```
test: add integration test suite for Postgres-backed pipeline

- pyproject.toml registers the `integration` marker.
- tests/integration/conftest.py adds db_available + clean_db fixtures
  that skip the suite when Postgres is unreachable.
- E2E smoke test: vnu_uet pipeline writes 20 canonical records.
- Regression guard: migration 010's per-source unique constraint
  is present after setup_db.
```

Do NOT run the commit; leave staging in place for user inspection.
