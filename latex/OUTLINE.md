# Thesis Outline — content ↔ codebase map

Status legend: `[ ]` not started · `[~]` drafted · `[x]` final.
Every claim/number below marked (verify) must be re-measured before writing.

## Front matter
- [~] Acknowledgments — 100-150 words.
- [~] Abstract — 200-350 words; problem → approach → solution → contributions.

## Chapter 1 — Introduction (3-6 pages)
- [~] 1.1 Motivation: Vietnamese admission landscape: per-school admission
      pages, proposal PDFs, ministry (MOET) documents; data is fragmented,
      frequently revised, and sources contradict each other. No solution here.
- [~] 1.2 Objectives and scope: survey existing channels (school websites,
      hotline counseling, generic chatbots); limitations: stale data, no
      conflict awareness, no personalization. Objectives: end-to-end system =
      ingestion of official sources + canonical conflict-aware store +
      LLM-agent advisory chat. Scope: configured schools (see
      `ingestion/config/`), Vietnamese-language user dialogue.
- [~] 1.3 Tentative solution: LangGraph advisory pipeline + RAG over pgvector +
      resilient Gemini gateway; contributions preview (→ Chapter 5).
- [~] 1.4 Thesis organization: prose description of Chapters 2-6.

## Chapter 2 — Requirement survey and analysis (9-11 pages)
Sources: `docs/happy-path.md`, `docs/edge-case.md`,
`docs/admission-advisory-conversational-architecture.md`.
- [~] 2.1 Status survey: existing advisory products; comparison table.
- [~] 2.2.1 General use case diagram: actors = student (anonymous chat),
      operator (ingestion CLI, observability via Langfuse — in-app trace panel
      retired 2026-06-18).
- [~] 2.2.2 Detailed use case diagrams: advisory conversation; knowledge Q&A;
      data ingestion.
- [~] 2.2.3 Business process: profile collection → retrieval → conflict
      check → reasoning → policy → explanation (mirrors `graph.py`).
- [x] 2.2.4 Solution architecture overview: system-flow diagram
      (`Figure/src/system_architecture.puml` → `system_architecture.png`) —
      offline ingestion → shared pgvector store → message → intent router →
      advisory / knowledge-RAG (cosine over pgvector+HNSW) / hybrid → answer.
      Shows design, answer generation, and similarity measurement in one figure.
- [~] 2.3 Functional description: 4-7 key use cases with flows and pre/post
      conditions (advisory consultation, free-form Q&A, profile update,
      school data refresh).
- [~] 2.4 Non-functional: LLM-outage graceful degradation, data freshness,
      anonymous sessions, latency, test isolation.

## Chapter 3 — Theoretical background and technologies (8–10 pages)
Rule: each technology must map to a Chapter 2 requirement + name alternatives.
Condensed 2026-06-22 to a decision-driven form (need → alternatives → choice),
~40% shorter than the earlier draft; all citations/labels preserved.
- [~] 3.1 LLMs: Gemini family (cite), prompting, structured output.
- [~] 3.2 RAG + vector search: embeddings, pgvector (cite); alternative:
      dedicated vector DBs; why Postgres-integrated.
- [~] 3.3 Agentic pipelines: LangGraph (cite) state graphs; alternative:
      plain function-calling loop; why a fixed graph (determinism,
      traceability).
- [~] 3.4 Document processing + OCR model choice: PDF parsing; OCR framed as a
      model-selection decision among multimodal LLMs (Table: gemini-2.5-flash-lite
      chosen vs gemini-2.5-flash / GPT-4o-class / Claude-class, qualitative cost
      tiers + single-gateway reuse). Degenerate-OCR mechanics deferred to §5.3.
- [~] 3.5 Web stack: FastAPI (cite), Jinja2, durable run queue + background worker.
- [~] 3.6 Observability and answer caching: LLM observability (Langfuse, cite) as
      span-tree tracing (OpenTelemetry convention, cite); alternative: bespoke
      in-app trace panel (rejected). Semantic answer cache (GPTCache, cite);
      alternative: exact-match cache / no cache.

## Chapter 4 — Design, implementation, and evaluation
- [~] 4.1.1 Architecture selection: layered service-oriented monolith.
- [~] 4.1.2 Overall design: package diagram from real packages: `web/`,
      `services/{chat,inference,knowledge,conflict,cutoff,profile,tracing}`,
      `agents/`, `ingestion/`, `db/`, `observability/`, `domain/`.
- [~] 4.1.3 Detailed package design: advisory graph
      (`graph.py`, `state.py::AgentState`, `agents/*`); inference gateway
      (`services/inference/gateway.py`, `registry.py`,
      `providers/gemini_provider.py`); ingestion
      (`ingestion/pipeline/ingestion_pipeline.py`, fetchers/parsers/
      extractors/normalization, `storage/db_writer.py`).
- [~] 4.2.1 UI design: two-pane chat UI (profile + conversation); the right-hand
      trace panel was retired (observability moved to Langfuse). NOTE: committed
      `screenshot_chat_landing.png` is stale (old 3-pane) — author must recapture.
- [~] 4.2.2 Layer design: sequence diagrams for advisory run dispatch
      (`services/chat/` background executor) and knowledge Q&A
      (`services/knowledge/qa_service.py`).
- [~] 4.2.3 Database design: E-R of canonical store; migrations
      `db/migrations/001-019` (20 files, two share `014`); pgvector tables incl.
      `knowledge_qa_cache` (019); `advisory_trace_events` (011) dormant;
      repository pattern with injectable `connection_factory` + `_cursor`.
- [~] 4.3.1 Libraries/tools table: versions from `requirements.txt` /
      `pyproject.toml` (verify).
