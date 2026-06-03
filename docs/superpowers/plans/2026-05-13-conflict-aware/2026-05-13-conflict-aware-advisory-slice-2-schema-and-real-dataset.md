# Slice 2 - Schema and Real Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Do not create commits for this project unless the user explicitly asks.** Use checkpoint steps instead of `git commit`.

**Goal:** Preserve multiple source rows for the same logical admission program and curate/export real conflict-bearing data for the later conflict-aware graph.

**Architecture:** Change `canonical_admission_records` uniqueness from one row per logical program-method to one row per source per logical program-method. Update the writer upsert target to include `source_url`. Then run/verify ingestion outside the default test path and export a demo-prep fixture only after SQL acceptance proves real quota divergence.

**Tech Stack:** PostgreSQL migrations, existing ingestion storage code, pytest, live Postgres for the real-data acceptance checks.

---

## File Structure

- Create: `db/migrations/010_canonical_records_per_source.sql` - per-source uniqueness migration.
- Modify: `ingestion/storage/db_writer.py` - `ON CONFLICT` target includes `source_url`.
- Create: `tests/ingestion/storage/test_db_writer_conflict_target.py` - static regression test for writer SQL target.
- Modify: `docs/ingestion/vnu-uet-preflight-findings.md` or create/update an equivalent findings doc only when real curation is run.
- Create later: `tests/e2e/fixtures/real_dataset_dump.sql` - only after acceptance queries pass against real data.

This slice should not depend on `ADVISORY_MOCK_CONFLICTS`; it is the real-data path.

---

## Task 1: Add Migration for Per-Source Rows

**Files:**
- Create: `db/migrations/010_canonical_records_per_source.sql`
- Test: `tests/ingestion/storage/test_db_writer_conflict_target.py`

- [ ] **Step 1: Inspect existing constraint names**

Run:

```powershell
rg -n "canonical_admission_records|UNIQUE|ON CONFLICT" db ingestion/storage/db_writer.py
```

Expected: find the old uniqueness definition and the writer's current `ON CONFLICT (school_id, admission_year, program_id, admission_method)` target.

- [ ] **Step 2: Write a static failing test for migration content**

Create `tests/ingestion/storage/test_db_writer_conflict_target.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_per_source_migration_exists_and_uses_source_url():
    migration = ROOT / "db" / "migrations" / "010_canonical_records_per_source.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "canonical_admission_records" in sql
    assert "source_url" in sql
    assert "school_id, admission_year, program_id, admission_method, source_url" in sql
```

- [ ] **Step 3: Run the test and verify it fails**

Run:

```powershell
pytest tests/ingestion/storage/test_db_writer_conflict_target.py -v
```

Expected: FAIL because the migration does not exist or does not contain the new key.

- [ ] **Step 4: Create the migration**

Create `db/migrations/010_canonical_records_per_source.sql`:

```sql
-- Preserve one canonical admission record per source for each logical
-- school/year/program/method tuple so conflict detection can compare sources.

ALTER TABLE canonical_admission_records
DROP CONSTRAINT IF EXISTS canonical_admission_records_school_id_admission_year_program_id_admission_method_key;

ALTER TABLE canonical_admission_records
DROP CONSTRAINT IF EXISTS canonical_admission_records_unique_program_method;

CREATE UNIQUE INDEX IF NOT EXISTS canonical_admission_records_per_source_key
ON canonical_admission_records (
    school_id,
    admission_year,
    program_id,
    admission_method,
    source_url
);
```

If the repo's previous migration used a different constraint/index name, add a matching `DROP CONSTRAINT IF EXISTS` or `DROP INDEX IF EXISTS` line after inspecting Task 1 output.

- [ ] **Step 5: Run the migration-content test**

Run:

```powershell
pytest tests/ingestion/storage/test_db_writer_conflict_target.py -v
```

Expected: PASS.

---

## Task 2: Update `save_canonical_records` Upsert Target

**Files:**
- Modify: `ingestion/storage/db_writer.py`
- Modify: `tests/ingestion/storage/test_db_writer_conflict_target.py`

- [ ] **Step 1: Add a failing static test for the writer conflict target**

Append:

```python
def test_db_writer_upserts_per_source_key():
    writer = ROOT / "ingestion" / "storage" / "db_writer.py"
    source = writer.read_text(encoding="utf-8")

    assert (
        "ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)"
        in source
    )
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
pytest tests/ingestion/storage/test_db_writer_conflict_target.py::test_db_writer_upserts_per_source_key -v
```

Expected: FAIL because the writer still uses the old conflict target.

- [ ] **Step 3: Update `ingestion/storage/db_writer.py`**

Find the SQL inside `save_canonical_records` and replace:

```sql
ON CONFLICT (school_id, admission_year, program_id, admission_method)
```

with:

```sql
ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)
```

Do not change unrelated insert columns or update assignments.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/ingestion/storage/test_db_writer_conflict_target.py -v
```

Expected: PASS.

---

## Task 3: Live DB Verification Query

**Files:**
- No mandatory code edits.

- [ ] **Step 1: Apply migrations in the project's normal way**

Use the repo's existing migration process. If there is no runner, apply the SQL file manually against the development Postgres database after confirming the DB target.

Expected: `canonical_admission_records_per_source_key` exists and includes `source_url`.

- [ ] **Step 2: Run a schema verification SQL**

Run against Postgres:

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'canonical_admission_records'
  AND indexname = 'canonical_admission_records_per_source_key';
```

