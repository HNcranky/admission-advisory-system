# Thesis LaTeX Workspace Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up `latex/` as the English-language graduation-thesis workspace (SoICT template) with directory-scoped writing rules, a clean scaffold, and a per-chapter outline mapped to the codebase.

**Architecture:** `latex/` is a cleaned copy of `latex-template/` (read-only reference): Vietnamese guideline prose stripped, cover metadata filled, missing `lstlisting.tex` created, template guideline chapters dropped. Writing rules live in `latex/CLAUDE.md` (auto-loaded only when working under `latex/`); the root `CLAUDE.md` gets a pointer. `latex/OUTLINE.md` maps each chapter section to codebase modules/docs.

**Tech Stack:** LaTeX (report class, subfiles, biblatex/bibtex IEEE, glossaries). No local compiler — the user compiles externally (Prism); correctness checks are structural (grep).

**Spec:** `docs/superpowers/specs/2026-06-07-thesis-latex-setup-design.md`

**Conventions for all commits:** plain `git commit -m "..."` — NO `Co-Authored-By` or AI attribution, never `git push` (repo rule).

---

### Task 1: LaTeX build artifacts in `.gitignore`

**Files:**
- Modify: `.gitignore` (append at end, after the `data/knowledge/` block)

- [ ] **Step 1: Append LaTeX block to `.gitignore`**

```gitignore
# LaTeX build artifacts (thesis lives in latex/, compiled externally)
*.aux
*.bbl
*.blg
*.fdb_latexmk
*.fls
*.glo
*.gls
*.glsdefs
*.ist
*.lof
*.log
*.lot
*.out
*.run.xml
*.synctex.gz
*.toc
*.bcf
latex/main.pdf
```

- [ ] **Step 2: Verify nothing currently tracked becomes ignored**

Run: `git -C D:\Work\admission-advisory-system status --short`
Expected: `.gitignore` modified; no tracked file disappears from status.

- [ ] **Step 3: Commit**

```powershell
git add .gitignore
git commit -m "chore: ignore LaTeX build artifacts"
```

---

### Task 2: Scaffold `latex/` top-level files

**Files:**
- Create: `latex/main.tex` (from `latex-template/main.tex`)
- Create: `latex/Cover.tex`, `latex/Cover2.tex`
- Create: `latex/lstlisting.tex` (template references it but does not ship it — compile would fail without it)
- Create: `latex/glossary.tex`
- Create: `latex/reference.bib`
- Create: `latex/Figure/.gitkeep` (template demo images are NOT copied)

- [ ] **Step 1: Copy `latex-template/main.tex` → `latex/main.tex`, then apply these edits**

1. Metadata (lines 80–81 of the template):

```latex
\def \TITLE{Building an End-to-End Data Ingestion and LLM-Based Advisory System for University Admission Counseling}
\def \AUTHOR{Nguyen Viet Anh}
```

2. Delete the "SHORT NOTICES ON REFERENCE" guideline block (template lines 305–309):

```latex
\newpage
%\pagestyle{fancy} % Áp dụng header và footer
\chapter*{SHORT NOTICES ON REFERENCE} %Kết luận và hướng phát triển}
\label{chapter:reference}
\subfile{Chapter/7_Reference}
```

3. Replace the two appendix chapters (template lines 337–341) with a single thesis-relevant appendix:

```latex
\chapter{USE CASE DESCRIPTIONS}
\subfile{Chapter/Appendix_A}
```

4. Leave the preamble otherwise byte-identical (the format is mandated by the school).

- [ ] **Step 2: Create `latex/lstlisting.tex`**

```latex
% Code-listing configuration (referenced by \include{lstlisting} in main.tex).
% The template does not ship this file; minimal Python-oriented setup.
\lstset{
  basicstyle=\ttfamily\small,
  breaklines=true,
  frame=single,
  numbers=left,
  numberstyle=\tiny,
  showstringspaces=false,
  tabsize=2,
  captionpos=b,
  language=Python
}
\renewcommand{\lstlistingname}{Listing}
```

