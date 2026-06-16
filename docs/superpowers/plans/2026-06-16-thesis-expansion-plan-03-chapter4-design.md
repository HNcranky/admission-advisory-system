# Plan 03 — Chapter 4: Design, Implementation & Evaluation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Read the shared conventions in the plan index first.

**Goal:** Expand `latex/Chapter/4_Experiment_evaluation.tex` from ~15 to **18–21 pages** through design/implementation depth — code listings, two algorithms, and a fuller schema narrative — while keeping the evaluation sections (§4.4, edge-case matrix) essentially as-is.

**Architecture:** Add real short code excerpts (`listings`) and control-flow algorithms (`algorithm2e`) to the design sections; re-verify all numbers; do not add new evaluation experiments.

**Tech Stack:** LaTeX `listings` (configured in `lstlisting.tex`), `algorithm2e`, biblatex IEEE.

**Depends on:** Plan 00 (re-verified `FACTS.md`, including run-queue worker drift).

---

### Task 1: §4.1 — architecture depth + graph-wiring listing

**Files:**
- Modify: `latex/Chapter/4_Experiment_evaluation.tex` (§4.1, currently ll. 10–64)

- [ ] **Step 1: Read sources first**

Read `graph.py` (full 42 lines), `state.py`, and one `agents/*.py` node (e.g., `agents/reasoning_agent.py`) and the tracing wrapper in `services/tracing/`.

- [ ] **Step 2: Add a code listing of the graph wiring**

Insert a short `lstlisting` excerpt (≤ ~20 lines) copied from `graph.py` showing node registration and the fixed linear edges, introduced by path and explained in one paragraph (how the fixed edges give determinism + per-node tracing).

```latex
\begin{lstlisting}[language=Python,caption={Advisory pipeline wiring in \texttt{graph.py}},label=lst:graph]
# excerpt copied verbatim from graph.py
\end{lstlisting}
```

Reference `\ref{lst:graph}` in prose.

- [ ] **Step 3: Deepen the detailed-package narrative**

Expand the three core-package paragraphs (advisory pipeline, inference gateway, ingestion) with one extra grounded sentence each (e.g., what `state.py::AgentState` carries; the `registry.py` per-agent policy fields). Keep figures `fig:package-overview`, `fig:advisory-graph`.

- [ ] **Step 4: Verify + commit**

Run the shared refs/cites/gls check; confirm `lst:graph` resolves.
```bash
git add latex/Chapter/4_Experiment_evaluation.tex
git commit -m "docs(thesis): add graph-wiring listing and package depth to Ch4.1"
```

---

### Task 2: §4.2 — dispatch + retrieval algorithms and `_cursor` listing

**Files:**
- Modify: `latex/Chapter/4_Experiment_evaluation.tex` (§4.2, currently ll. 66–139)

- [ ] **Step 1: Read sources first**

Read `web/app.py` (message endpoint), `services/chat/run_dispatcher.py`, `services/chat/run_queue_worker.py`, `services/chat/advisory_runner.py`, `services/knowledge/qa_service.py`, `services/knowledge/scope.py`, and one repository for the `_cursor` context manager (e.g., `services/chat/repository.py`).

- [ ] **Step 2: Add the advisory-dispatch algorithm**

Insert an `algorithm2e` block tracing: endpoint creates run record → submits to background executor / run-queue worker → returns immediately (NFR-04) → worker marks running, drives LangGraph, persists answer + per-stage trace → browser polls. Use the **actual** dispatch path verified in Plan 00 (run-queue worker, not only ThreadPoolExecutor).

```latex
\begin{algorithm}[H]
\caption{Advisory run dispatch (non-blocking)}
\label{alg:dispatch}
\end{algorithm}
```

Keep `fig:seq-advisory`; reference `\ref{alg:dispatch}`.

- [ ] **Step 3: Add the scoped-retrieval algorithm**

Insert an `algorithm2e` block for knowledge retrieval: embed question → vector search scoped to school+topic (`scope.py`) → additionally retrieve national/ministry chunks with their own budget → confidence gate (below threshold ⇒ "no data", no model call) → else answer strictly from passages + resolve citations.

