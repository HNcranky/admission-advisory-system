
CREATE TABLE IF NOT EXISTS discovered_resources (
    id              SERIAL PRIMARY KEY,
    url             TEXT UNIQUE NOT NULL,
    source_id       TEXT REFERENCES source_registry(source_id),
    discovered_at   TIMESTAMPTZ DEFAULT NOW(),
    predicted_type  TEXT,
    priority_score  REAL DEFAULT 0.5,
    status          TEXT DEFAULT 'new',
    content_hash    TEXT,
    last_checked_at TIMESTAMPTZ,
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_discovered_status ON discovered_resources(status);
CREATE INDEX IF NOT EXISTS idx_discovered_source ON discovered_resources(source_id);
