-- 018_advisory_run_queue.sql
-- Durable claim-based queue for advisory runs (audit S1).
-- Adds claim metadata columns and a partial index for efficient polling.
ALTER TABLE chat_advisory_runs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
ALTER TABLE chat_advisory_runs ADD COLUMN IF NOT EXISTS worker_id TEXT;
ALTER TABLE chat_advisory_runs ADD COLUMN IF NOT EXISTS dispatch_args_json JSONB;
CREATE INDEX IF NOT EXISTS idx_advisory_runs_queued
    ON chat_advisory_runs (created_at)
    WHERE status = 'queued';