```latex
\begin{algorithm}[H]
\caption{Scoped knowledge retrieval with confidence gating}
\label{alg:retrieval}
\end{algorithm}
```

Keep `fig:seq-knowledge`; reference `\ref{alg:retrieval}`.

- [ ] **Step 4: Add the `_cursor` listing**

Insert a short `lstlisting` of the `_cursor` context manager (commit on success / rollback on exception / cleanup), copied from the real repository, supporting the NFR-05 paragraph (keep `\cite{psycopg}`).

```latex
\begin{lstlisting}[language=Python,caption={The \texttt{\_cursor} context manager guaranteeing commit/rollback/cleanup},label=lst:cursor]
\end{lstlisting}
```

Keep the existing §4.2 screenshot `% TODO:` as the one sanctioned placeholder.

- [ ] **Step 5: Verify + commit**

Run the shared check; confirm `alg:dispatch`, `alg:retrieval`, `lst:cursor` resolve.
```bash
git add latex/Chapter/4_Experiment_evaluation.tex
git commit -m "docs(thesis): add dispatch/retrieval algorithms and _cursor listing to Ch4.2"
```

---

### Task 3: §4.2.3 database design + §4.3 achievement (re-verified numbers)

**Files:**
- Modify: `latex/Chapter/4_Experiment_evaluation.tex` (§4.2.3 ll. 123–139, §4.3 ll. 141–233)

- [ ] **Step 1: Read sources first**

List `db/migrations/*.sql` and read the headers of `015`–`018` to describe the four schema areas accurately, including `017_knowledge_chunk_doc_index` and `018_advisory_run_queue`.

- [ ] **Step 2: Update migration count + ERD narrative**

Change "sixteen ... migrations (001--016)" to the **re-verified count** (19, `001`–`018`) everywhere it appears in this chapter. Add the run-queue table to the chat/tracing area description. Keep `fig:erd`.

- [ ] **Step 3: Update achievement tables with re-verified values**

Update Table `table:achievement` and `table:libraries` and the prose in §4.3.2 with the re-verified `FACTS.md` numbers (LOC, files, tests, migrations, store counts, library versions). Any number the DB could not produce in Plan 00 gets `% TODO-VERIFY` on its line.

- [ ] **Step 4: Verify + commit**

Run: `Select-String -Path latex\Chapter\4_Experiment_evaluation.tex -Pattern 'sixteen|001--016'`
Expected: none remain.
```bash
git add latex/Chapter/4_Experiment_evaluation.tex
git commit -m "docs(thesis): re-verify Ch4 schema count and achievement figures"
```

---

### Task 4: §4.4–4.5 — light refresh only

**Files:**
- Modify: `latex/Chapter/4_Experiment_evaluation.tex` (§4.4 ll. 235–271, §4.5 ll. 273–282)

- [ ] **Step 1: Update test counts/timing**

Refresh the test count, pass/fail/skip, and runtime from Plan 00's `FACTS.md`. Keep the edge-case matrix table and its 17/4/4 framing unless the re-run changed it (if it did, update counts and tag the source date). **Do not** add new evaluation experiments (out of scope per D3).

- [ ] **Step 2: Optional deployment listing**

If accurate, add a tiny `lstlisting` of the one-command setup sequence (`docker compose up -d --wait db` → `python -m db.setup_db`) from `QUICKSTART.md`. Skip if it would duplicate prose.

- [ ] **Step 3: Update the chapter summary paragraph** to reflect the refreshed numbers.

- [ ] **Step 4: Verify + commit**

```bash
git add latex/Chapter/4_Experiment_evaluation.tex
git commit -m "docs(thesis): refresh Ch4 testing/deployment figures"
```

---

### Self-review (run before marking plan done)

- [ ] Every listing is a real excerpt copied from the named module; every algorithm matches the real flow.
- [ ] No number contradicts the re-verified `FACTS.md`; "sixteen migrations" fully removed.
- [ ] Evaluation sections unchanged except number refresh (D3 respected).
- [ ] All `lst:*`/`alg:*`/`fig:*`/`cite` references resolve.
- [ ] Length in the 18–21 page range by content.
