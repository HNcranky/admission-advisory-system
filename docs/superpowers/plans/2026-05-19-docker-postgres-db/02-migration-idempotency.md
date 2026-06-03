# Plan 02: Migration Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `python -m db.setup_db` safe to re-run any number of times against the live container; specifically, eliminate the `ADD CONSTRAINT` re-run failure in migration `010_canonical_records_per_source.sql`.

**Architecture:** Audit of `db/migrations/001..009` confirms they already use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and guarded `DO $$` blocks. Only `010_canonical_records_per_source.sql` has a bare `ALTER TABLE ... ADD CONSTRAINT` at the bottom — re-running it once the constraint exists raises `duplicate_object`. Fix by wrapping the `ADD CONSTRAINT` in the same kind of `DO $$ IF NOT EXISTS` guard used elsewhere in the codebase. Verify by running `setup_db` twice in a row against the Docker DB.

**Tech Stack:** PostgreSQL DDL, `psycopg2`, `db/setup_db.py`.

**Prerequisite:** Plan 01 complete (DB container healthy, host can connect).

---

### Task 1: Re-confirm the audit findings against the working tree

Plans get stale. Re-run the read-only audit so the patched file is unambiguous.

**Files:**
- Read-only: `db/migrations/*.sql`

- [ ] **Step 1: Grep every migration for non-idempotent DDL**

Run:

```powershell
grep -nP '^(CREATE|ALTER|DROP|RENAME)\b' D:/Work/advisory-agent/db/migrations/*.sql
```

(Use the Grep tool, not bash grep, if running through an agent.)

Expected findings:
- `001..005` use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. ✓
- `007` uses `CREATE INDEX IF NOT EXISTS`. ✓
- `008..009` use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. ✓
- `010` ends with a bare `ALTER TABLE canonical_admission_records ADD CONSTRAINT canonical_admission_records_per_source_key UNIQUE (...);` — **NOT idempotent**.

Migrations `006` and the start of `010` use `DO $$ ... IF EXISTS / IF NOT EXISTS` and are safe.

- [ ] **Step 2: Confirm the failing scenario with a clean DB**

This is the failing test for the bug. Bring up a fresh DB and apply once successfully:

```powershell
docker compose down -v
docker compose up -d --wait db
python -m db.setup_db
```

Expected: all migrations succeed, including `010_canonical_records_per_source.sql`.

- [ ] **Step 3: Run setup_db again to trigger the failure**

Run: `python -m db.setup_db`

Expected: prints `⚠️  010_canonical_records_per_source.sql error: relation "canonical_admission_records_per_source_key" already exists` (or `duplicate_object`). All other migrations succeed because they're guarded.

This is the reproduction we will fix in Task 2.

---

### Task 2: Patch migration `010` to guard the `ADD CONSTRAINT`

Wrap the `ADD CONSTRAINT` in a `DO $$ IF NOT EXISTS` block so a second apply is a no-op.

**Files:**
- Modify: `db/migrations/010_canonical_records_per_source.sql`

- [ ] **Step 1: Apply the patch**

Open `db/migrations/010_canonical_records_per_source.sql`. The bottom of the file currently is:

```sql
-- Add per-source uniqueness so two sources for the same logical program
-- coexist as two rows.
ALTER TABLE canonical_admission_records
    ADD CONSTRAINT canonical_admission_records_per_source_key
    UNIQUE (school_id, admission_year, program_id, admission_method, source_url);
```

Replace those four lines with this guarded block:

```sql
-- Add per-source uniqueness so two sources for the same logical program
-- coexist as two rows. Guarded so the migration is safe to re-apply.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'canonical_admission_records'::regclass
          AND conname = 'canonical_admission_records_per_source_key'
    ) THEN
        ALTER TABLE canonical_admission_records
            ADD CONSTRAINT canonical_admission_records_per_source_key
            UNIQUE (school_id, admission_year, program_id, admission_method, source_url);
    END IF;
END$$;
```