- [ ] **Step 3: Create `latex/Cover.tex`** — copy of template `Cover.tex` with:

- Title line uses the macro instead of hard-coded text: `{\textbf{\Large{\TITLE}}}\\[1cm]`
- `{\textbf{\large{NGUYEN VIET ANH -- 20225434}}}\\`
- `{\large{<sis-email>}}\\[0.5cm]` (placeholder — unknown)
- `{\textbf{\large{Program: <Program>}}}\\` (placeholder — unknown)
- Supervisor row: `Assoc. Prof. Le Thanh Huong`
- Department row: `<Department>` (placeholder — unknown)
- School row unchanged: `School of Information and Communications Technology`
- Date: `\textbf{HANOI, 06/2026}`

- [ ] **Step 4: Create `latex/Cover2.tex`** — same replacements as Cover.tex (Cover2 additionally has the supervisor Signature line — keep it). Also fix the parent reference on line 1: `\documentclass[main.tex]{subfiles}` (template says `DoAn.tex`, which does not exist).

- [ ] **Step 5: Create `latex/glossary.tex`** — replace template demo entries with real seed acronyms (English descriptions; grow the list while writing):

```latex
%\makeglossaries
\makenoidxglossaries

\newglossaryentry{LLM}{
    type=\acronymtype,
    name={LLM},
    description={Large Language Model},
    first={Large Language Model (LLM)}
}
\newglossaryentry{RAG}{
    type=\acronymtype,
    name={RAG},
    description={Retrieval-Augmented Generation},
    first={Retrieval-Augmented Generation (RAG)}
}
\newglossaryentry{OCR}{
    type=\acronymtype,
    name={OCR},
    description={Optical Character Recognition},
    first={Optical Character Recognition (OCR)}
}
\newglossaryentry{API}{
    type=\acronymtype,
    name={API},
    description={Application Programming Interface},
    first={Application Programming Interface (API)}
}
\newglossaryentry{UI}{
    type=\acronymtype,
    name={UI},
    description={User Interface},
    first={User Interface (UI)}
}
```

- [ ] **Step 6: Create `latex/reference.bib`** — drop all template demo entries; seed with verified official-source references used by the project:

```bibtex
% IEEE style via biblatex (backend=bibtex). Official publications only —
% no lecture slides, no Wikipedia, no ordinary web pages (school rule).

@misc{langgraph,
  author  = {{LangChain, Inc.}},
  title   = {LangGraph},
  url     = {https://github.com/langchain-ai/langgraph},
  urldate = {2026-06-07}
}

@misc{pgvector,
  author  = {Kane, Andrew},
  title   = {pgvector: Open-source vector similarity search for Postgres},
  url     = {https://github.com/pgvector/pgvector},
  urldate = {2026-06-07}
}

@misc{fastapi,
  author  = {Ram{\'i}rez, Sebasti{\'a}n},
  title   = {FastAPI},
  url     = {https://fastapi.tiangolo.com},
  urldate = {2026-06-07}
}

@misc{gemini,
  author  = {{Google}},
  title   = {Gemini {API} Documentation},
  url     = {https://ai.google.dev},
  urldate = {2026-06-07}
}
```

- [ ] **Step 7: Create empty `latex/Figure/.gitkeep`**

- [ ] **Step 8: Verify structure**

Run: `Get-ChildItem D:\Work\admission-advisory-system\latex`
Expected: `Chapter` missing (next task), `Figure/`, `main.tex`, `Cover.tex`, `Cover2.tex`, `lstlisting.tex`, `glossary.tex`, `reference.bib`.

(Do not commit yet — `main.tex` references `Chapter/` subfiles created in Task 3; commit both together.)

---

### Task 3: Chapter skeletons (English, guideline prose stripped)

