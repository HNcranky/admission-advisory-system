# Knowledge QA Semantic Cache — Design

**Date:** 2026-06-18
**Status:** Approved (design)
**Scope:** Knowledge QA generation path only (v1)

## Problem

Every Knowledge QA turn pays a Gemini generation call (`knowledge_qa_agent`,
`gemini-2.5-flash`) plus an embedding + pgvector retrieval. On Gemini's free tier
(20 requests/day/project/model) this is the binding constraint, not latency.
Students ask the **same common questions** ("học phí UET?", "điểm chuẩn ngành
CNTT?") in many phrasings, across sessions and across users — every repeat spends
a request that produced an (almost) identical answer last time.

A naive answer cache has a correctness trap, explicitly raised during design:

> Earlier, the corpus had too few docs → a question got a bad answer. After docs
> are added, the same question should get the better answer — but a naive cache
> keeps returning the old bad one.

The design must (a) avoid caching the thin-docs bad answer in the first place, and
(b) invalidate cached answers when the corpus behind them changes — **including
when new docs are *added*** (not just edited).

## Goals

- Cut Gemini generation calls for repeated / paraphrased knowledge questions.
- Never return a stale answer after the relevant corpus scope changes.
- Never cache a low-confidence ("thin docs") answer.
- Degrade gracefully: any cache fault falls through to normal generation.

## Non-goals (YAGNI)

- No caching of intent routing, profile extraction, or followup reasoning.
- No cross-school / no-topic query caching (the fanout always supplies a concrete
  `(school, topic)`; direct `school=None` calls bypass the cache).
- No Redis / external store — Postgres is the shared store across the 40 web
  threads + background executors.
- No provider-side (Gemini `CachedContent`) prompt caching — system prompts here
  are far below Gemini's ~1k-token minimum cacheable prefix, so they would never
  produce a cache; left to Gemini's automatic implicit caching at zero cost.

## Match strategy

**Semantic** (embedding similarity), as chosen in design:

```
embed(question)  -- reuses fanout's query_vector when present; else embed_query()
candidate = SELECT ... WHERE school=? AND topic=?
            ORDER BY embedding <=> :q LIMIT 1
HIT  if (1 - cosine_distance) >= KNOWLEDGE_QA_CACHE_THRESHOLD (0.95)
     AND all dep_versions == current
MISS otherwise -> normal flow, then maybe store
```

The query embedding is needed for retrieval anyway, so the lookup adds no extra
embedding call on the fanout path (and exact-text repeats already hit the
embedder's in-process LRU, `embedder.py:18`).

## Invalidation strategy

**Per-scope version stamping**, as chosen in design. Each cache row records the
versions of every corpus scope its answer depends on; ingestion bumps a scope's
version when it writes chunks into that scope; a read recomputes those versions
and treats any mismatch as a miss (lazy — no eager delete).

### Scope dependency set

The codebase treats `topic IS NULL` chunks as wildcards — locally-ingested
official PDFs are multi-topic and stay candidates for **every** topic filter
(`repository.py:174-177`). National-scope chunks (`NATIONAL_SCHOOL`) are merged
into every school-scoped answer (`qa_service.py:115-130`). So a cached answer for
a concrete `(school=S, topic=T)` depends on **four** scopes:

| scope_key            | covers                                        |
|----------------------|-----------------------------------------------|
| `s:{S}\|t:{T}`        | S's own chunks for topic T                     |
| `s:{S}\|t:*`          | S's NULL-topic (wildcard) docs, e.g. local PDFs|
| `s:national\|t:{T}`   | national regulations for topic T               |
| `s:national\|t:*`     | national NULL-topic (wildcard) docs            |

### Ingest bump rule

Each ingested document bumps exactly one scope_key, derived from the
`(school, topic)` it is written with in `pipeline._chunk_embed_upsert`:

| Doc written              | bump scope_key       |
|--------------------------|----------------------|
| school=S, topic=T        | `s:S\|t:T`            |
| school=S, topic=NULL     | `s:S\|t:*`            |
| school=national, topic=T | `s:national\|t:T`     |
| school=national, topic=NULL | `s:national\|t:*`  |

Adding a **new** doc bumps its scope, so a previously-cached answer for that scope
goes stale even though it never cited the new doc — this is the "additions" case
that source-provenance (`used_source_ids`) alone would miss.

`NATIONAL_SCHOOL` is the constant from `services/knowledge/scope.py`; any non-
national school value maps to the `s:{S}|...` form.

## Quality gate (kills the thin-docs bad answer)

A cache write happens **only if**:

```
result.has_data AND result.confidence >= KNOWLEDGE_QA_MIN_SCORE  (0.5)
```

`has_data=False` (no grounded answer, `qa_service.py:147-156`) and low retrieval
confidence both signal "thin docs" — exactly the bad answer the user described.
Skipping the write means that when better docs arrive later, no cache entry
exists, so a fresh generation runs and the improved answer is produced. Combined
with version invalidation, the stale-answer problem is closed from both ends.

## Components

### Migration — `db/migrations/019_knowledge_qa_cache.sql`

```sql
CREATE TABLE IF NOT EXISTS knowledge_qa_cache (
    id           BIGSERIAL PRIMARY KEY,
    school       TEXT NOT NULL,
    topic        TEXT NOT NULL,
    question     TEXT NOT NULL,
    embedding    vector(768) NOT NULL,
    answer_json  JSONB NOT NULL,         -- {answer, citations, confidence}
    confidence   REAL NOT NULL,
    dep_versions JSONB NOT NULL,         -- {scope_key: version_at_write}
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qa_cache_scope
    ON knowledge_qa_cache (school, topic);
CREATE INDEX IF NOT EXISTS idx_qa_cache_embedding
    ON knowledge_qa_cache USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_qa_cache_expires
    ON knowledge_qa_cache (expires_at);

CREATE TABLE IF NOT EXISTS knowledge_qa_cache_version (
    scope_key TEXT PRIMARY KEY,
    version   BIGINT NOT NULL DEFAULT 1,
    bumped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`vector(768)` matches `EMBEDDING_DIM` and the existing `knowledge_chunks` /
`program_catalog_embeddings` tables. Migration is idempotent (`IF NOT EXISTS`),
matching the `001–018` convention.

### `services/knowledge/qa_cache.py` — `QACacheRepository`

Follows `KnowledgeChunkRepository`: injectable `connection_factory`
(default `get_knowledge_db_connection`), all DB access via `services.db.cursor`,
vectors via `services.db.vector_literal`.

- `scope_keys(school, topic) -> list[str]` — the 4 dependency keys (pure helper).
- `current_versions(scope_keys) -> dict[str,int]` — fetch versions; missing key = 0.
- `lookup(embedding, school, topic, threshold) -> CachedAnswer | None` — nearest
  by cosine within scope and `expires_at > NOW()`; returns it only if
  `cosine >= threshold` **and** stored `dep_versions == current_versions`.
- `store(school, topic, question, embedding, result, dep_versions, ttl_days)`.
- `bump_version(scope_key)` — `INSERT ... ON CONFLICT (scope_key) DO UPDATE SET
  version = version + 1, bumped_at = NOW()`.

### `KnowledgeQAService.answer()` wiring (`qa_service.py:56`)

```
if cache disabled OR school is None OR topic is None:
    return graph path (unchanged)

embedding = query_vector or self.embed_query(retrieval_query or question)
try:
    hit = cache.lookup(embedding, school, topic, threshold)
    if hit: return hit.to_result(from_cache=True)
except Exception: logger.warning(...)        # fall through, never break QA

result = graph.invoke(..., query_vector=embedding)   # reuse embedding, no re-embed
try:
    if result.has_data and result.confidence >= min_score:
        cache.store(school, topic, question, embedding, result,
                    cache.current_versions(cache.scope_keys(school, topic)),
                    ttl_days)
except Exception: logger.warning(...)
return result
```

Passing `query_vector=embedding` into the graph preserves the existing
embed-once-reuse behaviour (the graph's embed node already honours a supplied
vector). `KnowledgeQAResult` gains an optional `from_cache: bool = False` field
for observability and test assertions.

### Ingest hook (`ingestion/knowledge/pipeline.py`)

After a successful `mark_ingested` in `run_for_source`, `run_for_local_file`, and
`run_for_url`, call `QACacheRepository().bump_version(scope_key)` where
`scope_key` is derived from the doc's `(school, topic)` per the bump rule above
(local/url paths write `topic=None` → `s:{school}|t:*`). Wrapped so a cache-bump
failure logs a warning and never fails ingestion.

### Settings (`ingestion/config/settings.py`)

- `KNOWLEDGE_QA_CACHE_ENABLED: bool = True`
- `KNOWLEDGE_QA_CACHE_THRESHOLD: float = 0.95`
- `KNOWLEDGE_QA_CACHE_TTL_DAYS: int = 30`

## Data flow

```
                 ┌─────────── answer(question, school, topic, query_vector) ───────────┐
                 │ concrete (school, topic)?  no → graph path (today), no cache          │
                 │ yes:                                                                  │
   embed ───────▶│ embedding = query_vector or embed_query(...)                          │
                 │ cache.lookup ── HIT (cosine≥0.95 & versions current) ──▶ return ◀─────┤
                 │            └── MISS ─▶ graph.invoke(query_vector=embedding)            │
                 │ quality gate (has_data & confidence≥0.5) ─▶ cache.store(dep_versions)  │
                 └───────────────────────────────────────────────────────────────────────┘

ingest doc(school, topic) ─▶ mark_ingested ─▶ cache.bump_version(scope_key)
```

## Error handling

- Cache read/write/bump failures are caught, `logger.warning`-ed, and the system
  proceeds as if the cache were absent (CLAUDE.md degrade-gracefully rule).
- Generation itself is unchanged and keeps its existing degrade-to-no-data path.

## Testing

**Unit** (fake `QACacheRepository` / in-memory):
- hit returns cached answer with `from_cache=True`, no gateway call;
- below-threshold candidate → miss → gateway called;
- quality gate: `has_data=False` and `confidence<0.5` are not stored;
- stale: a bumped dep version makes a previously-stored row a miss;
- `school is None` or `topic is None` → cache bypassed entirely.

**Integration** (`admission_test` DB, migration 019 applied):
- store → lookup hit round-trip via real pgvector;
- `bump_version` for a scope makes the matching cached row stale;
- adding a doc to a scope (ingest path) invalidates that scope's cached answers.

Run unit/integration per CLAUDE.md (`pytest -q`; integration needs Docker DB).

## Open risks / tuning

- **Threshold 0.95** is a starting point; log near-miss cosines to retune. The
  synonym map in `intent_router` shows real conflation risk (tuition vs
  scholarship) — too-loose threshold could cross-match.
- **TTL 30d** is a backstop only; correctness rests on the version logic.
- Topic-level granularity adds the 4-scope dependency set; if it proves to be
  over-engineered in practice it can be collapsed to school-level versioning
  without a schema change (fewer scope_keys, same tables).
```
