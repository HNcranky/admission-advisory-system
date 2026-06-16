# Plan 00 — Facts Re-verification & References Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Refresh every measured number the thesis cites, reconcile architecture drift, and grow `reference.bib` + `glossary.tex` so all chapter plans build on accurate facts and a complete citation base.

**Architecture:** Pure measurement + documentation task. Re-run the commands recorded in `latex/FACTS.md` on the current branch, update the file, then web-search and add verified academic/official references.

**Tech Stack:** Git Bash / PowerShell for measurement, Docker Postgres for store counts, WebSearch/WebFetch for reference verification.

**Hard prerequisite for:** Plans 01–06.

---

### Task 1: Re-measure codebase size and migrations

**Files:**
- Modify: `latex/FACTS.md`

- [ ] **Step 1: Define the check (what "correct" looks like)**

The "Codebase size" and "Database migrations" sections of `latex/FACTS.md` must match the current branch. Known drift already observed: migrations are now **19 files (`001`–`018`)**, not 16; `services/chat/run_queue_worker.py` and `db/migrations/018_advisory_run_queue.sql` exist (the dispatch model now includes a run-queue worker, which the thesis currently describes only as a `ThreadPoolExecutor`).

- [ ] **Step 2: Run the measurements**

```bash
# Python LOC + file counts (tracked files only)
git ls-files '*.py' | xargs wc -l | tail -1
git ls-files '*.py' | wc -l
# Per-layer LOC
for d in ingestion services db agents web scripts; do echo -n "$d "; git ls-files "$d/*.py" | xargs wc -l 2>/dev/null | tail -1; done
git ls-files 'tests/*.py' | xargs wc -l | tail -1
# Migrations
ls db/migrations/*.sql | wc -l
ls db/migrations/*.sql
# Commits on branch
git rev-list --count HEAD
```

- [ ] **Step 3: Update `latex/FACTS.md`**

Replace the "Codebase size" table values and the "Database migrations" section with the measured values. Update the header date line to `All measurements taken 2026-06-16 on branch refactor/codebase unless noted.` Note the new migrations `017_knowledge_chunk_doc_index`, `018_advisory_run_queue` in the table list.

- [ ] **Step 4: Verify**

Run: `Select-String -Path latex\FACTS.md -Pattern '16 migrations|001.{1,4}016'`
Expected: no stale "16 migrations" / "001–016" claims remain.

- [ ] **Step 5: Commit**

```bash
git add latex/FACTS.md
git commit -m "docs(thesis): re-measure codebase size and migrations for FACTS"
```

---

### Task 2: Re-measure test suite and data-store counts

**Files:**
- Modify: `latex/FACTS.md`

- [ ] **Step 1: Run test collection**

```bash
python -m pytest --collect-only -q 2>&1 | tail -3
git ls-files 'tests/*.py' | grep -c test_
```

- [ ] **Step 2: (If Docker DB available) run full suite + store counts**

```bash
docker compose up -d --wait db
python -m pytest -q 2>&1 | tail -5    # passed/failed/skipped + duration
docker exec advisory-db psql -U postgres -d admission -c "SELECT school_id, COUNT(*) FROM canonical_admission_records GROUP BY school_id;"
docker exec advisory-db psql -U postgres -d admission -c "SELECT school_id, COUNT(*) FROM cutoff_records GROUP BY school_id;"
docker exec advisory-db psql -U postgres -d admission -c "SELECT COUNT(*) FROM program_catalog_embeddings;"
docker exec advisory-db psql -U postgres -d admission -c "SELECT COUNT(*) FROM knowledge_documents;"
docker exec advisory-db psql -U postgres -d admission -c "SELECT COUNT(*) FROM knowledge_chunks;"
```

- [ ] **Step 3: Update `latex/FACTS.md`**

Update the "Test suite" and "Canonical store contents" sections with measured values. If the Docker DB is **not** available in this environment, do **not** guess: keep the prior values but annotate each store-count line `<!-- TODO-VERIFY 2026-06-16: re-run psql when dev DB is up -->`, and the chapter plans will carry `% TODO-VERIFY` for those specific numbers.

- [ ] **Step 4: Verify**

Run: `Select-String -Path latex\FACTS.md -Pattern '2026-06-08'`
Expected: only intentional historical-baseline references remain; current measurements are dated 2026-06-16.

- [ ] **Step 5: Commit**

```bash
git add latex/FACTS.md
git commit -m "docs(thesis): re-measure test suite and store counts for FACTS"
```

---