**Files:**
- Create: `latex/Chapter/0_2_acknowledgment.tex`
- Create: `latex/Chapter/0_3_abstract.tex`
- Create: `latex/Chapter/1_Introduction.tex`
- Create: `latex/Chapter/2_Survey.tex`
- Create: `latex/Chapter/3_Methodology.tex`
- Create: `latex/Chapter/4_Experiment_evaluation.tex`
- Create: `latex/Chapter/5_Solution_contribution.tex`
- Create: `latex/Chapter/6_Conclusion.tex`
- Create: `latex/Chapter/Appendix_A.tex`

All files: first line `\documentclass[../main.tex]{subfiles}` (normalize the template's inconsistent `../Main.tex` / `../DoAn.tex` — case matters on Linux build servers). Section headings keep the template skeleton; every body is a `% TODO:` comment so unwritten sections are grep-able, never silent filler prose.

- [ ] **Step 1: Create `latex/Chapter/0_2_acknowledgment.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\pagenumbering{roman}
\begin{document}
\begin{center}
    \Large{\textbf{ACKNOWLEDGMENTS}}\\
\end{center}
\vspace{1cm}
% TODO: acknowledgments, 100-150 words, concrete and concise.
\end{document}
```

- [ ] **Step 2: Create `latex/Chapter/0_3_abstract.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\begin{document}

\begin{center}
    \Large{\textbf{ABSTRACT}}\\
\end{center}
\vspace{1cm}
% TODO: abstract, 200-350 words, single prose paragraph(s), no bullets:
% (i) problem, (ii) chosen approach and why, (iii) solution overview,
% (iv) main contributions and final results.
\begin{flushright}
\begin{tabular}{@{}c@{}}
Student\\
\textit{(Signature and full name)}\\[1cm]
Nguyen Viet Anh
\end{tabular}
\end{flushright}
\end{document}
```

- [ ] **Step 3: Create `latex/Chapter/1_Introduction.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\begin{document}

% Target length: 3-6 pages.

\section{Motivation}
\label{section:1.1}
% TODO: the problem only, no solution: fragmented and conflicting Vietnamese
% university admission information (official school pages, proposal PDFs,
% ministry announcements); stakes for students choosing programs.

\section{Objectives and scope of the graduation thesis}
\label{section:1.2}
% TODO: survey existing advisory products/research at a high level, their
% limitations, then state the concrete objectives and scope of this thesis.

\section{Tentative solution}
\label{section:1.3}
% TODO: (i) direction/technologies (LLM agents, RAG, data ingestion pipeline),
% (ii) one-two sentence solution description, (iii) main contributions and results.

\section{Thesis organization}
\label{section:1.4}
% TODO: prose paragraphs describing Chapters 2-6 (no bullets; Chapter 1 excluded).

\end{document}
```

- [ ] **Step 4: Create `latex/Chapter/2_Survey.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\begin{document}

% Target length: 9-11 pages. Open with an Overview paragraph, close with a
% Chapter summary paragraph (plain prose, "Normal" formatting).

% TODO: Overview paragraph.

\section{Status survey}
\label{section:2.1}
% TODO: existing admission-advisory channels and tools; comparison and
% limitations. Sources: docs/happy-path.md, docs/edge-case.md.

\section{Functional overview}
\label{section:2.2}

\subsection{General use case diagram}
\label{subsection:2.2.1}
% TODO: actors (student, administrator/operator) and main use cases.

\subsection{Detailed use case diagrams}
\label{subsection:2.2.2}
% TODO: one subsection per decomposed high-level use case.

\subsection{Business process}
\label{subsection:2.2.3}
% TODO: advisory conversation flow: profile collection -> retrieval ->
% conflict handling -> recommendation -> explanation.

\section{Functional description}
\label{section:2.3}
% TODO: detailed specs for 4-7 key use cases: name, main/alternative flows,
% pre-conditions, post-conditions.

\section{Non-functional requirement}
\label{section:2.4}
% TODO: data freshness/conflict tolerance, graceful LLM degradation, latency,
% anonymous sessions, database requirements.

% TODO: Chapter summary paragraph.

\end{document}
```

- [ ] **Step 5: Create `latex/Chapter/3_Methodology.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\begin{document}

% Target length: <= 10 pages. Existing knowledge only - analyze and summarize;
% for each technology: which Chapter 2 requirement it serves, what the
% alternatives were, why this choice. Cite official sources.

% TODO: Overview paragraph.

\section{Large language models}
% TODO: LLM background; Gemini model family \cite{gemini}; alternatives.

\section{Retrieval-augmented generation and vector search}
% TODO: RAG; embeddings; PostgreSQL + pgvector \cite{pgvector}; alternatives.

\section{Agentic pipelines}
% TODO: agent orchestration; LangGraph \cite{langgraph}; state graphs;
% alternatives (sequential prompting, function-calling loops).

\section{Document processing and OCR}
% TODO: PDF/HTML ingestion, OCR for scanned admission proposals; degenerate
% output detection.

\section{Web technologies}
% TODO: FastAPI \cite{fastapi}, server-rendered UI, background execution.

% TODO: Chapter summary paragraph.

\end{document}
```

- [ ] **Step 6: Create `latex/Chapter/4_Experiment_evaluation.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\begin{document}

% TODO: Overview paragraph.

\section{Architecture design}
\subsection{Software architecture selection}
% TODO: layered service-oriented monolith; why not microservices.

\subsection{Overall design}
% TODO: UML package diagram: web / services (chat, inference, knowledge,
% conflict, tracing) / agents / ingestion / db.

\subsection{Detailed package design}
% TODO: per-package class diagrams (agents pipeline, services/inference,
% ingestion pipeline).

\section{Detailed design}
\subsection{User interface design}
% TODO: chat UI design, debug/trace panel.

\subsection{Layer design}
% TODO: key classes (inference gateway, chat dispatchers, repositories) +
% sequence diagrams for 2-3 key use cases.

\subsection{Database design}
% TODO: E-R diagram; canonical store (schools, programs, quotas, methods,
% cutoffs); pgvector knowledge tables; migrations 001-013.

\section{Application building}
\subsection{Libraries and tools}
% TODO: table of tools with versions (Python, FastAPI, LangGraph, psycopg,
% pgvector, pytest, Docker).

\subsection{Achievement}
% TODO: statistics: LOC, packages, test counts, ingested schools/documents.
% All numbers must be measured, not estimated.

\subsection{Illustration of main functions}
% TODO: screenshots of main advisory flows.

\section{Testing}
% TODO: test strategy (unit/integration/e2e, isolated test DB), edge-case
% compliance evaluation, results analysis.

\section{Deployment}
% TODO: Docker Compose deployment, configuration, observed behavior.

% TODO: Chapter summary paragraph.

\end{document}
```

- [ ] **Step 7: Create `latex/Chapter/5_Solution_contribution.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\begin{document}

% Target length: >= 5 pages. One section per contribution, each with
% (i) problem, (ii) solution, (iii) results. No repetition of earlier
% chapters - they cross-reference here.

% TODO: Overview paragraph.

\section{Conflict-aware data consolidation}
% TODO: problem: contradictory quota/cutoff data across sources;
% solution: conflict detection + LLM tiebreaker (services/conflict/);
% results.

\section{Resilient LLM inference gateway}
% TODO: problem: LLM outages/malformed outputs; solution: gateway with
% retry, structure-failure fallback, deterministic keyword fallback
% (services/inference/); results.

\section{End-to-end ingestion of heterogeneous official sources}
% TODO: problem: per-school formats, scanned PDFs; solution: configurable
% fetcher/parser/extractor pipeline with degenerate-OCR retry; results.

% TODO: Chapter summary paragraph.

\end{document}
```

- [ ] **Step 8: Create `latex/Chapter/6_Conclusion.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\begin{document}

\section{Conclusion}
% TODO: compare against similar products; what was and was not achieved;
% lessons learned.

\section{Future work}
% TODO: completing remaining edge cases (structured preferences), more
% schools, retrieval/reasoning over location and budget, deployment hardening.

\end{document}
```

- [ ] **Step 9: Create `latex/Chapter/Appendix_A.tex`**

```latex
\documentclass[../main.tex]{subfiles}
\begin{document}

% TODO: full use case descriptions that did not fit in Section 2.3.

\end{document}
```

- [ ] **Step 10: Verify no Vietnamese guideline text and no broken subfile refs**

Run:
`Select-String -Path D:\Work\admission-advisory-system\latex\*.tex,D:\Work\admission-advisory-system\latex\Chapter\*.tex -Pattern '[ạảãàáâậầấẩẫăắằẳẵặđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]' -CaseSensitive`
Expected: matches ONLY in `main.tex` (Vietnamese comments in the mandated preamble are acceptable) — zero matches in `Chapter/*.tex`, `Cover*.tex`, `glossary.tex`.

Run:
`Select-String -Path D:\Work\admission-advisory-system\latex\main.tex -Pattern 'subfile\{([^}]+)\}' -AllMatches | ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value }`
Expected: every listed path exists under `latex/` (with `.tex` appended where omitted).

- [ ] **Step 11: Commit Tasks 2+3 together**

```powershell
git add latex/
git commit -m "feat(thesis): scaffold latex workspace from SoICT template"
```

---

### Task 4: `latex/CLAUDE.md` (writing rules)

**Files:**
- Create: `latex/CLAUDE.md`

- [ ] **Step 1: Create `latex/CLAUDE.md` with exactly this content**

````markdown
# CLAUDE.md — Thesis writing rules (`latex/`)

Graduation thesis of **Nguyen Viet Anh (20225434)**, SoICT, HUST.
Title: *Building an End-to-End Data Ingestion and LLM-Based Advisory System
for University Admission Counseling*. Supervisor: Assoc. Prof. Le Thanh Huong.

The thesis documents THIS repository (the admission advisory system). The
chapter-by-chapter content map lives in `latex/OUTLINE.md` — consult it before
writing any section.

## Hard rules

- **English only** (American English), first-person singular ("I"). No
  Vietnamese in prose; Vietnamese proper nouns (school names, document titles)
  keep their diacritics.
- **Factual integrity — the most important rule.** Every number, module name,
  metric, and behavior claim must be traceable to this codebase, its docs, or
  real command output. Never estimate or invent statistics ("about 50k lines",
  "95% accuracy"). If a fact is not yet verified, write the sentence and tag it
  `% TODO-VERIFY: <how to verify>`. Before any submission pass, grep for
  `TODO-VERIFY` and resolve all of them.
- **`latex-template/` is read-only reference.** Never edit it. Never copy its
  Vietnamese guideline prose into `latex/`.
- **Do not restructure.** The 6-chapter skeleton, `main.tex` preamble, fonts,
  margins, and heading formats are mandated by the school (ISO 7144). Only
  metadata (`\TITLE`, `\AUTHOR`) and content change.

## Style (from the school's writing guideline)

- One main idea per paragraph; supporting sentences only develop that idea.
  Consecutive paragraphs and sentences must connect logically.
- Scientific register: no colloquialisms, no hype or emotional words
  ("amazing", "extremely useful"), no unsupported superlatives.
- Every chapter (2-6) opens with an Overview paragraph (links back to the
  previous chapter, previews this one) and closes with a Chapter summary
  paragraph (links forward). Plain prose, no special formatting.
- Chapter descriptions in §1.4 and all abstract content are prose paragraphs —
  never bullet lists.
- Chapter 5 is the contribution showcase: each contribution = problem →
  solution → results, no repetition of earlier chapters (cross-reference
  instead).

## Mechanics

- Citations: IEEE via `reference.bib` (`\cite{...}`). Allowed sources: papers,
  books, theses, and *official* organizational publications (e.g., a project's
  own documentation site). Forbidden: lecture slides, Wikipedia, ordinary web
  pages. Every external-technology claim (LangGraph, pgvector, Gemini, FastAPI,
  …) needs a citation. Add `urldate` for web sources.
- Acronyms: define in `glossary.tex` (`\newglossaryentry`), use `\gls{...}` on
  first use in prose.
- Figures: `latex/Figure/`, referenced with `\ref{fig:...}`; every figure and
  table needs a caption and an in-text reference.
- Unwritten sections carry a `% TODO:` comment — never placeholder prose that
  could pass as final text.
- One sentence per source line where practical (cleaner git diffs).

## Compilation

No local LaTeX toolchain. The user compiles externally (Prism) — after editing,
self-check structurally instead of compiling:

```powershell
# Every \ref/\cite/\gls target must exist
Select-String -Path latex\Chapter\*.tex -Pattern '\\(ref|cite|gls)\{[^}]+\}' -AllMatches
# No unresolved facts before a submission pass
Select-String -Path latex\Chapter\*.tex -Pattern 'TODO-VERIFY'
```

If MiKTeX/TeX Live is installed later, add the build command here.

## Workflow

- Cover placeholders still unknown: `<sis-email>`, `<Program>`, `<Department>`
  in `Cover.tex`/`Cover2.tex` — ask the user before any submission pass.
- When writing a section, read the relevant code/docs FIRST (paths in
  `OUTLINE.md`), then write. Quote real module paths in `\texttt{...}`.
- Keep `OUTLINE.md` in sync when content moves between chapters.
````

- [ ] **Step 2: Commit**

```powershell
git add latex/CLAUDE.md
git commit -m "docs(thesis): add writing rules for latex workspace"
```

---

### Task 5: Pointer section in root `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (repo root) — append after the "Conventions & gotchas" section

- [ ] **Step 1: Append this section to root `CLAUDE.md`**

```markdown
## Thesis writing

The graduation thesis (English, LaTeX) lives in `latex/` — rules and the
chapter outline are in `latex/CLAUDE.md` and `latex/OUTLINE.md`.
`latex-template/` is the school's read-only reference template: never edit it.
```

- [ ] **Step 2: Commit**

```powershell
git add CLAUDE.md
git commit -m "docs: point root CLAUDE.md at thesis workspace rules"
```

---

### Task 6: `latex/OUTLINE.md` (chapter ↔ codebase map)

**Files:**
- Create: `latex/OUTLINE.md`

- [ ] **Step 1: Create `latex/OUTLINE.md` with exactly this content**

````markdown
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
      `ingestion/configs/`), Vietnamese-language user dialogue.
