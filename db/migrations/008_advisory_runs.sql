
CREATE TABLE IF NOT EXISTS advisory_runs (
    id SERIAL PRIMARY KEY,
    user_query TEXT NOT NULL,
    admission_year INTEGER,
    profile_json JSONB NOT NULL,
    retrieval_json JSONB NOT NULL,
    reasoning_json JSONB NOT NULL,
    policy_json JSONB NOT NULL,
    final_answer TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_advisory_runs_created_at
ON advisory_runs (created_at DESC);
