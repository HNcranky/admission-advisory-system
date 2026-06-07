# Thesis Report Completion Plan (~50–60 pages)

> **For agentic workers:** Execute phase-by-phase. Within every phase, the
> **Review first** file list MUST be read before writing a single sentence of
> the corresponding section (rule from `latex/CLAUDE.md`: read code/docs first,
> quote real module paths in `\texttt{...}`). Every number must come from
> `latex/FACTS.md` (Phase 0) or be tagged `% TODO-VERIFY`.

**Goal:** Complete the graduation thesis in `latex/` (English, ~50–60 body
pages) documenting this repository, per `latex/OUTLINE.md`.

**Hard rules (from `latex/CLAUDE.md` + root `CLAUDE.md`):**
- Never edit `latex-template/`. Never restructure the 6-chapter skeleton.
- Factual integrity: no estimated statistics, ever.
- Never `git push`; commits without any AI attribution trailer.
- Update `latex/OUTLINE.md` status markers (`[ ]`→`[~]`→`[x]`) as sections land.

**Page budget:**

| Part | Pages |
|---|---|
| Ch1 Introduction | 4–5 |
| Ch2 Survey | 9–11 |
| Ch3 Background | 8–10 |
| Ch4 Design/Impl/Eval | 17–20 |
| Ch5 Contributions | 5–6 |
| Ch6 Conclusion | 2–3 |
| Appendix A | 2–3 |
| **Body total** | **~47–58** |

---

## Phase 0 — Fact sheet (single source of truth for every number)

**Goal:** every statistic used anywhere in the thesis is measured from the
live repo/DB and recorded in `latex/FACTS.md`; writing phases never measure
ad hoc.

**Review first:**
- `db/migrations/` — count is **16** (001–016); `latex/OUTLINE.md` and root
  `CLAUDE.md` still say 001–013 → use 16 in the thesis, fix OUTLINE.md.
- `tests/conftest.py` (`_isolate_test_db`) and `tests/` tree — suite layout.
- `ingestion/registry/` + `python -m ingestion.main` (no args) — registered schools.
- `docs/edge-case.md` — the 25 edge cases behind the 17/25 figure.
- `docs/happy-path.md` — acceptance criteria status.

