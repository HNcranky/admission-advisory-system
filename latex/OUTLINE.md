# Thesis Outline — content ↔ codebase map

Status legend: `[ ]` not started · `[~]` drafted · `[x]` final.
Every claim/number below marked (verify) must be re-measured before writing.

## Front matter
- [ ] Acknowledgments — 100-150 words.
- [ ] Abstract — 200-350 words; problem → approach → solution → contributions.

## Chapter 1 — Introduction (3-6 pages)
- [ ] 1.1 Motivation: Vietnamese admission landscape: per-school admission
      pages, proposal PDFs, ministry (MOET) documents; data is fragmented,
      frequently revised, and sources contradict each other. No solution here.
- [ ] 1.2 Objectives and scope: survey existing channels (school websites,
      hotline counseling, generic chatbots); limitations: stale data, no
      conflict awareness, no personalization. Objectives: end-to-end system =
      ingestion of official sources + canonical conflict-aware store +
      LLM-agent advisory chat. Scope: configured schools (see
      `ingestion/config/`), Vietnamese-language user dialogue.
- [ ] 1.3 Tentative solution: LangGraph advisory pipeline + RAG over pgvector +
      resilient Gemini gateway; contributions preview (→ Chapter 5).
- [ ] 1.4 Thesis organization: prose description of Chapters 2-6.

## Chapter 2 — Requirement survey and analysis (9-11 pages)
Sources: `docs/happy-path.md`, `docs/edge-case.md`,
`docs/admission-advisory-conversational-architecture.md`.
- [~] 2.1 Status survey: existing advisory products; comparison table.
- [~] 2.2.1 General use case diagram: actors = student (anonymous chat),
      operator (ingestion CLI, debug/trace panel).
- [~] 2.2.2 Detailed use case diagrams: advisory conversation; knowledge Q&A;
      data ingestion.
- [~] 2.2.3 Business process: profile collection → retrieval → conflict
      check → reasoning → policy → explanation (mirrors `graph.py`).
- [~] 2.3 Functional description: 4-7 key use cases with flows and pre/post
      conditions (advisory consultation, free-form Q&A, profile update,
      school data refresh).
- [~] 2.4 Non-functional: LLM-outage graceful degradation, data freshness,
      anonymous sessions, latency, test isolation.

## Chapter 3 — Theoretical background and technologies (≤ 10 pages)
Rule: each technology must map to a Chapter 2 requirement + name alternatives.
- [~] 3.1 LLMs: Gemini family (cite), prompting, structured output.
- [~] 3.2 RAG + vector search: embeddings, pgvector (cite); alternative:
      dedicated vector DBs; why Postgres-integrated.
- [~] 3.3 Agentic pipelines: LangGraph (cite) state graphs; alternative:
      plain function-calling loop; why a fixed graph (determinism,
      traceability).
- [~] 3.4 Document processing: PDF parsing, OCR for scanned proposals,
      degenerate-OCR detection rationale.
- [~] 3.5 Web stack: FastAPI (cite), Jinja2, background ThreadPoolExecutor.

## Chapter 4 — Design, implementation, and evaluation
- [~] 4.1.1 Architecture selection: layered service-oriented monolith.
- [~] 4.1.2 Overall design: package diagram from real packages: `web/`,
      `services/{chat,inference,knowledge,conflict,tracing}`, `agents/`,
      `ingestion/`, `db/`.
- [~] 4.1.3 Detailed package design: advisory graph
      (`graph.py`, `state.py::AgentState`, `agents/*`); inference gateway
      (`services/inference/gateway.py`, `registry.py`,
      `providers/gemini_provider.py`); ingestion
      (`ingestion/pipeline/ingestion_pipeline.py`, fetchers/parsers/
      extractors/normalization, `storage/db_writer.py`).
- [~] 4.2.1 UI design: chat UI, debug/trace panel (`services/tracing/`).
- [~] 4.2.2 Layer design: sequence diagrams for advisory run dispatch
      (`services/chat/` background executor) and knowledge Q&A
      (`services/knowledge/qa_service.py`).
- [~] 4.2.3 Database design: E-R of canonical store; migrations
      `db/migrations/001-016`; pgvector tables; repository pattern with
      injectable `connection_factory` + `_cursor` context manager.
- [~] 4.3.1 Libraries/tools table: versions from `requirements.txt` /
      `pyproject.toml` (verify).
- [~] 4.3.2 Achievement: LOC, package/test counts, ingested schools
      HUST/NEU/UET + MOET documents — all measured values in `latex/FACTS.md`
      (2026-06-08: hust 136 programs, cutoffs 715 total, catalog 81,
      knowledge docs 18 / chunks 406, 28,055 Python LOC, 856 tests).
- [~] 4.3.3 Screenshots of main flows.
- [~] 4.4 Testing: pytest suite on isolated `admission_test` DB
      (`tests/conftest.py::_isolate_test_db`); edge-case compliance matrix
      result 17/25 passing (verify against `docs/edge-case.md` run).
- [~] 4.5 Deployment: Docker Compose (pgvector/pgvector:pg16), uvicorn.

## Chapter 5 — Solution and contribution (≥ 5 pages)
Each: problem → solution → results. Cross-referenced from Chapters 2/4.
- [ ] 5.1 Conflict-aware data consolidation: contradictory quota/cutoff data
      across sources; `services/conflict/` detection + LLM tiebreaker;
      conflict surfacing in advisory answers.
- [ ] 5.2 Resilient LLM inference gateway: API failures vs STRUCTURE_FAILURE,
      retry/fallback in `services/inference/gateway.py`, deterministic keyword
      fallback for intent classification (commit c2ef582).
- [ ] 5.3 End-to-end heterogeneous ingestion: per-school configs, OCR with
      degenerate-output detection and retry (commit b41dd9f), normalization
      into the canonical store.

## Chapter 6 — Conclusion and future work
- [ ] 6.1 Conclusion: achieved vs not; comparison with existing products.
- [ ] 6.2 Future work: structured preferences (remaining edge cases
      EC-07/08/11/19/20/25), location/budget-aware retrieval and reasoning,
      more schools, production hardening.

## Appendix A — Use case descriptions
- [ ] Full specifications overflowing from §2.3.

## Reference collection backlog
- Academic: RAG (Lewis et al. 2020), LLM agents survey, conflict resolution /
  data-fusion literature — find and add to `reference.bib`.
- Official: LangGraph, pgvector, FastAPI, Gemini (already seeded).
