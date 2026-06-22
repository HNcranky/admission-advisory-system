# Thesis Expansion — Plan Index

> **For agentic workers:** Each linked plan is self-contained and produces one verifiable deliverable (an expanded chapter, or the shared foundation). Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` per plan. Steps use checkbox (`- [ ]`) syntax.

**Source spec:** `docs/superpowers/specs/2026-06-16-thesis-expansion-design.md`

**Goal:** Expand `latex/` Chapters 2–6 + Appendix A from ~45–50 to **65–75 body pages**, add verified IEEE citations, without restructuring or padding.

**Why split:** Each chapter is an independent deliverable that can be drafted, verified, and committed on its own. Plan 00 is a hard prerequisite for all chapter plans (it fixes the numbers and the citation base every chapter depends on).

## Plans, in execution order

| # | Plan | Deliverable | Depends on |
|---|---|---|---|
| 00 | `...-plan-00-facts-and-references.md` | Re-verified `FACTS.md`; expanded `reference.bib` + `glossary.tex` | — |
| 01 | `...-plan-01-chapter3-background.md` | Ch3 expanded to 13–15 pp (citation backbone) | 00 |
| 02 | `...-plan-02-chapter5-contributions.md` | Ch5 expanded to 9–11 pp (algorithms) | 00, 01 |
| 03 | `...-plan-03-chapter4-design.md` | Ch4 expanded to 18–21 pp (design depth, listings) | 00 |
| 04 | `...-plan-04-chapter2-survey.md` | Ch2 expanded to 12–14 pp (literature) | 00, 01 |
| 05 | `...-plan-05-appendix-a.md` | Appendix A expanded to 5–7 pp (scenarios + mapping) | 00 |
| 06 | `...-plan-06-chapter6-and-final.md` | Ch6 tightened; whole-thesis final verification pass | 01–05 |

## Conventions shared by every plan (read once)

These adapt the writing-plans TDD loop to LaTeX prose. "Test" = a structural/grounding check, not pytest.

- **Grounding-first:** before writing any sentence about the system, **read the named source file(s)**. Quote real module paths in `\texttt{...}`. Never state a number not in the re-verified `FACTS.md`; if unmeasurable here, write the sentence and tag `% TODO-VERIFY: <command>`.
- **Style (from `latex/CLAUDE.md`):** English, American, first-person "I"; one sentence per source line; each chapter keeps its opening Overview and closing Summary paragraph; no hype/superlatives; Vietnamese proper nouns keep diacritics.
- **Citations:** `\cite{key}` where `key` exists in `reference.bib` after Plan 00. Every external-technology claim needs a citation. `\gls{KEY}` on first prose use of an acronym defined in `glossary.tex`.
- **Algorithms:** use the already-loaded `algorithm2e` (`\begin{algorithm}...\end{algorithm}`); every algorithm gets a `\caption{}`, a `\label{alg:...}`, and an in-text `\ref{}`.
- **Listings:** use the configured `listings` setup (`\begin{lstlisting}[language=Python,caption=...,label=lst:...]`); excerpts are copied from the real module and introduced by path; keep them short (≤ ~20 lines).
- **No new image figures.** Existing `latex/Figure/*.png` are reused. The one sanctioned `% TODO:` is the §4.2 second screenshot (needs a live Gemini run).

### Per-section verification loop (every writing task ends with this)

1. **Refs/cites/gls resolve** — run:
   ```powershell
   Select-String -Path latex\Chapter\<file>.tex -Pattern '\\(ref|cite|gls)\{[^}]+\}' -AllMatches
   ```
   Confirm every `\cite` key is in `reference.bib`, every `\gls` key is in `glossary.tex`, every `\ref` target is defined somewhere.
2. **No stray placeholders** — `Select-String -Path latex\Chapter\<file>.tex -Pattern 'XXX|FIXME'` returns nothing. (`% TODO-VERIFY` is allowed mid-project; `% TODO:` only for the sanctioned screenshot.)
3. **Commit** — `git add` the touched files, commit with no AI attribution (`latex/CLAUDE.md` rule), never `git push`.

## Final acceptance (checked in Plan 06)

- Combined body in the 65–75 page range (content-judged, not padded).
- `Select-String -Path latex\Chapter\*.tex -Pattern 'TODO-VERIFY'` → empty.
- Every `\cite`/`\gls`/`\ref` resolves across all chapters.
- `git diff` touches only in-scope files (`latex/Chapter/2..6`, `Appendix_A`, `reference.bib`, `glossary.tex`, `FACTS.md`).
- Every new `reference.bib` entry corresponds to a web-verified real source.
