-- Knowledge corpus: unstructured documents + embedded chunks for RAG.
-- Separate from raw_documents (admission fetch pipeline) on purpose.
-- embedding is vector(768) — must match ingestion.config.settings.EMBEDDING_DIM.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id              SERIAL PRIMARY KEY,
    school          TEXT NOT NULL,
    document_type   TEXT NOT NULL,          -- tuition_page | curriculum_pdf | faq | handbook | scholarship_policy
    source_url      TEXT NOT NULL UNIQUE,   -- UNIQUE → re-fetch upserts, no duplicates
    content_hash    TEXT,
    raw_text        TEXT,
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id                    SERIAL PRIMARY KEY,
    knowledge_document_id INTEGER REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    school                TEXT NOT NULL,
    program               TEXT,
    year                  INTEGER,
    document_type         TEXT,
    topic                 TEXT,             -- tuition | curriculum | scholarship | dormitory | career | ...
    chunk_text            TEXT NOT NULL,
    embedding             vector(768),      -- nullable: allows chunk-then-embed / re-embed
    source_url            TEXT,
    span_start            INTEGER,
    span_end              INTEGER,
    ingested_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_url, span_start, span_end)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_school_topic
    ON knowledge_chunks (school, topic);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