- [ ] 1.3 Tentative solution: LangGraph advisory pipeline + RAG over pgvector +
      resilient Gemini gateway; contributions preview (→ Chapter 5).
- [ ] 1.4 Thesis organization: prose description of Chapters 2-6.

## Chapter 2 — Requirement survey and analysis (9-11 pages)
Sources: `docs/happy-path.md`, `docs/edge-case.md`,
`docs/admission-advisory-conversational-architecture.md`.
- [ ] 2.1 Status survey: existing advisory products; comparison table.
- [ ] 2.2.1 General use case diagram: actors = student (anonymous chat),
      operator (ingestion CLI, debug/trace panel).
- [ ] 2.2.2 Detailed use case diagrams: advisory conversation; knowledge Q&A;
      data ingestion.
- [ ] 2.2.3 Business process: profile collection → retrieval → conflict
      check → reasoning → policy → explanation (mirrors `graph.py`).
- [ ] 2.3 Functional description: 4-7 key use cases with flows and pre/post
      conditions (advisory consultation, free-form Q&A, profile update,
      school data refresh).
- [ ] 2.4 Non-functional: LLM-outage graceful degradation, data freshness,
      anonymous sessions, latency, test isolation.

## Chapter 3 — Theoretical background and technologies (≤ 10 pages)
Rule: each technology must map to a Chapter 2 requirement + name alternatives.
- [ ] 3.1 LLMs: Gemini family (cite), prompting, structured output.
- [ ] 3.2 RAG + vector search: embeddings, pgvector (cite); alternative:
      dedicated vector DBs; why Postgres-integrated.
