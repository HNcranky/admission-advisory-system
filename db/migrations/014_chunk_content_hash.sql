-- Add content_hash to knowledge_chunks for cross-document embedding reuse.
-- SHA-256 of chunk_text (see services/knowledge/repository.py::chunk_content_hash).
-- Indexed so re-ingestion can reuse an existing embedding for identical chunk
-- text regardless of which document it first appeared in.
ALTER TABLE knowledge_chunks
    ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_content_hash
    ON knowledge_chunks (content_hash);
