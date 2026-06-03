
CREATE TABLE IF NOT EXISTS canonical_admission_records (
    id                      SERIAL PRIMARY KEY,
    extracted_fact_id        INTEGER REFERENCES extracted_facts(id),
    school_id               TEXT NOT NULL,
    school_name_canonical   TEXT NOT NULL,
    admission_year          INTEGER NOT NULL,
    program_id              TEXT,
    program_name_canonical  TEXT,
    program_name_raw        TEXT,
    admission_method        TEXT,
    admission_method_raw    TEXT,
    subject_combinations    JSONB,
    quota                   JSONB,
    deadline                JSONB,
    metadata                JSONB,
    tuition                 JSONB,
    source_url              TEXT,
    source_trust_level      INTEGER,
    confidence_score        REAL,
    normalized_at           TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(school_id, admission_year, program_id, admission_method)
);

CREATE INDEX IF NOT EXISTS idx_canonical_school ON canonical_admission_records(school_id);
CREATE INDEX IF NOT EXISTS idx_canonical_year ON canonical_admission_records(admission_year);
CREATE INDEX IF NOT EXISTS idx_canonical_program ON canonical_admission_records(program_id);