- [ ] 3.3 Agentic pipelines: LangGraph (cite) state graphs; alternative:
      plain function-calling loop; why a fixed graph (determinism,
      traceability).
- [ ] 3.4 Document processing: PDF parsing, OCR for scanned proposals,
      degenerate-OCR detection rationale.
- [ ] 3.5 Web stack: FastAPI (cite), Jinja2, background ThreadPoolExecutor.

## Chapter 4 — Design, implementation, and evaluation
- [ ] 4.1.1 Architecture selection: layered service-oriented monolith.
- [ ] 4.1.2 Overall design: package diagram from real packages: `web/`,
      `services/{chat,inference,knowledge,conflict,tracing}`, `agents/`,
      `ingestion/`, `db/`.
- [ ] 4.1.3 Detailed package design: advisory graph
      (`graph.py`, `state.py::AgentState`, `agents/*`); inference gateway
      (`services/inference/gateway.py`, `registry.py`,
      `providers/gemini_provider.py`); ingestion
      (`ingestion/pipeline/ingestion_pipeline.py`, fetchers/parsers/
      extractors/normalization, `storage/db_writer.py`).
- [ ] 4.2.1 UI design: chat UI, debug/trace panel (`services/tracing/`).
- [ ] 4.2.2 Layer design: sequence diagrams for advisory run dispatch
      (`services/chat/` background executor) and knowledge Q&A
      (`services/knowledge/qa_service.py`).
