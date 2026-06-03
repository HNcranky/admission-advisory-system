
CREATE TABLE IF NOT EXISTS source_registry (
    source_id           TEXT PRIMARY KEY,
    school_id           TEXT NOT NULL,
    school_name         TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    root_url            TEXT NOT NULL,
    trust_level         INTEGER DEFAULT 3 CHECK (trust_level BETWEEN 1 AND 5),
    priority            INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    fetch_strategy      TEXT DEFAULT 'http',
    parser_profile      TEXT DEFAULT 'default',
    update_frequency_hint TEXT DEFAULT 'weekly',
    is_official         BOOLEAN DEFAULT TRUE,
    active              BOOLEAN DEFAULT TRUE,
    last_fetched_at     TIMESTAMPTZ,
    metadata            JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_school_id ON source_registry(school_id);
CREATE INDEX IF NOT EXISTS idx_source_active ON source_registry(active);
