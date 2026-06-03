-- Add flow control state column to chat_sessions.
-- Kept separate from profile_state_json: profile data vs. routing state are different concerns.
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS flow_state_json JSONB NOT NULL DEFAULT '{}';
