-- 014_drop_discovered_resources.sql
-- discovered_resources never wired to any read/write path (audit §1). Drop it.
DROP TABLE IF EXISTS discovered_resources CASCADE;