**Measure (record command + output in FACTS.md):**
- LOC and file counts: `git ls-files '*.py' | xargs wc -l` (315 tracked .py files).
- Test count: `python -m pytest --collect-only -q` (Docker DB must be up).
- Canonical-store counts per school (`docker compose exec db psql -U postgres -d admission`):
  `canonical_admission_records`, `cutoff_records`, `program_catalog_embeddings`,
  `knowledge_documents`, `knowledge_chunks` (expected ballpark from memory:
  hust 136 programs / 715 cutoffs / 83 catalog — re-measure, don't trust).
- Edge-case matrix: 17/25 as of 2026-06-06 — re-confirm before §4.4.
- Contribution commits exist (verified 2026-06-08): `c2ef582` (deterministic
  keyword fallback), `b41dd9f` (degenerate OCR detection/retry).

**Output:** `latex/FACTS.md`. **Done when:** every Ch4/Ch5 number in
OUTLINE.md has a measured value or an explicit TODO-VERIFY entry. Commit.

---

## Phase 1 — Bibliography + glossary

**Goal:** `reference.bib` and `glossary.tex` are complete enough that no
writing phase stops to hunt citations or define acronyms.

**Review first:**
- `latex/reference.bib` — already seeded: `langgraph`, `pgvector`, `fastapi`, `gemini`.
- `latex/glossary.tex` — existing entries.
- `requirements.txt` — exact library names/versions to cite (langgraph 1.1.10,
  google-genai 1.75.0, pydantic 2.13.4, psycopg2-binary 2.9.12, …).

**Add (academic):** Lewis et al. 2020 (RAG, NeurIPS 33); Bleiholder & Naumann
2009 (Data Fusion, ACM Comput. Surv. 41(1)); an LLM-agents survey (e.g. Wang
et al. 2024, Front. Comput. Sci. 18); Gemini technical report
(arXiv:2312.11805). **Add (official):** PostgreSQL docs, LangChain, psycopg,
Docker — each with `urldate`.

**Glossary:** LLM, RAG, OCR, API, UI, DB, E-R, SQL, CLI, MOET, HUST, NEU,
UET (VNU-UET), JSON, REST.

**Done when:** every technology named in OUTLINE.md Ch3 has a bib key. Commit.

---

## Phase 2 — All figures (~11) rendered into `latex/Figure/`

**Goal:** every figure the chapters will `\ref` exists as PNG before prose is
written. Toolchain: PlantUML jar via local Java (`!pragma layout smetana`, no
Graphviz needed); sources in `latex/Figure/src/*.puml`.

**Review first (per diagram — draw only what the code actually does):**
- Use-case + activity diagrams: `graph.py` (node wiring), `state.py`
  (`AgentState`), `agents/*.py` (7 agents: profile, retrieval, conflict,
  reasoning, policy, explanation + models), `web/routes/chat_api.py`
  (user-facing endpoints), `services/chat/intent_router.py` (intents = detailed
  use cases), `ingestion/main.py` (operator CLI use cases).
- Package diagram: top-level layout — `web/{routes,static,templates}`,
  `services/{chat,inference,knowledge,conflict,cutoff,profile,tracing}`,
  `agents/`, `ingestion/{config,cutoff,extractors,fetchers,knowledge,models,normalization,parsers,pipeline,registry,router,storage}`, `db/`.
- Sequence diagram 1 (advisory dispatch): `services/chat/run_dispatcher.py`,
  `services/chat/advisory_runner.py`, `services/chat/hybrid_dispatcher.py`.
- Sequence diagram 2 (knowledge Q&A): `services/knowledge/qa_service.py`,
  `services/knowledge/repository.py`, `services/chat/knowledge_fanout.py`.
- E-R diagram: all 16 files in `db/migrations/` (canonical store, chat,
  advisory runs/traces, knowledge corpus, embeddings, cutoffs).

**Figures:** Ch2: general use case, 2–3 detailed use cases, advisory business
process (activity). Ch4: package diagram, LangGraph pipeline graph, 2 sequence
diagrams, E-R diagram.

**Done when:** PNGs render cleanly and match code-verified flows. Commit
(sources + PNGs).

---

## Phase 3 — Chapter 2: Survey & requirement analysis (9–11 pp)

**Goal:** `2_Survey.tex` drafted `[~]`: comparison of existing channels,
use-case model, business process, 4–7 functional specs, non-functional
requirements.

**Review first:**
- `docs/happy-path.md`, `docs/edge-case.md`,
  `docs/admission-advisory-conversational-architecture.md` — requirements ground truth.
- `services/chat/intent_router.py`, `services/chat/conversation_service.py`,
  `services/chat/profile_state_service.py`, `services/profile/slots.py` —
  what profile collection/intents actually support (pre/post conditions must
  match real behavior).
- `web/templates/chat.html`, `web/static/js/modules/trace.js`,
  `services/tracing/trace_service.py` — student UI vs operator debug panel
  (actor capabilities for §2.2.1).
- `services/chat/session_service.py` — anonymous-session requirement (§2.4).
- `services/inference/gateway.py` (degradation), `tests/conftest.py`
  (test isolation) — non-functional requirements §2.4.

**Done when:** all §2.x TODOs replaced, figures referenced, overview+summary
paragraphs in, overflow use-case specs parked for Appendix A. Commit.

---

## Phase 4 — Chapter 3: Theoretical background (8–10 pp)

**Goal:** `3_Methodology.tex` drafted; every technology maps to a Ch2
requirement and names an alternative + why this choice.

**Review first (justifications must describe the real usage):**
- §3.1 LLM/Gemini: `services/inference/gateway.py`, `registry.py`,
  `providers/gemini_provider.py`, `providers/key_pool.py`, `models.py`
  (InferenceResult, STRUCTURE_FAILURE semantics — structured-output theory).
- §3.2 RAG/pgvector: `services/knowledge/repository.py` (actual vector query),
  `services/knowledge/scope.py`, migration `013_knowledge_corpus.sql`,
  `015_program_catalog_embeddings.sql`.
- §3.3 LangGraph: `graph.py`, `state.py` (fixed graph, no tool-calling — the
  determinism/traceability argument).
- §3.4 PDF/OCR: `ingestion/extractors/`, `ingestion/knowledge/` (hybrid OCR,
  degenerate-output detection), `pdfminer/pdfplumber/pymupdf` in requirements.
- §3.5 Web stack: `web/app.py`, `services/chat/run_dispatcher.py`
  (ThreadPoolExecutor background runs).

**Done when:** each §3.x cites bib keys from Phase 1 and cross-refs Ch2
requirement labels. Commit.

---

## Phase 5 — Chapter 4: Design, implementation, evaluation (17–20 pp)

**Goal:** `4_Experiment_evaluation.tex` drafted — the heaviest chapter; all
numbers from FACTS.md, all figures from Phase 2, plus real screenshots.

**Review first:**
- §4.1 architecture/packages: `graph.py`, `state.py`, `agents/*`, full
  `services/` tree, `web/app.py`, `ingestion/pipeline/ingestion_pipeline.py`,
  `ingestion/storage/db_writer.py`.
- §4.2.1 UI: `web/templates/*.html`, `web/static/js/chat.js` + `modules/*`,
  `services/tracing/*` (trace panel data model).
- §4.2.2 layers: `services/chat/run_dispatcher.py`, `advisory_runner.py`,
  `services/knowledge/qa_service.py`, repository `_cursor` pattern in
  `services/chat/repository.py` / `services/knowledge/db.py`.
- §4.2.3 DB: all 16 migrations; describe canonical store + per-source records
  (`010_canonical_records_per_source.sql`) + pgvector tables.
- §4.3 libraries/achievement: `requirements.txt`, `latex/FACTS.md`.
- §4.4 testing: `tests/conftest.py::_isolate_test_db`, tests tree,
  `docs/edge-case.md` matrix (17/25 — re-verified in Phase 0).
- §4.5 deployment: `docker-compose.yml`, `db/setup_db.py`, `QUICKSTART.md`.

**Screenshots step:** `docker compose up -d --wait db` + `python -m uvicorn
web.app:app` → capture chat UI, an advisory recommendation with conflict note,
debug/trace panel → `latex/Figure/screenshot_*.png`.

**Done when:** all 13 §4 TODOs replaced; libraries table matches
requirements.txt exactly. Commit per section group (4.1–4.2, 4.3, 4.4–4.5).

---

## Phase 6 — Chapter 5: Solution & contribution (5–6 pp)

**Goal:** `5_Solution_contribution.tex` drafted; 3 contributions, each
problem → solution → results, cross-referencing Ch2/Ch4 (no repetition).

**Review first:**
- §5.1 conflict-aware consolidation: `services/conflict/detection.py`,
  `resolution_agent.py`, `resolution_inference_service.py`,
  `comparison_agent.py`, `evidence_agent.py`, `source_labels.py`;
  how conflicts surface in `agents/conflict_agent.py` + explanation.
- §5.2 resilient gateway: `services/inference/gateway.py` (retry/fallback,
  InferenceError vs STRUCTURE_FAILURE), `telemetry.py`, `key_pool.py`;
  `git show c2ef582` (deterministic keyword fallback in intent router).
- §5.3 heterogeneous ingestion: `ingestion/pipeline/ingestion_pipeline.py`,
  per-school `ingestion/config/`, `ingestion/normalization/`,
  `git show b41dd9f` (degenerate OCR detection/retry).

**Done when:** each contribution states a measurable result (from FACTS.md or
test results), no Ch4 prose repeated. Commit.

---

## Phase 7 — Chapter 1, Chapter 6, Abstract, Acknowledgments, Appendix A

**Goal:** the parts that summarize the body are written last, consistent with
what the body actually says.

**Review first:**
- The completed Chapters 2–5 themselves (consistency source).
- `docs/edge-case.md` — remaining EC-07/08/11/19/20/25 → §6.2 future work.
- `docs/happy-path.md` gaps (location/budget unused in retrieval/reasoning) →
  honest "achieved vs not" in §6.1.
- `ingestion/config/` + registry — scope statement in §1.2.

**Output:** `1_Introduction.tex` (prose §1.4, no bullets),
`6_Conclusion.tex`, `0_3_abstract.tex` (200–350 words, prose),
`0_2_acknowledgment.tex` (100–150 words), `Appendix_A.tex` (overflow
use-case specs from Phase 3). Commit.

---

## Phase 8 — Polish pass (whole document)

**Goal:** zero structural defects before compilation.

**Checks (all must pass):**
- Every chapter 2–6 opens with Overview, closes with Chapter summary prose.
- `\gls` on first use; figures/tables all captioned and referenced in text.
- `Select-String -Path latex\Chapter\*.tex -Pattern 'TODO-VERIFY'` → **0 hits**.
- `Select-String -Path latex\Chapter\*.tex -Pattern '% TODO'` → 0 hits.
- Every `\ref/\cite/\gls` target exists (grep per latex/CLAUDE.md).
- `latex/OUTLINE.md` statuses updated to `[x]`.

**Done when:** all greps clean. Commit.

---

## Phase 9 — Submission pass

**Goal:** final PDF compiles on Prism, body lands in 50–60 pages, cover complete.

- Ask user for cover placeholders: `<sis-email>`, `<Program>`, `<Department>`
  (`Cover.tex`/`Cover2.tex`) — blocked on user input.
- User compiles on Prism → check page count; if outside 50–60, rebalance
  Ch4 (largest lever) / Appendix A.
- Final read-through of compiled PDF (figure placement, table overflow,
  bibliography rendering).

**Done when:** compiled PDF verified, final commit.

---

**Dependency order:** 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.
Phases 0–2 are foundations; body chapters are sequential (later chapters
cross-reference earlier ones); Ch1/abstract written last by design.
