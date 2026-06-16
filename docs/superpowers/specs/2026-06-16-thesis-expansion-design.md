# Design Spec — Thesis Expansion (Chapters 2–6 + Appendix A)

**Date:** 2026-06-16
**Author:** drafted with Claude, approved by Nguyen Viet Anh
**Scope target:** `latex/Chapter/{2_Survey,3_Methodology,4_Experiment_evaluation,5_Solution_contribution,6_Conclusion,Appendix_A}.tex`, `latex/reference.bib`, `latex/glossary.tex`, `latex/FACTS.md`
**Out of scope:** `latex/Chapter/1_Introduction.tex`, `latex/main.tex`, the preamble/template, `latex-template/`, the deferred live-run second screenshot.

---

## 1. Problem & goal

The graduation thesis (`latex/`) already has complete, codebase-accurate drafts of Chapters 1–6 and Appendix A. The drafts honor the school's style rules and the factual-integrity rule in `latex/CLAUDE.md`, but the body is short of the page requirement.

**Goal:** Expand Chapters **2, 3, 4, 5, 6** and **Appendix A** so the thesis body comfortably clears the **60-page minimum**, landing in the **65–75 page** range, while:

- adding **genuine academic citations** (web-searched and verified — never invented), and
- **growing `reference.bib`** in the existing IEEE/biblatex format.

The expansion must add **traceable depth, not filler**. The user explicitly rejected padding ("không cố gắng viết lan man để câu trang"). Every added sentence must be defensible against `latex/CLAUDE.md`'s factual-integrity rule.

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|---|---|
| D1 | Treatment of existing drafts | **Deepen in place** — keep proven structure and accurate content; do not rewrite from scratch. |
| D2 | Page target | **65–75 body pages** (comfortably clear 60; stop where content would thin out). |
| D3 | Expansion levers | **Algorithms/pseudocode** (`algorithm2e`), **code listings** (`listings`), **expanded literature review**. *Not* a broad new-evaluation pass. |
| D4 | New references | **Web-search and verify real papers**; add to `reference.bib` in IEEE format. No Wikipedia/slides/ordinary web pages (school rule). |

**Consequence of D3:** Chapter 4's *evaluation* sections (§4.4 testing, edge-case matrix) stay essentially as-is. Chapter 4 grows through *design/implementation* depth (algorithms, listings, schema narrative), not new evaluation tables. Chapters 3 and 5 are the largest beneficiaries of the algorithm/literature levers.

**No new image figures.** The author compiles externally (Prism) and PNG assets cannot be produced here. All visual expansion uses `algorithm2e` and `listings`, which are pure LaTeX and compile with no new assets. All currently-referenced figures already exist in `latex/Figure/` (verified 2026-06-16).

## 3. Style & integrity constraints (non-negotiable, from `latex/CLAUDE.md`)

- **English only**, American English, first-person singular ("I"). Vietnamese proper nouns keep diacritics.
- **Factual integrity is paramount.** Every number, module name, metric, and behavior claim traces to the codebase, its docs, or real command output. No estimates. Unverified facts get a `% TODO-VERIFY: <how>` tag, all resolved before any submission pass.
- **Do not restructure.** The 6-chapter skeleton, preamble, fonts, margins, headings are fixed (ISO 7144). Only content changes.
- Every chapter (2–6) opens with an Overview paragraph and closes with a Chapter-summary paragraph (plain prose). These already exist — preserve and adjust to new content.
- Chapter 5 stays problem → solution → result per contribution; cross-reference instead of repeating Chapters 2/4.
- Citations: IEEE via `\cite{...}`. Allowed: papers, books, theses, official org publications. `urldate` for web/official-doc sources.
- Acronyms: define in `glossary.tex` (`\newglossaryentry`), `\gls{...}` on first prose use.
- One sentence per source line where practical (clean diffs).
- Unwritten parts use `% TODO:` — never placeholder prose passing as final text.

## 4. Page budget

Current body ≈ 45–50 pages (figures inflate count; not independently compiled here). Targets below are *content* targets, not hard counts.

