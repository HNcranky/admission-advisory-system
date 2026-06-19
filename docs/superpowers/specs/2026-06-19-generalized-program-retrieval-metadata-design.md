# Generalized program retrieval via metadata filtering

**Date:** 2026-06-19
**Status:** Approved design
**Area:** `ingestion/knowledge` (pipeline wiring), `services/knowledge`
(retrieval), `db/migrations`
**Supersedes the deferred part of:**
`2026-06-19-section-chunking-program-overview-design.md` ("approach B —
program metadata filtering — deferred")

## Problem

The `by_section` program-overview design works only for HUST. It is coupled to
HUST's HTML idiom in three places:

1. **Section split** needs `<h2>` → markdown `## ` (`chunker.py:16`,
   `html_parser.py:192`). NEU/UET overview pages are free prose with no `<h2>`,
   so `chunk_by_section` finds no headings.
2. **Program identity** is read from `li.breadcrumb-item.active`
   (`html_parser.py:219`) and from the seed only as a fallback — HUST-specific
   CSS.
3. The discriminating program signal lives in the **chunk text** (the
   `{program} — {section}` header) so plain cosine ranks the right program. That
   trick only holds when the page structure yields clean headers.

The deeper issue: the prior spec deliberately deferred putting program identity
in **metadata + query-time filter** (the structure-independent fix). That
deferral *is* the HUST-coupling. Retrieval today
(`services/knowledge/repository.py::vector_search`) filters `school` + `topic`
only; the `program` column is populated but never used as a filter, and there is
no query-side program resolution.

## Root cause

Program identity rides the embedding **text**, which requires page structure to
produce a clean header. The Milvus pattern is the inverse: carry identity as
**metadata** and apply a **scalar filter** alongside the vector ANN search, which
is independent of how any individual page is shaped.

## Scope decision

`topic` is already general (hardcoded per seed; we own the seeds — no change).
`school` + `topic` scalar filters already serve school-level questions (policy,
scholarship, tuition). The missing facet is **`program`**, which only matters
when a question targets one specific program. Therefore:

- Add a **soft `program` scalar filter** to retrieval (the Milvus core idea).
- Resolve the program **query-side via `pg_trgm`** against the program values
  already in the DB — no LLM program extraction, so no hallucinated filter.
- Make the program metadata **reliable at ingest** by sourcing it from the seed
  (any school), not the HUST breadcrumb.

`program` is one facet of a general metadata-filter mechanism. Other topics that
later prove to need their own facet (e.g. per-method `admission_policy`) extend
the same mechanism; not built now (YAGNI).

## Approach

### 1. Metadata: program from the seed (`ingestion/knowledge/pipeline.py`)

`run_for_source` currently (`pipeline.py:173-181`):

```python
strategy = getattr(source, "chunk_strategy", "size")
program = content_label if strategy == "by_section" else source.program
... context_label=content_label ...
```

becomes **seed-first with breadcrumb fallback**, and the chunk header uses the
chosen program:

```python
strategy = getattr(source, "chunk_strategy", "size")
program = source.program or content_label   # seed wins; breadcrumb is fallback
... context_label=program ...               # header carries the reliable program
```

- NEU/UET program-overview seeds set `program` explicitly → correct on **any**
  HTML, no `<h2>`/breadcrumb needed.
- HUST is behaviorally unchanged today (its seeds have no `program`, so it falls
  back to `content_label` = breadcrumb). Seeds may be backfilled later.
- `context_label` only affects the `by_section` header path; `size`/PDF paths
  ignore it (`chunk_text` only reads it for `by_section`), and non-program seeds
  have `program=None` → `context_label=None` → no header injected. Safe.

**Convention:** a seed's `program` value is the program's **canonical catalog
name**, so query-side resolution (§3) and the canonical store agree on the same
string.

### 2. Chunking: `by_section` stays, documented as general (`chunker.py`)

No functional change. `chunk_by_section` already degrades correctly: with no
`## ` headings it routes the body through `_label_chunks` →
`split_into_chunks`, producing multiple **size-bounded** chunks
(`CHUNK_SIZE=1800`), each prefixed with the program header. Long NEU/UET pages
(>1800 chars) therefore already chunk granularly without any heading structure.

- Only edit: clarify the docstring to state it is *structure-aware with a
  size-split fallback*, not section-only.
- NEU/UET program-overview seeds use `chunk_strategy: "by_section"` too.
- The name `by_section` is kept (renaming would churn 85 HUST seeds for no
  behavior change). Residual dilution exists only for a **short** (<1800-char)
  page that mixes sub-topics — rare; accepted and documented, mitigated at
  retrieval by §3.

### 3. Retrieval: soft `program` scalar filter (`services/knowledge/`, `db/`)

**Migration `db/migrations/020_knowledge_chunk_program_trgm.sql`** (idempotent,
follows the numbered-migration convention):

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_program_trgm
  ON knowledge_chunks USING gin (program gin_trgm_ops);
```

**`KnowledgeChunkRepository`** (`repository.py`) gains a resolver and a filter
param:

```python
def resolve_program(self, question, school=None):
    """Best program name whose text appears inside the question, or None.

    Uses word_similarity(program, question): the trigram similarity of the
    (short) program name against the best-matching window of the (long)
    question. Scoped to `school` when provided so program names don't collide
    across schools. Returns the top program only when its score clears
    KNOWLEDGE_PROGRAM_MATCH_THRESHOLD, else None.
    """
    # SELECT program, MAX(word_similarity(program, %(q)s)) AS sim
    # FROM knowledge_chunks
    # WHERE program IS NOT NULL
    #   AND (%(school)s IS NULL OR school = %(school)s)
    # GROUP BY program
    # ORDER BY sim DESC
    # LIMIT 1
    # -> return program if sim >= KNOWLEDGE_PROGRAM_MATCH_THRESHOLD else None
    #
    # The explicit Python-side threshold compare is the source of truth. Do NOT
    # gate with the `<%` operator: its index prefilter uses the session GUC
    # pg_trgm.word_similarity_threshold (default 0.6), which would override our
    # 0.3 and silently drop valid matches. The GIN trgm index still benefits
    # future `%`/LIKE use; at ~hundreds of distinct programs this scan is cheap.

def vector_search(self, embedding, school=None, topic=None,
                  program=None, limit=5):
    ...  # add: if program is not None: sql += " AND program = %s"
         # exact match is safe — the value came FROM the DB via resolve_program
```

**`KnowledgeQAService.answer`** (`qa_service.py`) resolves then filters, **soft**:

```python
program = self._chunk_repository.resolve_program(question, school)
chunks = self._chunk_repository.vector_search(
    embedding, school=school, topic=topic, program=program, limit=self._top_k
)
```

- `resolve_program` is called for **every** knowledge query (decision: always
  resolve, not gated by topic — corpus is small, one trgm query is negligible,
  and a topic gate would re-introduce coupling). Non-program questions score
  below threshold → `None` → no filter.
- No/low match → `program=None` → today's vector-only behavior. **Never zeroes
  results.**

**Settings** (`ingestion/config/settings.py`): add

```python
KNOWLEDGE_PROGRAM_MATCH_THRESHOLD = float(
    os.getenv("KNOWLEDGE_PROGRAM_MATCH_THRESHOLD", 0.3)
)
```

### 4. National (Bộ GD&ĐT) pass — unchanged

The national-scope second pass (`KNOWLEDGE_QA_NATIONAL_TOP_K`) is school-level
policy; `resolve_program` returns `None` for it → no program filter. No change.

## Components & boundaries

| Unit | Responsibility | Interface | Depends on |
|---|---|---|---|
| pipeline wiring | source program from seed; header uses it | `program = source.program or content_label` | parser, chunker |
| `chunk_by_section` | structure-aware split, size-split fallback, program header | `(text, context_label) -> [Chunk]` | `split_into_chunks` |
| `resolve_program` | question + school → canonical program or None | `(question, school?) -> str \| None` | pg_trgm, repo cursor |
| `vector_search` | vector ANN + school/topic/program scalar filters | `(embedding, school?, topic?, program?, limit)` | pgvector |
| migration 020 | pg_trgm extension + GIN trigram index on `program` | SQL | — |

## Error handling / edge cases

- **No confident program match** → `resolve_program` returns `None` → vector-only
  (current behavior). The dominant safety guarantee: generalization never makes
  retrieval *worse* than today.
- **School unknown** (`school=None`) → resolution spans all schools; risk of a
  cross-school program-name collision is accepted (rare; the `school` vector
  filter is also absent in that case anyway).
- **Wrong match above threshold** → returns *that program's* chunks; the existing
  `KNOWLEDGE_QA_MIN_SCORE` gate still rejects an irrelevant top hit, so a bad
  filter degrades to "no data" rather than a wrong answer.
- **Threshold tuning** → `KNOWLEDGE_PROGRAM_MATCH_THRESHOLD` env-tunable without
  code change; start at 0.3.
- **Short (<1800) multi-subtopic page** → may yield one diluted chunk; the
  program filter still narrows candidates to that program, so within-program
  cosine handles the sub-topic.

## Testing

- **chunker**: no-heading page > `CHUNK_SIZE` → multiple chunks, each carrying the
  program header (not one diluted chunk); short page → single chunk (documented).
- **repository**: `resolve_program` returns the top match above threshold;
  returns `None` below threshold; scoped by `school`; `vector_search` applies the
  `program` filter when set and omits it when `None`.
- **migration**: `020` is idempotent (extension + index `IF NOT EXISTS`).
- **retrieval quality**: a NEU-style no-heading page whose question names the
  program returns that program's chunks via the filter; a policy/method question
  resolves to `None` and is unaffected.

## Rollout

1. Migration 020 (pg_trgm + index); `db.setup_db` picks it up idempotently.
2. Pipeline wiring + settings + repository + qa_service.
3. Add NEU/UET program-overview seeds with explicit `program` +
   `chunk_strategy: by_section`; re-ingest.
4. Spot-check: program-named sub-topic query on a no-heading page returns the
   right program; a policy question is unchanged.

## Out of scope (YAGNI)

- Full dense+sparse BM25 fusion / reranker over chunk bodies.
- Per-chunk sub-topic classification + a `subtopic` facet.
- Per-method `admission_policy` facet.
- LLM-side program extraction in the intent router (replaced by `pg_trgm`).
- `topic` taxonomy changes (already general).
