# Plan 05 — Appendix A: Use Case Descriptions

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Read the shared conventions in the plan index first.

**Goal:** Expand `latex/Chapter/Appendix_A.tex` from ~3 to **5–7 pages** by adding detailed scenarios for UC-02 / UC-03 / UC-05 and an edge-case → scenario mapping table, all grounded in `docs/edge-case.md`.

**Architecture:** Same precondition / user-action / required-behavior scenario format as the existing UC-01.x entries; add a traceability table linking the 25 edge cases to scenarios and their pass/partial/fail status.

**Tech Stack:** LaTeX `subfiles`; a `tabular` for the mapping table.

**Depends on:** Plan 00 (status counts come from re-verified `FACTS.md`).

---

### Task 1: Add UC-02 / UC-03 detailed scenarios

**Files:**
- Modify: `latex/Chapter/Appendix_A.tex` (after §A.3, currently ll. 47–62)

- [ ] **Step 1: Read sources first**

Read `services/knowledge/qa_service.py`, `services/knowledge/scope.py`, and `services/chat/compare_orchestrator.py` + `synthesis_agent.py` + `knowledge_fanout.py` to keep behavior exact.

- [ ] **Step 2: Add scenarios in the existing format**

- UC-02.3 — scoped retrieval with national-budget: a topic question where ministry chunks contribute alongside school chunks; required behavior names both retrieval scopes.
- UC-02.4 — pronoun-scoped question ("trường này") resolved from the collected profile, else a clarifying question.
- UC-03.1 — hybrid comparison fan-out: two schools × topics, per-school knowledge lookups, then a synthesis step merging factual + advisory evidence.
- UC-03.2 — factual-only hybrid: advisory path skipped when no admission-chance sub-question is present.

Each entry uses the `\textbf{UC-..} --- ...` + `\textit{Precondition/User action/Required behavior}` structure already in the file.

- [ ] **Step 3: Verify + commit**

Run: `Select-String -Path latex\Chapter\Appendix_A.tex -Pattern 'UC-02.3|UC-03.1'`
```bash
git add latex/Chapter/Appendix_A.tex
git commit -m "docs(thesis): add UC-02/UC-03 detailed scenarios to Appendix A"
```

---

### Task 2: Add UC-05 ingestion scenarios

**Files:**
- Modify: `latex/Chapter/Appendix_A.tex`

- [ ] **Step 1: Read sources first**

Read `ingestion/pipeline/ingestion_pipeline.py` and `storage/db_writer.py` for the per-source / per-school / per-URL variants and the scanned-PDF alternative flow.

- [ ] **Step 2: Add a new section §A.5 with scenarios**

- UC-05.1 — ingest all sources of one school; required behavior: normalized records persisted with provenance, one row per source.
- UC-05.2 — scanned-PDF source: OCR recovers text, degenerate output detected and retried, one bad page isolated.
- UC-05.3 — no extractable facts: run completes with a warning, writes nothing.

- [ ] **Step 3: Verify + commit**

```bash
git add latex/Chapter/Appendix_A.tex
git commit -m "docs(thesis): add UC-05 ingestion scenarios to Appendix A"
```

---

### Task 3: Add the edge-case → scenario mapping table

**Files:**
- Modify: `latex/Chapter/Appendix_A.tex`
- Read: `docs/edge-case.md`, `latex/FACTS.md` (status counts)

- [ ] **Step 1: Build the table**

Add a `tabular` (new §A.6) with columns: Edge case (EC-01..EC-25), Short description, Appendix scenario / UC, Status (Satisfied / Partial / Not yet). Populate Status from the re-verified `FACTS.md` edge-case section (currently 17 / 4 / 4). The table is long; split across pages with `[H]`/`longtable` only if the existing preamble supports it — otherwise use two `tabular` blocks. (Do **not** add new packages; `longtable` is not in the preamble, so use plain `tabular` split into two.)

- [ ] **Step 2: Add a one-paragraph lead-in** explaining the table traces requirements to evaluation outcomes, and reference Section~\ref{section:4.4}.

- [ ] **Step 3: Verify + commit**

Run: `Select-String -Path latex\Chapter\Appendix_A.tex -Pattern 'EC-25'`
Expected: present (table complete through EC-25).
```bash
git add latex/Chapter/Appendix_A.tex
git commit -m "docs(thesis): add edge-case to scenario mapping table in Appendix A"
```

---

### Self-review (run before marking plan done)

- [ ] All 25 edge cases appear in the mapping table with a status matching `FACTS.md`.
- [ ] New scenarios match the real modules (no invented behavior).
- [ ] No new LaTeX packages introduced; `tabular` split used instead of `longtable`.
- [ ] Length in the 5–7 page range.
