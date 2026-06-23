# FACTS.md — measured statistics for the thesis

Single source of truth for every number cited in `latex/Chapter/*.tex`.
Re-measure before the submission pass if the codebase changes.
All measurements taken **2026-06-19** on branch `refactor/codebase` unless noted.

## Codebase size

Command: `git ls-files '*.py' | xargs wc -l` (tracked files only)

| Metric | Value |
|---|---|
| Python LOC (total, incl. tests) | 34,413 |
| Python files (tracked) | 414 |
| `tests/` LOC | 17,569 |
| Production LOC (total − tests) | 16,844 |
| `ingestion/` LOC | 6,909 |
| `services/` LOC | 6,777 |
| `scripts/` LOC | 1,519 |
| `db/` LOC | 329 |
| `observability/` LOC | 325 |
| `agents/` LOC | 156 |
| `web/` (Python only) LOC | 155 |
| `domain/` LOC | 99 |
| root (`graph.py`, `state.py`, `main.py`) | 107 |
| Git commits on branch | 371 (as of 2026-06-19) |

`observability/` and `domain/` are top-level packages that did not exist in the
2026-06-16 measurement: `observability/` holds the Langfuse client, run-trace
helpers, and prompt service; `domain/` holds shared Pydantic models.

## Database migrations

Command: `ls db/migrations/*.sql` — **20 migrations**, `001_source_registry.sql`
… `019_knowledge_qa_cache.sql`. Numbering runs `001`–`019` but two files share the
`014_` prefix (`014_chunk_content_hash.sql`, `014_drop_discovered_resources.sql`), so
the file count (20) is one higher than the top number (019).
(OUTLINE.md / root CLAUDE.md previously said 001–013, and earlier FACTS passes said
16 then 19 — all stale; use 20 files.)

Tables: source_registry, discovered_resources (dropped by `014`), raw_documents,
extracted_facts, canonical_admission_records, advisory_runs,
chat_sessions/chat_messages/chat_advisory_runs, advisory_trace_events (`011`,
now **dormant** — see below), flow_state (`012`),
knowledge_documents/knowledge_chunks (`013`), program_catalog_embeddings (`015`),
cutoff_records (`016`), knowledge_chunk_doc_index (`017`), advisory_run_queue
(`018`), knowledge_qa_cache + knowledge_qa_cache_version (`019`).

- Migration `018` backs the **run-queue worker** (`services/chat/run_queue_worker.py`):
  advisory/hybrid runs are persisted to `chat_advisory_runs` (claimed with
  `SKIP LOCKED`) and drained by a background worker, not only the in-process
  `ThreadPoolExecutor` an earlier draft described.
- Migration `019` backs the **knowledge-QA semantic cache**
  (`services/knowledge/qa_cache.py`): answered questions are stored with their
  768-dim embedding and a dependency-version stamp; a later question whose
  embedding is within threshold reuses the cached answer unless an ingest has
  bumped the scope version.
- `advisory_trace_events` (`011`) is **dormant since 2026-06-18**: the in-app
  trace viewer was retired and no rows are written any longer (see "Observability").

## Canonical store contents (dev DB `admission`)

Command: `docker exec advisory-db psql -U postgres -d admission -c "SELECT …"`.
Re-measured **2026-06-19** with the Docker dev DB up (`advisory-db`, healthy).
(Note: `knowledge_documents` groups by column `school`, not `school_id`.)

| Table | Count |
|---|---|
| canonical_admission_records — hust | 136 |
| canonical_admission_records — vnu_uet | 20 |
| cutoff_records — hust | 699 |
| cutoff_records — vnu_uet | 16 |
| cutoff_records — **total** | 715 |
| program_catalog_embeddings | 82 |
| knowledge_documents (total) | 93 |
| — HUST | 72 |
| — MOET | 10 |
| — NEU | 5 |
| — VNU-UET | 4 |
| — unknown (school column null/blank) | 2 |
| knowledge_chunks | 692 |
| knowledge_qa_cache rows | 0 (empty until a run populates it) |
| source_registry rows | 6 |
| raw_documents / extracted_facts | 0 / 0 (working tables, cleared after promotion) |

The knowledge corpus grew sharply since 2026-06-16 (18 → 93 documents,
406 → 692 chunks): the HUST program-overview scraper plus the `by_section`
chunking strategy ingested 72 HUST documents (was 5) and additional MOET pages.

Schools registered in ingestion CLI (`python -m ingestion.main --list`): **2** —
`hust` (2 active / 4 total sources), `vnu_uet` (2 active / 2 total). NEU and MOET
data enter via the knowledge-corpus path, not the canonical ingestion registry.

## Test suite

