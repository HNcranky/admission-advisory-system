-- Trigram fuzzy matching on the program label so retrieval can resolve the
-- program named in a question (word_similarity) and scalar-filter by it.
-- Structure-independent: works regardless of how a page was chunked.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_program_trgm
    ON knowledge_chunks USING gin (program gin_trgm_ops);