Leave the preceding `DO $$` block (the one that drops the old auto-named 4-column constraint) untouched — it is already idempotent.

- [ ] **Step 2: Lint the SQL syntax against the live DB**

Run:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "SET check_function_bodies = on; \i /dev/stdin" < db/migrations/010_canonical_records_per_source.sql
```

On Windows PowerShell, the `< file` redirection works for binary-safe input. If that fails on your shell, use the cross-platform variant:

```powershell
Get-Content db/migrations/010_canonical_records_per_source.sql | docker compose exec -T db psql -U postgres -d admission
```

Expected: prints `DO` then `DO` (one per `DO $$` block), no errors.

- [ ] **Step 3: Run the patched migration directly a second time**

Run the same command as Step 2 again.

Expected: still prints `DO` then `DO`, **no errors**. This is the green test for idempotency at the SQL layer.

---

### Task 3: End-to-end idempotency verification via `setup_db`

Higher-level test: prove `python -m db.setup_db` itself is now idempotent. This is what real users (and the integration tests in Plan 03) will rely on.

**Files:**
- No file changes.

- [ ] **Step 1: Reset to a clean DB**

Run:

```powershell
docker compose down -v
docker compose up -d --wait db
```

Expected: container healthy, volume `advisory_pgdata` removed and recreated.

- [ ] **Step 2: Apply migrations + seed once**

Run: `python -m db.setup_db`

Expected output (abbreviated):
```
Step 1: Creating database...
✅ Database 'admission' created
Step 2: Running migrations...
  Running 001_source_registry.sql...
  ✅ 001_source_registry.sql applied
  ... (through 010) ...
  ✅ 010_canonical_records_per_source.sql applied
Step 3: Verifying tables...
  ✅ source_registry
  ✅ discovered_resources
  ✅ raw_documents
  ✅ extracted_facts
  ✅ canonical_admission_records
  ✅ advisory_runs
  ✅ chat_sessions
  ✅ chat_messages
  ✅ chat_advisory_runs
Step 4: Seeding source registry...
🌱 Seeded 2 sources into source_registry
✅ Setup complete!
```

If any migration prints `⚠️`, stop and inspect.

- [ ] **Step 3: Apply a SECOND time — must also succeed without warnings**

Run: `python -m db.setup_db`

Expected: every migration prints `✅ ... applied`. The exact "Seeded N sources" count may stay at 2 (the writer uses `ON CONFLICT DO NOTHING`, so re-seeding does not duplicate). **No `⚠️` lines anywhere.**

If any `⚠️` appears, the migration is still not idempotent — return to Task 2.

- [ ] **Step 4: Confirm the constraint exists exactly once**

Run:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "SELECT conname FROM pg_constraint WHERE conrelid = 'canonical_admission_records'::regclass AND contype = 'u';"
```

Expected: exactly one row, `canonical_admission_records_per_source_key`. (The old auto-named 4-column constraint must have been dropped by the first `DO $$` block; the new constraint must exist exactly once.)

---

### Plan-02 acceptance gate

All of the following must be true before moving to Plan 03:

- [ ] `db/migrations/010_canonical_records_per_source.sql` ends with the guarded `DO $$ IF NOT EXISTS ... ADD CONSTRAINT` block.
- [ ] Running `python -m db.setup_db` twice in succession against a fresh DB produces zero `⚠️` warnings on the second run.
- [ ] `canonical_admission_records` has exactly one unique constraint, named `canonical_admission_records_per_source_key`, on the 5-column tuple.

### Commit checklist (user runs `git commit` themselves)

Suggested staging:

```bash
git add db/migrations/010_canonical_records_per_source.sql
```

Suggested message:

```
fix(db): make migration 010 idempotent

Wrap the ADD CONSTRAINT in a DO $$ IF NOT EXISTS guard so
`python -m db.setup_db` can be re-run safely against an
already-migrated database (required for the Docker DB workflow).
```

Do NOT run the commit; leave staging in place for user inspection.