Command: `python -m pytest --collect-only -q` → **1123 tests collected**
(2026-06-19). Test files: 194.
Isolation: `tests/conftest.py::_isolate_test_db` redirects the whole suite to
an auto-created `admission_test` database; dev data untouched.

Full-suite result, `python -m pytest -q`, ≈14 s with the Docker DB up:
**1122 passed, 1 skipped, 0 errors** (of 1123 collected).

- The 1 skip is `tests/e2e/test_real_conflict_resolution.py` — requires
  `DATABASE_URL` + a real dataset dump fixture not in the repo.
- The trace-endpoint integration error reported in the 2026-06-17 pass is **gone**:
  the endpoint and its test were removed when the trace viewer was retired
  (2026-06-18), so the suite now runs clean with no errors.

## Observability — Langfuse single sink (2026-06-17 / 2026-06-18)

The in-app per-stage trace viewer (Postgres `advisory_trace_events`, the
`GET /api/sessions/{token}/trace` endpoint, and its JS panel) was **retired** and
replaced by a single observability sink: **Langfuse** (`observability/`).

- `observability/langfuse_client.py` — lazy `get_langfuse()` singleton, returns
  `None` and no-ops when `ADVISORY_LANGFUSE_ENABLED` is false or keys are missing.
- `observability/run_trace.py` — `advisory_run_trace` / `turn_trace` root spans,
  `stage_span` per pipeline stage, `record_generation` per Gemini call (one per
  retry/fallback) carrying model, raw prompt/response, token usage
  (`InferenceResult.usage` from Gemini `usage_metadata`), latency, `attempt`,
  `used_fallback`, `failure_type`. Trace id is derived deterministically from
  `run_id`; `session_id = session_token`.
- `services/tracing/agent_tracer.py` (`traced`) now opens only `stage_span`; the
  `TraceRepository` write half was removed. `extractors.py` is kept (feeds span
  input/output).
- Self-hosted Langfuse v3 runs from a separate compose stack
  (`langfuse-web`/`langfuse-worker` + its own Postgres/ClickHouse/Redis/MinIO);
  the app stack (`advisory-db`) is unchanged. Every helper degrades silently.

## Agentization — declarative LangGraph orchestration (2026-06-18)

The conversation turn and the knowledge-QA flow were turned into LangGraph graphs
(no LLM tool-calling autonomy added; the deterministic stages stay deterministic).

- `services/chat/turn_graph.py` — `build_turn_graph`: guards (reset, rejection,
  continue, correction) + `intent_router` router node + conditional routing to
  handler nodes (advisory enqueue, knowledge_qa subgraph, hybrid, conversational,
  clarification, out-of-scope). Wired into `ConversationService.handle_user_message`
  (`conversation_service.py:143` `self._turn_graph.invoke(state)`).
- `services/knowledge/qa_graph.py` — `build_kqa_graph`: reusable subgraph
  embed → retrieve_school → augment_national → gate(min_score) → generate, hidden
  behind `KnowledgeQAService.answer()` (signature unchanged). Used by the inline
  turn path, the fan-out, and the hybrid path.
- `services/chat/hybrid_graph.py` — hybrid orchestration graph
  (advisory ∥ knowledge → synthesis).
- The advisory pipeline `graph.py` (profile → retrieve → conflict → reason →
  policy → explain) is unchanged; the turn-graph only enqueues advisory runs.

## Prompt management — Langfuse PromptService pilot (2026-06-18, partial)

`observability/prompts.py` (`get_prompt_service`) fetches/compiles system prompts
from Langfuse with a local fallback (disabled by default). **Pilot scope = 3
agents** that resolve their system prompt through the service:
`services/chat/intent_router.py`, `services/chat/synthesis_agent.py`,
`services/knowledge/qa_service.py`. The inference gateway forwards an optional
prompt handle to `record_generation` so a generation links back to its prompt
version. This is a pilot, not a system-wide rollout → future-work in §6.2.

## Edge-case compliance (evaluation of 2026-06-06, branch feat/edge-case-complete)

Against the 25 cases in `docs/edge-case.md`:
**17 pass / 4 partial / 4 fail** (baseline 2026-06-04: 8 / 3 / 14).

- Pass (17): EC-01, 03, 04, 05, 06, 09, 10, 12, 13, 14, 15, 16, 17, 18, 21, 22, 24.
- Partial (4): EC-02 (no e2e re-ask test), EC-19 (tuition raw JSONB only, no
  tuition_fit in reasoning), EC-23 (no per-program band-shift causality),
  EC-25 (data_uncertain_fields covers quota only).
- Fail (4): EC-07 (no `__remove__` op for majors), EC-08 (location_preference
  flat string, unused in retrieval), EC-11 (no unresolved_major_mentions),
  EC-20 (tuition_budget flat string, no soft preference).
