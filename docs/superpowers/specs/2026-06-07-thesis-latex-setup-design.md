# Thesis LaTeX Workspace Setup — Design

**Date:** 2026-06-07
**Status:** Approved
**Goal:** Set up the repository so Claude Code can co-write the graduation thesis
(in English, LaTeX) based on this codebase, using the SoICT template in
`latex-template/` and composing into `latex/`.

## Context

- `latex-template/` holds the official HUST/SoICT graduation-thesis template
  (`main.tex`, `Cover.tex`, `Cover2.tex`, `glossary.tex`, `reference.bib`,
  `Chapter/0_2 … 7 + Appendix_A/B`, `Figure/`). Chapter files contain Vietnamese
  writing-guideline text that must not appear in the final thesis.
- `latex/` does not exist yet.
- No LaTeX toolchain is installed locally (`pdflatex`/`latexmk`/`bibtex` absent).
  The user compiles externally (Prism). Local install is optional later and does
  not conflict with external compilation.
- Thesis metadata:
  - Title: *Building an End-to-End Data Ingestion and LLM-Based Advisory System
    for University Admission Counseling*
  - Author: Nguyen Viet Anh — 20225434
  - Supervisor: Assoc. Prof. Le Thanh Huong
  - School: School of Information and Communications Technology, HUST
  - Date on cover: HANOI, 06/2026
  - Email / Program / Department: unknown → use `<...>` placeholders.

## Deliverables

1. **`latex/CLAUDE.md`** — directory-scoped writing rules (see below).
2. **Root `CLAUDE.md`** — add a short "Thesis writing" section pointing to
   `latex/CLAUDE.md` and marking `latex-template/` as read-only reference.
3. **`latex/` scaffold** — copy of the template with:
   - Cover placeholders replaced with the real metadata (placeholders where
     unknown).
   - All Vietnamese guideline prose stripped from chapter files; keep the
     `\section` skeleton mandated by the template.
   - `main.tex` preamble untouched except metadata (`\TITLE`, `\AUTHOR`).
   - `Figure/` carried over only with assets actually needed (cover images);
     template demo images dropped.
4. **`latex/OUTLINE.md`** — detailed per-chapter outline mapping thesis content
   to codebase modules and docs.
5. **`.gitignore`** — LaTeX build-artifact block (`*.aux`, `*.log`, `*.bbl`,
   `*.blg`, `*.toc`, `*.lof`, `*.lot`, `*.out`, `*.glo`, `*.gls`, `*.glsdefs`,
   `*.ist`, `*.fls`, `*.fdb_latexmk`, `*.synctex.gz`, `latex/main.pdf`).

## `latex/CLAUDE.md` rules (summary)

- **Language:** 100% English (American), first-person singular "I".
- **Style** (adapted from template Appendix A / ISO 7144): one main idea per
  paragraph; no colloquial or exaggerated wording; every chapter opens with an
  Overview and closes with a Chapter summary written as prose (no bullet lists
  for chapter descriptions).
- **Factual integrity (most important):** every number, module name, and system
  behavior stated in the thesis must be traceable to the codebase, docs, or real
  test output (e.g., edge-case matrix 17/25, ingested schools). Unverified
  claims are marked `% TODO-VERIFY`. Never fabricate metrics.
- **Structure:** keep the template's 6 chapters + appendices; do not reorganize.
  Preamble/format of `main.tex` is fixed apart from metadata.
- **Citations:** IEEE via `reference.bib`; external-technology claims
  (LangGraph, pgvector, Gemini, …) must be cited.
- **Compilation:** user compiles on Prism; Claude writes `.tex` and checks
  cross-refs/cites by inspection (grep for `\ref`/`\cite` targets). If MiKTeX is
  installed later, add build commands here.
- **`latex-template/` is read-only.**

## Chapter outline (high level — detail goes in `latex/OUTLINE.md`)

1. **Introduction** — fragmented & conflicting Vietnamese admission data;
   objectives & scope; tentative solution; thesis organization.
2. **Requirement survey and analysis** — existing tools survey; actors and use
   cases; requirements (from `docs/happy-path.md`, `docs/edge-case.md`).
3. **Theoretical background and technologies** — LLM/RAG/pgvector, agentic
   pipelines (LangGraph), OCR-based ingestion, FastAPI.
4. **Design, implementation, and evaluation** — overall architecture; ingestion
   pipeline; 6-node advisory graph; DB schema; chat UI; evaluation via
   edge-case compliance matrix and test suite.
5. **Solution and contribution** — conflict detection + LLM tiebreaker;
   resilient inference gateway with deterministic fallback; test DB isolation.
6. **Conclusion and future work.**

## Non-goals

- Writing actual thesis prose (separate, subsequent work).
- Installing a LaTeX toolchain.
- Modifying `latex-template/`.