| Part | File | Current (lines / est. pp) | Target pp | Growth focus |
|---|---|---|---|---|
| Ch2 Survey | `2_Survey.tex` | 343 / ~10 | **12–14** | §2.1 status survey: cited literature on conversational AI, education chatbots, grounded QA; richer NFR rationale. |
| Ch3 Background | `3_Methodology.tex` | 97 / ~7 | **13–15** | Largest growth. Transformer + in-context learning; prompting taxonomy; embeddings + ANN/HNSW; RAG theory + hallucination motivation; agent taxonomy + state machines; OCR; async web stack. Heaviest citation target. |
| Ch4 Design/Impl/Eval | `4_Experiment_evaluation.tex` | 288 / ~15 | **18–21** | Design depth + algorithms (advisory dispatch, scoped retrieval) + listings (graph wiring, `_cursor`, `AgentState`/Pydantic schemas) + fuller DB/schema narrative. **Eval kept ~as-is.** |
| Ch5 Contribution | `5_Solution_contribution.tex` | 86 / ~5 | **9–11** | Algorithms: conflict-resolution decision logic, OCR-degeneracy detection+retry, gateway retry/fallback state machine; deeper cited problem framing (data fusion, truth discovery). |
| Ch6 Conclusion | `6_Conclusion.tex` | 39 / ~3 | **3–4** | Modest tightening; future-work depth. |
| Appendix A | `Appendix_A.tex` | 76 / ~3 | **5–7** | Add detailed UC-02 / UC-03 / UC-05 scenarios; edge-case → scenario mapping table. |

Bibliography and front matter add further pages. **Estimated post-expansion body: 64–78 pages**, satisfying the 60 floor inside the 65–75 zone.

## 5. Per-chapter content plan

Each item below is a *grounding-first* obligation: read the cited code/docs **before** writing, then write prose that quotes real module paths in `\texttt{...}`.

### 5.1 Chapter 2 — Requirement survey and analysis
- **§2.1 Status survey:** Deepen the five-channel survey. Add a cited paragraph on conversational AI / chatbots in education and on grounded (retrieval-backed) QA as the academic backdrop, so the gap analysis rests on literature, not only product names. Keep the existing comparison table; optionally add one row/column only if it stays truthful.
- **§2.2 Use cases / business process:** Largely intact (figures already present). Tighten the activity-process prose if needed.
- **§2.3 Functional description:** Keep UC-01..UC-05 tables. Add 1–2 sentences of rationale per UC where the codebase justifies it.
- **§2.4 Non-functional:** Expand each NFR's *justification* with the concrete code/config that enforces it (e.g., `ADVISORY_FETCH_VERIFY_SSL` for NFR-06, `tests/conftest.py::_isolate_test_db` for NFR-05). No new NFRs unless codebase-grounded.
- **Sources to read:** `docs/happy-path.md`, `docs/edge-case.md`, `docs/admission-advisory-conversational-architecture.md`.

### 5.2 Chapter 3 — Theoretical background and technologies
Largest expansion. Each technology still maps to a Ch2 requirement + names an alternative.
- **§3.1 LLMs & structured output:** Add Transformer/self-attention, in-context learning, instruction tuning, and a short prompting taxonomy (role/instruction, few-shot, structured/JSON). Cite real works. Motivate hallucination → grounding.
- **§3.2 RAG & vector search:** Add embedding theory (dense retrieval, sentence embeddings), cosine distance, ANN and the HNSW index used by pgvector, and the RAG pattern with a survey citation. Keep the pgvector-vs-dedicated-store rationale.
- **§3.3 Agentic pipelines:** Add the agent-design spectrum (autonomous tool-use loops vs structured state graphs), reference ReAct-style loops as the alternative, and justify the fixed LangGraph graph by determinism/traceability/separation — tie to NFR-01/02/05.
- **§3.4 Document processing:** Keep hybrid text+OCR rationale; add a short citation-backed framing of OCR and of model-based transcription failure modes (forward-references the §5.3 contribution).
- **§3.5 Web stack:** Keep FastAPI/Jinja2/Uvicorn/ThreadPoolExecutor; add brief async/ASGI and concurrency-model rationale.
- **Sources to read:** `services/inference/`, `services/knowledge/`, `graph.py`, `state.py`, `ingestion/` parsers/extractors.