- Single remaining root cause: flat profile model for location/tuition +
  reasoning ignores both fields → future-work cluster "structured preferences"
  (EC-07/08/11/19/20/25), cited in §6.2.

## Subsystem evaluation framework (2026-06-23)

Evaluation is split by subsystem (no single whole-system metric). Harnesses live
under `eval/`; deterministic ones (reliability, conflict) run in the test suite
under `tests/eval/`. Reports are written to `docs/superpowers/evals/`.

### Axis 1 — Knowledge QA quality (MEASURED, `eval/knowledge_qa/`)
Golden set: **32 human-verified cases** (26 answerable + 6 abstain),
`eval/knowledge_qa/golden_set.json`. Generation-only over frozen
production-equivalent retrieval; judge = `gemini-2.5-flash` (LLM-as-judge).
Numbers for the production model `gemini-2.5-flash`
(report `docs/superpowers/evals/2026-06-10-knowledge-qa-flash-vs-flash-lite.md`):

| Metric | Value |
|---|---|
| Faithfulness (grounded, no hallucination) | 0.958 |
| Answer correctness | 0.769 |
| Citation F1 | 0.656 |
| Abstention accuracy (declines when unsupported) | 0.938 |

Metric definitions: faithfulness/correctness from the judge; citation F1 from
exact chunk-text match of cited vs expected source ids (`grader.py`); abstention
accuracy = fraction of cases where answered-vs-abstained matches the label.

**Production model update (2026-06-23):** runtime moved off `gemini-2.5-flash`/
`-flash-lite` (20 requests/day cap) to **`gemini-3.1-flash-lite`** (≈500 req/day) for
both tiers in `factory.py` via `.env` (`ADVISORY_MODEL_LITE`/`ADVISORY_MODEL_STRONG`).
Same harness, judge = `gemini-3.1-flash-lite`, candidate max_tokens 2048 (report
`docs/superpowers/evals/2026-06-23-knowledge-qa-gemini3-tier.md`):

| Metric | `gemini-3.1-flash-lite` |
|---|---|
| Faithfulness | 1.000 |
| Answer correctness | 0.769 |
| Citation F1 | 0.646 |
| Abstention accuracy | 0.938 |

On par with `gemini-2.5-flash`, far above old `-flash-lite` (correctness 0.615).
CAVEAT (state in thesis): this run self-judged (judge = candidate model) with a larger
token budget than the 2.5-flash baseline above → a validation of adequacy, not a strictly
controlled delta. `gemini-3.5-flash` was NOT adopted: it returns empty (`has_data=False`)
through the json+`thinking_budget=0` path and runs 20–90 s/call (vs ~1.5 s for
3.1-flash-lite) — unusable for interactive advisory as wired.

### Axis 2 — Retrieval quality (MEASURED 2026-06-23, `eval/retrieval/`)
Labelled set: 48 questions from `eval/knowledge_qa/qna_corpus_eval.json`; **45 scored**
(3 skipped: gold doc was a local file from another machine, absent post-reingest).
Gold is matched at **document granularity (source URL)**, NOT chunk id — re-ingest
reassigns chunk ids so the corpus's `source_chunk_id` no longer identifies the same
text (verified: id 410 now holds an unrelated chunk). Recall@k = top-k chunks include
one from the gold source document. Production retrieval path, read-only.
Report `docs/superpowers/evals/retrieval-recall.md`:

| Metric | Value |
|---|---|
| Recall@1 | 0.711 |
| Recall@3 | 0.756 |
| Recall@5 | 0.778 |
| Recall@10 | 0.778 |
| MRR | 0.739 |

### Axis 3 — Runtime latency (MEASURED 2026-06-23, `eval/latency/`)
Wall-clock per `KnowledgeQAService.answer` (embed→retrieve→generate), production
model `gemini-3.1-flash-lite`. Report `docs/superpowers/evals/latency-knowledge-qa.md`.
**6-question sample, paced** (`EVAL_LATENCY_N=6 EVAL_CALL_DELAY_SECONDS=10`) — bigger
unpaced runs trip the free-tier embedding/generation RPM (key-pool cooldown), so the
sample is small; figures are order-of-magnitude, environment-specific.

| Stage | p50 (ms) | p95 (ms) |
|---|---|---|
| End-to-end answer | 1785 | 1866 |
| Generation only | 1268 | 1395 |

Sub-2 s end-to-end; retrieval adds ~0.5 s over the bare model call.

### Axis 4 — Reliability under failure (MEASURED, `eval/reliability/`)
Synthetic failure injection against the real `LLMGateway.run` (provider mocked,
no network). 5 scenarios across 3 families. Report
`docs/superpowers/evals/reliability-gateway.md`; covered by `tests/eval/reliability/`.

