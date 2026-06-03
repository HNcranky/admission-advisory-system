CREATE TABLE IF NOT EXISTS advisory_trace_events (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES chat_advisory_runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    output_json JSONB,
    error_text TEXT,
    UNIQUE (run_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_trace_events_run
    ON advisory_trace_events (run_id, sequence);
