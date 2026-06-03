
CREATE INDEX IF NOT EXISTS idx_canonical_school_year
ON canonical_admission_records (school_id, admission_year);

CREATE INDEX IF NOT EXISTS idx_canonical_program_year
ON canonical_admission_records (program_id, admission_year);

CREATE INDEX IF NOT EXISTS idx_canonical_method_year
ON canonical_admission_records (admission_method, admission_year);

CREATE INDEX IF NOT EXISTS idx_canonical_subject_combinations_gin
ON canonical_admission_records
USING GIN (subject_combinations);
