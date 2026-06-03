-- Drop the old uniqueness constraint that overwrote second-source rows.
-- The constraint was created by UNIQUE(...) inline in CREATE TABLE
-- (db/migrations/005_canonical_programs.sql), so Postgres assigned an
-- auto-generated name. We look it up by columns instead of hardcoding the
-- name, since the auto-generated name can be truncated past 63 chars.
DO $$
DECLARE
    old_constraint_name TEXT;
BEGIN
    SELECT conname INTO old_constraint_name
    FROM pg_constraint
    WHERE conrelid = 'canonical_admission_records'::regclass
      AND contype = 'u'
      AND array_length(conkey, 1) = 4
      AND (
          SELECT array_agg(attname::text ORDER BY attname)
          FROM pg_attribute
          WHERE attrelid = 'canonical_admission_records'::regclass
            AND attnum = ANY(conkey)
      ) = ARRAY['admission_method','admission_year','program_id','school_id'];

    IF old_constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE canonical_admission_records DROP CONSTRAINT %I',
            old_constraint_name
        );
    END IF;
END$$;

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
