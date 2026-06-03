-- Catalog ngành để ánh xạ free-text -> program_id bằng semantic retrieval.
-- embedding là vector(768) — phải khớp ingestion.config.settings.EMBEDDING_DIM
-- và knowledge_chunks (migration 013).
CREATE TABLE IF NOT EXISTS program_catalog_embeddings (
    program_id      TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    aliases_text    TEXT NOT NULL DEFAULT '',
    field           TEXT,
    embed_input     TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    embedding       vector(768),
    source          TEXT NOT NULL DEFAULT 'canonical',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_embedding
    ON program_catalog_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_program_catalog_content_hash
    ON program_catalog_embeddings (content_hash);
