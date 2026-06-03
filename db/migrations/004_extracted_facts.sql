
CREATE TABLE IF NOT EXISTS extracted_facts (
    id                          SERIAL PRIMARY KEY,
    raw_document_id             INTEGER REFERENCES raw_documents(id),
    school_name                 TEXT,
    admission_year              INTEGER,
    program_name                TEXT,
    program_code                TEXT,
    admission_method_raw        TEXT,
    subject_combinations_raw    JSONB,
    quota_raw                   TEXT,
    deadline_raw                TEXT,
    additional_conditions_raw   TEXT,
    tuition_raw                 TEXT,
    confidence_score            REAL,
    extraction_method           TEXT,
    extracted_at                TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_facts_school ON extracted_facts(school_name);
CREATE INDEX IF NOT EXISTS idx_facts_year ON extracted_facts(admission_year);
