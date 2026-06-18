CREATE TABLE IF NOT EXISTS knowledge_qa_cache (
    id           BIGSERIAL PRIMARY KEY,
    school       TEXT NOT NULL,
    topic        TEXT NOT NULL,
    question     TEXT NOT NULL,
    embedding    vector(768) NOT NULL,
    answer_json  JSONB NOT NULL,         -- {answer, citations, confidence}
    confidence   REAL NOT NULL,
    dep_versions JSONB NOT NULL,         -- {scope_key: version_at_write}
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qa_cache_scope
    ON knowledge_qa_cache (school, topic);
CREATE INDEX IF NOT EXISTS idx_qa_cache_embedding
    ON knowledge_qa_cache USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_qa_cache_expires
    ON knowledge_qa_cache (expires_at);

CREATE TABLE IF NOT EXISTS knowledge_qa_cache_version (
    scope_key TEXT PRIMARY KEY,
    version   BIGINT NOT NULL DEFAULT 1,
    bumped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
