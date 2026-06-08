-- Điểm chuẩn lịch sử per-source (Giai đoạn 2 — EC-14/15/16/18).
-- admission_method lưu MÃ canonical ('thpt_score'...), KHÁC convention
-- display-name của canonical_admission_records. Unique key per-source
-- mirror migration 010 để hai nguồn cùng tồn tại thành hai row (EC-16).
CREATE TABLE IF NOT EXISTS cutoff_records (
    id                     SERIAL PRIMARY KEY,
    school_id              TEXT NOT NULL,
    program_id             TEXT,
    program_name_canonical TEXT,
    program_name_raw       TEXT,
    cutoff_year            INTEGER NOT NULL,
    admission_method       TEXT NOT NULL,
    score_scale            NUMERIC,
    cutoff_score           NUMERIC NOT NULL,
    subject_combinations   JSONB,
    note                   TEXT,
    source_url             TEXT NOT NULL,
    source_trust_level     INTEGER,
    confidence_score       REAL,
    ingested_at            TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (school_id, cutoff_year, program_id, admission_method, source_url)
);

CREATE INDEX IF NOT EXISTS idx_cutoff_school_program
    ON cutoff_records (school_id, program_id, admission_method);

CREATE INDEX IF NOT EXISTS idx_cutoff_school_year
    ON cutoff_records (school_id, cutoff_year);
