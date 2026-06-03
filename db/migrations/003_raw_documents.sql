
CREATE TABLE IF NOT EXISTS raw_documents (
    id              SERIAL PRIMARY KEY,
    url             TEXT NOT NULL,
    final_url       TEXT,
    source_id       TEXT REFERENCES source_registry(source_id),
    content_type    TEXT,
    http_status     INTEGER,
    content_hash    TEXT,
    raw_content     BYTEA,
    headers         JSONB,
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    document_type   TEXT,
    parsed_text     TEXT,
    parsed_structure JSONB
);

CREATE INDEX IF NOT EXISTS idx_raw_docs_source ON raw_documents(source_id);
CREATE INDEX IF NOT EXISTS idx_raw_docs_hash ON raw_documents(content_hash);