- [x] 4.3.x Data preparation (NEW, before Achievement): crawled-source inventory
      table (6 sources from `initial_sources.json`, 4 active + 2 inactive
      aggregator cutoffs; 8 MOET seed PDFs from `national_sources.json`);
      fetch→route→parse→extract→normalize prose; dictionaries (programs.json 25
      shared + hust/neu/uet/vnu_uet/ftu, subjects 35, methods, combo rules);
      canonical_admission_records / cutoff_records field list. Counts from FACTS.md.
- [~] 4.3.2 Achievement: LOC, package/test counts, ingested schools
      HUST/NEU/UET + MOET documents — all measured values in `latex/FACTS.md`
      (2026-06-19: hust 136 programs, cutoffs 715 total, catalog 82,
      knowledge docs 93 / chunks 692, 34,413 Python LOC, 1,123 tests collected
      / 1,122 passing).
- [~] 4.3.3 Screenshots of main flows.
- [~] 4.4 Evaluation (restructured 2026-06-23, subsystem axes per reviewer):
      4.4.1 functional correctness (pytest 1123 on isolated `admission_test` DB,
      `tests/conftest.py::_isolate_test_db`); 4.4.2 knowledge-QA quality
      (32-case golden set, LLM-judge: faithfulness 0.958 / correctness 0.769 /
      citation F1 0.656 / abstention 0.938, `eval/knowledge_qa/`); 4.4.3 retrieval
      Recall@k+MRR (48-q labelled set, `eval/retrieval/`, NUMBERS PENDING run);
      4.4.4 runtime latency p50/p95 (`eval/latency/`, PENDING run); 4.4.5
      reliability recovery 5/5=100% (`eval/reliability/`, in suite); 4.4.6 synthetic
      conflict detection 5/5 + 0 FP (`eval/conflict/`, in suite); 4.4.7 advisory
      eligibility/constraint/coverage (12 synthetic profiles, `eval/advisory/`,
      PENDING run) + edge-case matrix 17/25; 4.4.8 limitations (cache unmeasured,
      no human rubric). All numbers + run commands in `latex/FACTS.md`
      "Subsystem evaluation framework".
- [~] 4.5 Deployment: Docker Compose (pgvector/pgvector:pg16), uvicorn.

## Chapter 5 — Solution and contribution (≥ 5 pages)
Each: problem → solution → results. Cross-referenced from Chapters 2/4.
Reordered 2026-06-23 (reviewer): conflict-aware demoted to last (5.6) so the
chapter leads with the five engineering outcomes; prose shortened, simpler
wording, em-dashes → hyphens. Section labels renumbered positionally and all
external `\ref{section:5.x}` in Ch3/Ch4/Ch6 remapped to match.
Opens with a consolidated "Problems addressed" table (problem → why it matters →
solving section) before the per-problem sections (added 2026-06-22).
- [~] 5.1 Resilient LLM inference gateway: API failures vs STRUCTURE_FAILURE,
      retry/fallback in `services/inference/gateway.py`, deterministic keyword
      fallback for intent classification (commit c2ef582).
- [~] 5.2 End-to-end heterogeneous ingestion: per-school configs, OCR with
      degenerate-output detection and retry (commit b41dd9f), normalization
      into the canonical store.
- [~] 5.3 Unified observability: single Langfuse sink (`observability/`),
      root span per run + stage spans + per-call generations with token usage;
      InferenceResult.usage from Gemini usage_metadata; retired in-app panel.
- [~] 5.4 Declarative orchestration: turn-graph (`services/chat/turn_graph.py`)
      + reusable knowledge_qa subgraph (`services/knowledge/qa_graph.py`) behind
      `answer()` facade + hybrid-graph; determinism preserved, characterization tests.
- [~] 5.5 Version-gated semantic cache: `knowledge_qa_cache` (migration 019),
      embedding-similarity reuse gated on per-scope version stamp; ingest bumps
      version → invalidation; disabled by default. No measured hit-rate (cache empty in dev).
- [~] 5.6 Conflict-aware data consolidation (now last, framed as rare/high-impact
      safeguard): contradictory quota/cutoff data across sources;
      `services/conflict/` deterministic detection + resolution; conflict surfacing
      in advisory answers; synthetic eval 5/5 + 0 FP (§4.4.6).

## Chapter 6 — Conclusion and future work
- [~] 6.1 Conclusion: achieved vs not; comparison with existing products.
- [~] 6.2 Future work: structured preferences (remaining edge cases
      EC-07/08/11/19/20/25), location/budget-aware retrieval and reasoning,
      more schools, production hardening, and extending the Langfuse prompt-
      management pilot (intent_router/synthesis/knowledge_qa) system-wide with
      eval datasets + scoring.

## Appendix A — Use case descriptions
- [~] Full specifications overflowing from §2.3.

## Appendix B — Prompts (`Chapter/Appendix_B.tex`, registered in `main.tex`)
- [x] The 7 LLM system prompts reproduced verbatim (Vietnamese) in `promptstyle`
      listings: intent router, knowledge QA, hybrid synthesis, profile delta
      extractor, initial profile inference, follow-up reasoner, policy interpreter.
      Intent/knowledge/synthesis resolve via Langfuse `PromptService` (local
      fallback shown); conflict service is deterministic (no prompt). New
      `promptstyle` in `lstlisting.tex` (utf8 + literate for → × —).

## Reference collection backlog
- Academic: RAG (Lewis et al. 2020), LLM agents survey, conflict resolution /
  data-fusion literature, GPTCache (Bang 2023) — all in `reference.bib`.
- Official: LangGraph, pgvector, FastAPI, Gemini, Langfuse, OpenTelemetry (seeded).
