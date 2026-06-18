# Knowledge QA Semantic Cache — Plan Set Overview

Source spec: `docs/superpowers/specs/2026-06-18-knowledge-qa-semantic-cache-design.md`

The design is split into **four** independently testable plans. Each one
produces working, committed software on its own and ends at a reviewer gate.

| # | Plan | Deliverable | Depends on |
|---|------|-------------|------------|
| 01 | `01-schema-and-version-stamping.md` | Migration `019`, 3 settings, `QACacheRepository` scope-key + version-stamp half (`scope_key_for`, `scope_keys`, `current_versions`, `bump_version`) | — |
| 02 | `02-cache-store-and-lookup.md` | `CachedAnswer`, `KnowledgeQAResult.from_cache`, repository `store` + semantic `lookup` (threshold + version gate) | 01 |
| 03 | `03-service-cache-wiring.md` | `KnowledgeQAService.answer()` cache lookup/store wiring, degrade-gracefully | 01, 02 |
| 04 | `04-ingest-invalidation-hook.md` | `bump_version` after every `mark_ingested` in the ingestion pipeline | 01 |

**Recommended execution order:** 01 → 02 → 03 → 04. Plan 04 needs only Plan 01
(`bump_version` + `scope_key_for`), so it may run any time after 01.

## Why this split

- **01** lands the schema and the version-stamping machinery (the invalidation
  backbone). Testable in isolation: bump a scope, read the version back.
- **02** completes the repository (the row read/write half). Testable in
  isolation against real pgvector: store → lookup round-trip, stale-on-bump.
- **03** is the only plan that touches the hot generation path. Isolated so a
  reviewer can scrutinise the degrade-gracefully wiring without schema noise.
- **04** is the producer side (ingestion bumps versions). Isolated because it
  touches a different subsystem (`ingestion/`) with its own test suite.

## Shared facts (verified against the codebase)

- The embedder lives at `services/inference/embedder.py` (`GeminiEmbedder`); the
  in-process LRU is module-level in that file. `EMBEDDING_DIM = 768`.
- DB access pattern: `services.db.cursor(connection_factory, commit=…)` context
  manager + `services.db.vector_literal(...)`. Knowledge repos default their
  `connection_factory` to `services.knowledge.db.get_knowledge_db_connection`.
- `NATIONAL_SCHOOL = "MOET"` (`services/knowledge/scope.py`). The spec table's
  `s:national|...` is a readable stand-in for `s:MOET|...`; both the read side
  and the ingest bump derive keys through the single helper `scope_key_for`, so
  they are guaranteed to agree.
- The KQA LangGraph `embed` node (`services/knowledge/qa_graph.py:32-39`) already
  reuses a supplied `query_vector` instead of re-embedding — passing the cache
  lookup's embedding into the graph adds **no** extra embedding call.
- Migrations are discovered by `sorted(db/migrations/*.sql)` in
  `db/setup_db.py:run_migrations`. The test DB (`admission_test`) auto-applies
  all migrations idempotently at session start via
  `tests/conftest.py::_isolate_test_db`, so a new `019_*.sql` is picked up on the
  next `pytest` run.
- The production service is built no-arg as `KnowledgeQAService()`
  (`services/chat/conversation_service.py:56`,
  `services/chat/compare_orchestrator.py:14`), so the cache must be **enabled by
  default** in the constructor. Existing unit tests construct the service with
  explicit fakes and must opt out with `cache_enabled=False` (Plan 03).