| Family | Scenarios | Recovered |
|---|---|---|
| Fallback recovery (hard API failure: timeout / 5xx) | 2 | 2 (100%) |
| Structured-output recovery (malformed JSON: retry + fallback) | 2 | 2 (100%) |
| Graceful-degradation contract (no fallback → surfaces InferenceError) | 1 | 1 (100%) |
| **All** | **5** | **5 (100%)** |

### Axis 5 — Conflict detection/resolution (MEASURED, synthetic, `eval/conflict/`)
Controlled contradictions injected into the deterministic conflict service (no
LLM, no DB). 5 injected conflicts + 3 agreeing controls. Report
`docs/superpowers/evals/conflict-synthetic.md`; covered by `tests/eval/conflict/`.

| Metric | Value |
|---|---|
| Detection recall (injected conflicts found) | 5/5 = 100% |
| False positives (agreeing sources wrongly flagged) | 0/3 = 0% |

Resolution behaviour (key result): decisive cases resolve by trust_level /
corroboration; an equal-trust tie and a **decision-changing** cutoff (values
straddle the applicant's score) are left **unresolved** and surfaced, never
silently picked. This is the designed conflict policy, demonstrated end to end.

### Axis 6 — Advisory recommendation validity (MEASURED 2026-06-23, `eval/advisory/`)
**12 synthetic student profiles** (`eval/advisory/profiles.json`) seeded into the
advisory pipeline (needs `cutoff_records` populated — `python -m ingestion.ingest_cutoffs
--seed`, 28 rows). Report `docs/superpowers/evals/advisory-eligibility.md`. 108
recommendations total:

| Metric | Value |
|---|---|
| Constraint satisfaction (recommended major requested) | 108/108 = 100% |
| Eligibility consistency (no uncautioned below-cutoff pick) | 108/108 = 100% |
| Coverage (per-profile match/no-match correct) | 11/12 = 92% |

The one coverage miss = `edge-unmatched-major` (asks for medicine, not offered by the
configured schools): pipeline returned 2 adjacent-program recs instead of declining.
Complements the edge-case matrix below (behavioural advisory evidence).

### Axis 7 — Semantic cache (NOT MEASURED — honest limitation)
`knowledge_qa_cache` is empty in dev and disabled by default; no hit-rate / cost /
latency-reduction figure can be reported. Stated as a limitation and future work
(§6.2): an instrumented soak with replayed queries would produce hit-rate and
token-saving numbers. Do NOT cite an invented cache hit-rate.

## Contribution commits (verified `git log`)

- `c2ef582` — feat: implement deterministic keyword fallback for intent classification (§5.2)
- `b41dd9f` — feat: implement degenerate OCR detection and retry mechanism to handle repetition loops (§5.3)
- `95814a1` — transparent no-match explanation (EC-24) — referenced by edge-case matrix
- `d65f270` — feat(chunker): add by_section strategy with program-section headers (knowledge corpus growth)
- `0323299` — feat(knowledge-qa): wire semantic cache into answer() (§5 semantic cache)
- `c44e8b3` — feat(prompts): fetch/compile prompt and expose linkable handle (§6.2 prompt pilot)

## Environment / library versions (`requirements.txt`, `python --version`)

| Tool | Version |
|---|---|
| Python | 3.12.0 |
| langgraph | 1.1.10 |
| langchain | 1.2.17 |
| langfuse | >=3,<4 |
| google-genai | 1.75.0 |
| pydantic | 2.13.4 |
| psycopg2-binary | 2.9.12 |
| fastapi | 0.136.1 |
| uvicorn | 0.46.0 |
| jinja2 | 3.1.6 |
| httpx | 0.28.1 |
| pytest | 9.0.3 |
| requests | 2.33.1 |
| beautifulsoup4 | 4.14.3 |
| pdfminer.six | 20251230 |
| pdfplumber | 0.11.9 |
| pymupdf | 1.27.2.3 |
| thefuzz | 0.22.1 |
| tenacity | 9.1.4 |
| Postgres image | pgvector/pgvector:pg16 |

## Advisory pipeline shape (from `graph.py`, `agents/`)

6 pipeline stages: profile → retrieve → conflict → reason → policy → explain.
6 graph-node modules in `agents/`: profile, retrieval, conflict, reasoning,
policy, explanation. Shared domain models live in `domain/models.py`.
`services/` packages: chat, conflict, cutoff, inference, knowledge, profile,
tracing. Top-level `observability/` holds the Langfuse client, run-trace helpers,
and prompt service.
</content>
</invoke>
