# Plan 06 — Chapter 6 Tightening & Whole-Thesis Final Pass

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Read the shared conventions in the plan index first.

**Goal:** Lightly expand `latex/Chapter/6_Conclusion.tex`, then run the whole-thesis verification gate so every cross-reference resolves, every `TODO-VERIFY` is cleared, and the page target is met.

**Architecture:** Conclusion is short by design — minor depth only. The bulk of this plan is the final structural verification across all chapters.

**Tech Stack:** LaTeX; PowerShell `Select-String` checks; Git.

**Depends on:** Plans 01–05 complete.

---

### Task 1: Tighten Chapter 6

**Files:**
- Modify: `latex/Chapter/6_Conclusion.tex` (currently 39 lines)

- [ ] **Step 1: Read sources first**

Re-read the final §4.4 evaluation outcome and §5.x results so the conclusion claims nothing beyond Chapters 4/5.

- [ ] **Step 2: Add modest depth**

- §6.1: keep the achieved-vs-limits framing; align the numbers (LOC, tests) with the re-verified `FACTS.md`.
- §6.2 future work: keep the three directions; add one grounded sentence to the "structured preferences" cluster naming the exact edge cases (EC-07/08/11/19/20/25) and the flat-field root cause from `FACTS.md`.

- [ ] **Step 3: Verify + commit**

Run the shared refs/cites/gls check on the file.
```bash
git add latex/Chapter/6_Conclusion.tex
git commit -m "docs(thesis): align Ch6 conclusion with re-verified results"
```

---

### Task 2: Resolve all TODO-VERIFY tags

**Files:**
- Modify: any `latex/Chapter/*.tex` carrying `% TODO-VERIFY`

- [ ] **Step 1: Find them**

Run: `Select-String -Path latex\Chapter\*.tex -Pattern 'TODO-VERIFY'`

- [ ] **Step 2: Resolve each**

For each tag, run the command in the tag (re-measure with Docker DB up if the tag needed it) and replace the value with the measured number, then delete the tag. If a value is genuinely unobtainable, escalate to the user rather than guessing.

- [ ] **Step 3: Verify**

Run: `Select-String -Path latex\Chapter\*.tex -Pattern 'TODO-VERIFY'`
Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add latex/Chapter/*.tex latex/FACTS.md
git commit -m "docs(thesis): resolve all TODO-VERIFY facts"
```

---

### Task 3: Whole-thesis cross-reference and citation audit

**Files:**
- Read-only audit across `latex/`

- [ ] **Step 1: Collect every reference target**

Run: `Select-String -Path latex\Chapter\*.tex -Pattern '\\(ref|cite|gls)\{[^}]+\}' -AllMatches`

- [ ] **Step 2: Confirm each resolves**
- Every `\cite{key}` → `key` exists in `reference.bib`.
- Every `\gls{KEY}` → `KEY` exists in `glossary.tex`.
- Every `\ref{...}` → a matching `\label{...}` exists (section/figure/table/algorithm/listing).
- Every `\label` for a figure/table/algorithm/listing is referenced at least once in prose.

- [ ] **Step 3: Confirm no orphan placeholders**

Run: `Select-String -Path latex\Chapter\*.tex -Pattern 'XXX|FIXME|lorem'`
Expected: none. The only allowed `% TODO:` is the §4.2 second-screenshot note.

- [ ] **Step 4: Confirm scope of the diff**

Run: `git diff --name-only main -- latex/`
Expected: only `Chapter/2..6`, `Appendix_A`, `reference.bib`, `glossary.tex`, `FACTS.md` (plus `Chapter/1` untouched). No `main.tex`/preamble/template changes.

- [ ] **Step 5: Commit any fixes**

```bash
git add latex/
git commit -m "docs(thesis): final cross-reference and citation audit fixes"
```

---

### Task 4: Page-target confirmation

- [ ] **Step 1: Author compiles on Prism** (no local LaTeX toolchain). Ask the author to compile `latex/main.tex` and report the body page count.

- [ ] **Step 2: Judge against target**

If the body is below 60 pages, identify the thinnest section from Plans 01–05 and add grounded depth there (prefer more algorithm detail or an additional cited paragraph) — never padding. If at 65–75, done.

- [ ] **Step 3: Final commit (if changes were needed)**

```bash
git add latex/
git commit -m "docs(thesis): final length adjustment to meet page target"
```

---

### Self-review (final acceptance — whole thesis)

- [ ] Body page count in the 65–75 range (≥ 60 hard floor), content-judged.
- [ ] `Select-String -Path latex\Chapter\*.tex -Pattern 'TODO-VERIFY'` → empty.
- [ ] Every `\cite`/`\gls`/`\ref` resolves; every float is referenced.
- [ ] `git diff` against `main` touches only in-scope files.
- [ ] Every new `reference.bib` entry is a web-verified real source.
- [ ] Each chapter retains its Overview + Summary paragraphs; English/first-person throughout.
