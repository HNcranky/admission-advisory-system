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
