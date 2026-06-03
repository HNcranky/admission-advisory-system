CREATE TABLE IF NOT EXISTS chat_sessions (
    id SERIAL PRIMARY KEY,
    session_token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'collecting_profile',
    profile_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    latest_run_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chat',
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_advisory_runs (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    profile_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB,
    final_answer TEXT,
    error_text TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at
ON chat_sessions (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
ON chat_messages (session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_chat_advisory_runs_session_id
ON chat_advisory_runs (session_id, created_at DESC);