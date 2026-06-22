-- Index cho 2 truy vấn per-document trong services/knowledge/repository.py:
--   get_embedding_map_for_document  (WHERE knowledge_document_id = %s ...)
--   delete_chunks_for_document      (DELETE ... WHERE knowledge_document_id = %s)
-- Trước đây chỉ có index theo (school, topic) và HNSW theo embedding ⇒ filter
-- theo FK này phải seq-scan. Idempotent, an toàn re-run.
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
    ON knowledge_chunks (knowledge_document_id);