### 5.3 Chapter 4 — Design, implementation, and evaluation
- **§4.1 Architecture:** Keep the monolith-vs-microservice rationale. Add a **code listing** of the LangGraph graph wiring (`graph.py`) and the per-node tracing wrapper, with explanation. Deepen the detailed-package-design narrative for the three core packages.
- **§4.2 Detailed design:** Keep both sequence-flow figures. Add an **algorithm** for advisory dispatch (endpoint → run record → background executor → poll) and one for scoped knowledge retrieval (school/topic scope + national-budget fan-out + confidence gate). Add a short **listing** of the `_cursor` context manager and an `AgentState`/Pydantic schema excerpt. Keep the §4.2 screenshot TODO as a `% TODO`.
- **§4.3 Libraries / achievement:** **Re-verify all numbers** against the current branch (see §7). Keep tables; update values.
- **§4.4 Testing:** Keep as-is (re-verify counts/timings). Edge-case matrix preserved.
- **§4.5 Deployment:** Keep; optionally add the one-command setup sequence as a short listing if accurate.
- **Sources to read:** `web/app.py`, `services/chat/`, `services/knowledge/qa_service.py`, `db/migrations/`, repositories, `tests/conftest.py`, `docker-compose.yml`, `requirements.txt`.

### 5.4 Chapter 5 — Solution and contribution
Each contribution: problem → solution → result; cross-reference, don't repeat.
- **§5.1 Conflict-aware consolidation:** Add an **algorithm** for the conflict resolution decision logic (per-source rows → group by program/year/method → quota path: deterministic trust/confidence compare, constrained LLM tie-break only if non-decisive; cutoff path: decision-changing test → leave unresolved vs reference most-trusted). Deepen problem framing with data-fusion / truth-discovery citations.
- **§5.2 Resilient inference gateway:** Add an **algorithm/state-machine** for hard-failure vs `STRUCTURE_FAILURE` handling (retry budget, fallback model, re-raise → call-site degradation) and the deterministic keyword intent-router fallback (commit `c2ef582`).
- **§5.3 Heterogeneous ingestion:** Add an **algorithm** for hybrid per-page extraction + degenerate-OCR detection (char ceiling, single-char dominance) + one retry at raised temperature (commit `b41dd9f`). Keep the result figures grounded in re-verified store counts.
- **Sources to read:** `services/conflict/` (`detection.py`, `keys.py`, `conflict_agent`, explanation), `services/inference/gateway.py`/`registry.py`, intent router, `ingestion/` OCR path.

### 5.5 Chapter 6 — Conclusion and future work
- Keep the achieved-vs-limits framing. Tighten and lightly expand future-work: structured preferences cluster (EC-07/08/11/19/20/25), location/budget-aware retrieval, more schools, production hardening. No new claims beyond Chapters 4/5.

### 5.6 Appendix A — Use case descriptions
- Keep existing UC-01.x scenarios.
- Add detailed scenarios overflowing from §2.3 that the main text states only in outline: **UC-02** (knowledge QA: scoped retrieval, national-budget, no-data honesty), **UC-03** (hybrid comparison fan-out + synthesis), **UC-05** (ingestion run incl. scanned-PDF OCR alternative flow).
- Add an **edge-case → scenario mapping table** linking `docs/edge-case.md` cases (EC-01..EC-25, with pass/partial/fail status) to the appendix scenarios. This is legitimate, codebase-grounded content that also adds pages.

## 6. References plan

- **Source discovery:** Use WebSearch/WebFetch to find and **verify the existence and metadata** of each new academic source before adding it. Add a source only if it backs a specific claim already in the prose.
- **Candidate academic additions** (verify each; add only if cited):
  - Instruction tuning (InstructGPT / Ouyang et al. 2022)
  - Chain-of-thought prompting (Wei et al. 2022)
  - Sentence embeddings (Reimers & Gurevych, SBERT 2019) and/or dense passage retrieval (Karpukhin et al. 2020)
  - HNSW approximate nearest neighbor (Malkov & Yashunin 2018/2020)
  - RAG survey (Gao et al. 2023)
  - ReAct (Yao et al. 2022) as the agentic-loop alternative
  - LLM hallucination survey (Ji et al. 2023) to motivate grounding
  - Truth discovery / conflict-resolution survey (e.g., Li et al. 2016) alongside existing `bleiholder2009fusion`
