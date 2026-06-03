
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'canonical_admission_records'
          AND column_name = 'conditions'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'canonical_admission_records'
          AND column_name = 'metadata'
    ) THEN
        ALTER TABLE canonical_admission_records
        RENAME COLUMN conditions TO metadata;
    END IF;
END $$;