### Task 3: Verify and add academic references

**Files:**
- Modify: `latex/reference.bib`

- [ ] **Step 1: Web-verify each candidate source**

For each candidate below, use WebSearch/WebFetch to confirm the title, authors, venue, and year before adding. Add an entry **only** if a chapter plan cites it. Do not invent DOIs.

| Intended cite key | Source (verify exact metadata) | Used by |
|---|---|---|
| `ouyang2022instruct` | Ouyang et al., "Training language models to follow instructions with human feedback", NeurIPS 2022 | Ch3 §3.1 |
| `wei2022cot` | Wei et al., "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models", NeurIPS 2022 | Ch3 §3.1 |
| `reimers2019sbert` | Reimers & Gurevych, "Sentence-BERT", EMNLP 2019 | Ch3 §3.2 |
| `karpukhin2020dpr` | Karpukhin et al., "Dense Passage Retrieval for Open-Domain QA", EMNLP 2020 | Ch3 §3.2 |
| `malkov2020hnsw` | Malkov & Yashunin, "Efficient and robust approximate nearest neighbor search using HNSW graphs", IEEE TPAMI 2020 | Ch3 §3.2 |
| `gao2023ragsurvey` | Gao et al., "Retrieval-Augmented Generation for Large Language Models: A Survey", arXiv 2023 | Ch3 §3.2 |
| `yao2023react` | Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models", ICLR 2023 | Ch3 §3.3 |
| `ji2023hallucination` | Ji et al., "Survey of Hallucination in Natural Language Generation", ACM Computing Surveys 2023 | Ch3 §3.1, Ch2 §2.1 |
| `li2016truth` | Li et al., "A Survey on Truth Discovery", ACM SIGKDD Explorations 2016 | Ch5 §5.1 |

- [ ] **Step 2: Add verified entries to `reference.bib`**

Append each verified entry in the existing biblatex format (match the indentation and field order of the current `@inproceedings`/`@article`/`@misc` entries). Group under the existing `% ---------- Academic ----------` heading. Example shape (fill with **verified** metadata only):

```bibtex
@inproceedings{wei2022cot,
  author    = {Wei, Jason and Wang, Xuezhi and Schuurmans, Dale and
               Bosma, Maarten and Ichter, Brian and Xia, Fei and
               Chi, Ed H. and Le, Quoc V. and Zhou, Denny},
  title     = {Chain-of-Thought Prompting Elicits Reasoning in Large Language Models},
  booktitle = {Advances in Neural Information Processing Systems},
  volume    = {35},
  year      = {2022}
}
```

- [ ] **Step 3: Verify formatting**

Run: `Select-String -Path latex\reference.bib -Pattern '@(article|inproceedings|misc)\{' | Measure-Object`
Expected: count increased by the number of added entries; no entry has empty required fields.

- [ ] **Step 4: Commit**

```bash
git add latex/reference.bib
git commit -m "docs(thesis): add verified academic references for Ch2/3/5"
```

---

### Task 4: Add glossary entries for new acronyms

**Files:**
- Modify: `latex/glossary.tex`

- [ ] **Step 1: Identify gaps**

Run: `Select-String -Path latex\glossary.tex -Pattern 'newglossaryentry\{(\w+)\}'`
Confirm whether `ANN` (approximate nearest neighbor) and `DPR` (dense passage retrieval) exist. `HNSW`, `API`, `JSON`, `RAG`, `LLM`, `OCR` already exist — do not duplicate.

- [ ] **Step 2: Add only the missing entries**

For each acronym a chapter plan introduces but `glossary.tex` lacks, add a `\newglossaryentry` matching the existing format, e.g.:

```latex
\newglossaryentry{ANN}{name={ANN},description={Approximate Nearest Neighbor}}
```

- [ ] **Step 3: Verify**

Run: `Select-String -Path latex\glossary.tex -Pattern 'newglossaryentry' | Measure-Object`
Expected: count increased only by genuinely new acronyms.

- [ ] **Step 4: Commit**

```bash
git add latex/glossary.tex
git commit -m "docs(thesis): add glossary entries for new acronyms"
```

---

### Self-review (run before marking plan done)

- [ ] `FACTS.md` header dated 2026-06-16; migration count = actual on-disk count; no "16 migrations" left.
- [ ] Architecture drift (run-queue worker) noted in `FACTS.md` so Ch4 can describe it accurately.
- [ ] Every added `reference.bib` entry was web-verified; no invented metadata.
- [ ] `glossary.tex` has no duplicate acronyms.