- **Format:** Match the existing `reference.bib` entry style (biblatex, `style=ieee`). Academic entries use `@inproceedings`/`@article`/`@misc` with full author lists; official-doc entries include `url` + `urldate`. No DOIs invented; include only verified ones.
- **Glossary:** Add `\newglossaryentry` for any new acronym introduced (e.g., ANN if used; HNSW/API/JSON already exist — confirm before adding). `\gls{...}` on first use.
- **Existing 30 entries:** keep; remove none unless found inaccurate.

## 7. Fact re-verification (do FIRST, before writing)

`latex/FACTS.md` was measured 2026-06-08 on `feat/thesis-report`. Current branch is `refactor/codebase`; counts may have shifted (e.g., migration count, LOC, test count, store rows). Before writing any number:

1. Re-measure on the current branch and **update `latex/FACTS.md`** (date-stamp the new measurement). Commands already documented in FACTS.md:
   - Python LOC / file counts (`git ls-files '*.py' | xargs wc -l`).
   - Migration count (`db/migrations/`).
   - Test collection (`python -m pytest --collect-only -q`) and, if feasible, a full-suite result (needs Docker DB up).
   - Canonical/cutoff/embedding/knowledge counts (requires the dev DB; if DB not available, tag affected sentences `% TODO-VERIFY` rather than guess).
   - Library versions (`requirements.txt`).
2. Reconcile the migration-count discrepancy (root `CLAUDE.md` says 001–013; `FACTS.md`/`OUTLINE.md` say 001–016) — use the **actual** files on disk as truth and fix the stale doc.
3. Any number that cannot be measured in this environment gets `% TODO-VERIFY` with the exact command to run.

## 8. Verification / done criteria

A part is "done" when:

1. **Page target trajectory** — combined Ch2–6 + Appendix expansion is on track for 65–75 body pages (judged by content, not by padding).
2. **Cross-references resolve** — every `\ref`, `\cite`, `\gls` target exists:
   ```powershell
   Select-String -Path latex\Chapter\*.tex -Pattern '\\(ref|cite|gls)\{[^}]+\}' -AllMatches
   ```
   Every `\cite` key exists in `reference.bib`; every `\gls` key exists in `glossary.tex`.
3. **No unresolved facts** — `Select-String -Path latex\Chapter\*.tex -Pattern 'TODO-VERIFY'` returns nothing before the final pass (during drafting, TODO-VERIFY tags are allowed and tracked).
4. **No placeholder prose** — no `% TODO:` left where final text is expected (the §4.2 screenshot TODO is the one sanctioned exception, since it needs a live Gemini run).
5. **Style compliance** — English/first-person; each chapter keeps overview + summary paragraphs; new algorithms/listings each have a caption and an in-text reference; one-sentence-per-line preserved.
6. **Citations are real** — every new `reference.bib` entry corresponds to a source verified to exist.
7. **No structural/template edits** — `git diff` touches only the in-scope files (plus `FACTS.md`, `reference.bib`, `glossary.tex`).

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Expansion slips into padding | D3 levers are all content-bearing; reviewer pass checks each new paragraph adds a fact/rationale not stated elsewhere. |
| Numbers stale on new branch | §7 re-verification gate runs first; `% TODO-VERIFY` for anything unmeasurable here. |
| DB unavailable → can't re-measure store counts | Tag those sentences `% TODO-VERIFY`; keep last-known values only if explicitly noted as such. |
| Fabricated/incorrect citations | D4: every source web-verified before insertion; no source added without a backing claim. |
| Listings/algorithms drift from real code | Each listing is an excerpt copied from the actual module and cited by path; algorithms describe the real control flow in the named module. |
| Compilation breaks (no local LaTeX) | Structural self-check via `Select-String`; keep `algorithm2e`/`listings` usage within the already-loaded package setup; author compiles on Prism. |

## 10. Execution order (for the plan that follows)

1. Re-verify facts; update `latex/FACTS.md` (§7).
2. Web-search + add verified references and glossary entries (§6).
3. Chapter 3 (largest lift; sets the citation backbone).
4. Chapter 5 (algorithms; depends on Ch3 background + Ch4 cross-refs).
5. Chapter 4 (design depth, listings, algorithms; re-verified numbers).
6. Chapter 2 (literature additions; uses Ch3 citations).
7. Appendix A (scenarios + mapping table).
8. Chapter 6 (tighten; depends on final Ch4/Ch5 content).
9. Final pass: resolve all `TODO-VERIFY`, run the §8 verification checks.