Expected: one row, with `school_id, admission_year, program_id, admission_method, source_url` in `indexdef`.

---

## Task 4: Real Dataset Acceptance Query

**Files:**
- Create or update: `docs/ingestion/vnu-uet-preflight-findings.md`
- Create later: `tests/e2e/fixtures/real_dataset_dump.sql`

- [ ] **Step 1: Run ingestion for the target schools**

Run the ingestion command for VNU-UET and HUST:

```powershell
python -m ingestion.main --school vnu_uet
python -m ingestion.main --school hust
```

Expected: ingestion completes without crashing. If the command fails because a school slug is unsupported, stop and update the relevant ingestion registry/parser plan before continuing; do not bypass this step with mock data.

- [ ] **Step 2: Run Query A - source rows exist**

Run:

```sql
SELECT school_id, admission_year, COUNT(*) AS row_count
FROM canonical_admission_records
WHERE admission_year = 2026
  AND school_id IN ('vnu_uet', 'hust')
GROUP BY school_id, admission_year
ORDER BY school_id;
```

Expected: at least one row for each ingested school. Record exact counts in the findings doc.

- [ ] **Step 3: Run Query B - conflict-bearing tuples**

Run:

```sql
SELECT
    school_id,
    admission_year,
    COALESCE(program_id, program_name_canonical) AS program_key,
    COALESCE(admission_method, 'unknown_method') AS method_key,
    COUNT(*) AS source_rows,
    COUNT(DISTINCT quota::text) AS distinct_quota_values,
    ARRAY_AGG(DISTINCT source_url) AS sources,
    ARRAY_AGG(DISTINCT quota::text) AS quotas
FROM canonical_admission_records
WHERE admission_year = 2026
  AND school_id IN ('vnu_uet', 'hust')
  AND quota IS NOT NULL
GROUP BY
    school_id,
    admission_year,
    COALESCE(program_id, program_name_canonical),
    COALESCE(admission_method, 'unknown_method')
HAVING COUNT(*) >= 2
   AND COUNT(DISTINCT quota::text) >= 2
ORDER BY school_id, program_key, method_key;
```

Expected for phase acceptance: at least 3 returned rows across the corpus. If fewer than 3, do not fake rows; document the result and either re-curate sources or add another school.

- [ ] **Step 4: Spot-check one conflict**

For one returned tuple, run this self-contained query. It selects the first conflict-bearing tuple from Query B and prints its source rows:

```sql
WITH conflict_tuple AS (
    SELECT
        school_id,
        admission_year,
        COALESCE(program_id, program_name_canonical) AS program_key,
        COALESCE(admission_method, 'unknown_method') AS method_key
    FROM canonical_admission_records
    WHERE admission_year = 2026
      AND school_id IN ('vnu_uet', 'hust')
      AND quota IS NOT NULL
    GROUP BY
        school_id,
        admission_year,
        COALESCE(program_id, program_name_canonical),
        COALESCE(admission_method, 'unknown_method')
    HAVING COUNT(*) >= 2
       AND COUNT(DISTINCT quota::text) >= 2
    ORDER BY school_id, program_key, method_key
    LIMIT 1
)
SELECT
    car.school_id,
    car.admission_year,
    car.program_id,
    car.program_name_canonical,
    car.admission_method,
    car.quota,
    car.source_url,
    car.source_trust_level,
    car.confidence_score
FROM canonical_admission_records car
JOIN conflict_tuple ct
  ON ct.school_id = car.school_id
 AND ct.admission_year = car.admission_year
 AND ct.program_key = COALESCE(car.program_id, car.program_name_canonical)
 AND ct.method_key = COALESCE(car.admission_method, 'unknown_method')
ORDER BY car.source_trust_level DESC NULLS LAST, car.confidence_score DESC NULLS LAST;
```

Expected: two or more rows with like-for-like quota semantics and different numeric values. If the difference is a normalization artifact or apples-to-oranges measurement, fix parser/normalizer data before exporting.

- [ ] **Step 5: Export the real fixture only after Query B passes**

Use the project's normal dump approach. Example:

```powershell
pg_dump --data-only --inserts --table=canonical_admission_records --file=tests/e2e/fixtures/real_dataset_dump.sql "$env:DATABASE_URL"
```

Expected: `tests/e2e/fixtures/real_dataset_dump.sql` exists and contains only real ingested data needed by the later `requires_real_dataset` test. Do not include mock retrieval candidates in this file.

---

## Task 5: Slice Verification

**Files:**
- No edits unless findings are updated.

- [ ] **Step 1: Run static tests**

Run:

```powershell
pytest tests/ingestion/storage/test_db_writer_conflict_target.py -v
```

Expected: PASS.

- [ ] **Step 2: Run ingestion-related tests if present**

Run:

```powershell
pytest tests/ingestion -v
```

Expected: PASS or documented skips for tests requiring live DB/network.

- [ ] **Step 3: Check diff, do not commit**

Run:

```powershell
git diff -- db/migrations/010_canonical_records_per_source.sql ingestion/storage/db_writer.py tests/ingestion/storage/test_db_writer_conflict_target.py docs/ingestion tests/e2e/fixtures
git status --short
```

Expected: only slice-2 files are modified/created. Do not run `git commit`.