- [ ] 4.2.3 Database design: E-R of canonical store; migrations
      `db/migrations/001-013`; pgvector tables; repository pattern with
      injectable `connection_factory` + `_cursor` context manager.
- [ ] 4.3.1 Libraries/tools table: versions from `requirements.txt` /
      `pyproject.toml` (verify).
- [ ] 4.3.2 Achievement: LOC, package/test counts, ingested schools
      HUST/NEU/UET + MOET documents (verify counts: hust 136 programs,
      cutoffs 715, catalog 83 — re-measure before writing).
- [ ] 4.3.3 Screenshots of main flows.
- [ ] 4.4 Testing: pytest suite on isolated `admission_test` DB
      (`tests/conftest.py::_isolate_test_db`); edge-case compliance matrix
      result 17/25 passing (verify against `docs/edge-case.md` run).
- [ ] 4.5 Deployment: Docker Compose (pgvector/pgvector:pg16), uvicorn.

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
````

- [ ] **Step 2: Commit**

```powershell
git add latex/OUTLINE.md
git commit -m "docs(thesis): add chapter outline mapped to codebase"
```

---

### Task 7: Final verification

- [ ] **Step 1: Whole-tree checks**

Run:
`Select-String -Path D:\Work\admission-advisory-system\latex\Chapter\*.tex,D:\Work\admission-advisory-system\latex\Cover*.tex,D:\Work\admission-advisory-system\latex\glossary.tex -Pattern '[ạảãàáâậầấẩẫăắằẳẵặđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]' -CaseSensitive`
Expected: no output.

Run: `git -C D:\Work\admission-advisory-system status --short`
Expected: clean working tree (everything committed), `latex-template/` still untracked & untouched.

- [ ] **Step 2: Report to user**

Summarize created files; remind about the three cover placeholders
(`<sis-email>`, `<Program>`, `<Department>`) and suggest a first Prism compile
to validate the scaffold before writing prose.
