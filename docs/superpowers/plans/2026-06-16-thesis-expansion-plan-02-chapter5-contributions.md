# Plan 02 — Chapter 5: Solution and Contribution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Read the shared conventions in the plan index first.

**Goal:** Expand `latex/Chapter/5_Solution_contribution.tex` from ~5 to **9–11 pages** by adding `algorithm2e` algorithms grounded in the real services, plus deeper cited problem framing, keeping the problem → solution → result form.

**Architecture:** Three contributions, each gains one algorithm that mirrors the actual control flow of the named module. Algorithms are the primary page-growth lever; prose explains and references them.

**Tech Stack:** LaTeX `algorithm2e` (already loaded `[ruled,vlined]`), biblatex IEEE.

**Depends on:** Plan 00 (`li2016truth`, `ji2023hallucination`), Plan 01 (Ch3 background to cross-reference).

---

### Task 1: §5.1 — conflict-resolution algorithm + framing

**Files:**
- Modify: `latex/Chapter/5_Solution_contribution.tex` (§5.1, currently ll. 11–34)

- [ ] **Step 1: Read sources first**

Read `services/conflict/detection.py`, `services/conflict/resolution.py`, `services/conflict/comparison.py`, `services/conflict/keys.py`, and `agents/conflict_agent.py`. The algorithm must reflect what these actually do — do not write an idealized version.

- [ ] **Step 2: Add the algorithm**

Insert an `algorithm2e` block after the "Solution" paragraph capturing the real decision logic:
- group candidate records by the conflict key (program, year, method) — from `keys.py`;
- flag a conflict when ≥2 distinct values exist;
- **quota path:** deterministic compare on trust level then source confidence (`comparison.py`); only if non-decisive, consult the constrained LLM tie-breaker (`conflict_agent.py`), accept only on high confidence + known source;
- **cutoff path:** never pick a winner by model; test whether the disagreement is decision-changing for this student's score (different fit categories); if yes leave unresolved + mark uncertain + list all values, else reference most-trusted while still listing all.

```latex
\begin{algorithm}[H]
\caption{Conflict detection and resolution (per recommended program)}
\label{alg:conflict}
\KwIn{candidate records $R$ for a program; student score $s$}
\KwOut{resolved value or an uncertainty annotation}
% ... fill from the real modules read in Step 1 ...
\end{algorithm}
```

Fill the body from Step 1; add `\ref{alg:conflict}` in the prose.

- [ ] **Step 3: Deepen the framing**

Keep `\cite{bleiholder2009fusion}`; add `\cite{li2016truth}` (truth discovery) to frame why the system defers rather than always resolves. Keep cross-references to §4.2 (per-source storage) and EC-16/EC-17.

- [ ] **Step 4: Verify**

Run: `Select-String -Path latex\Chapter\5_Solution_contribution.tex -Pattern '\\(ref|label)\{alg:conflict\}|\\cite\{li2016truth\}'`
Expected: label defined, referenced once, citation present.

- [ ] **Step 5: Commit**

```bash
git add latex/Chapter/5_Solution_contribution.tex
git commit -m "docs(thesis): add conflict-resolution algorithm and framing to Ch5.1"
```

---

### Task 2: §5.2 — inference-gateway resilience algorithm

**Files:**
- Modify: `latex/Chapter/5_Solution_contribution.tex` (§5.2, currently ll. 36–58)

- [ ] **Step 1: Read sources first**

Read `services/inference/gateway.py` (retry budget, fallback model, when `InferenceError` is raised vs `STRUCTURE_FAILURE` returned), `services/inference/registry.py` (per-agent policy), and `services/chat/intent_router.py` (the deterministic keyword fallback, commit `c2ef582`).

- [ ] **Step 2: Add the algorithm**

Insert an `algorithm2e` block for the gateway's failure handling:
- hard failure (`InferenceError`: network/auth/rate-limit) → stop retrying this model, switch to configured fallback model; if none, re-raise so the call site degrades;
- structure failure (`STRUCTURE_FAILURE`) → retry within the per-agent budget, then fall back to secondary model;
- show the intent-router degradation: on gateway failure, classify by keyword priority (knowledge-topic keywords before advisory phrases; unrecognized → clarification).

```latex
\begin{algorithm}[H]
\caption{Inference gateway: hard- vs structure-failure handling}
\label{alg:gateway}
% ... fill from gateway.py + registry.py read in Step 1 ...
\end{algorithm}
```

Reference `\ref{alg:gateway}` in prose; keep the `c2ef582` commit reference.

- [ ] **Step 3: Verify**

Run: `Select-String -Path latex\Chapter\5_Solution_contribution.tex -Pattern '\\(ref|label)\{alg:gateway\}'`
Expected: label defined and referenced. Confirm prose still ties to NFR-01.

- [ ] **Step 4: Commit**

```bash
git add latex/Chapter/5_Solution_contribution.tex
git commit -m "docs(thesis): add inference-gateway resilience algorithm to Ch5.2"
```

---

### Task 3: §5.3 — degenerate-OCR detection algorithm

**Files:**
- Modify: `latex/Chapter/5_Solution_contribution.tex` (§5.3, currently ll. 60–80)

- [ ] **Step 1: Read sources first**

Read the OCR ingestion path (page render + transcription + degenerate-output detection + retry, commit `b41dd9f`). Find the exact thresholds: the absolute per-page character ceiling, the single-character dominance fraction, the minimum length gate. The algorithm must use the **real** constants, not invented ones; if a constant cannot be located, tag the line `% TODO-VERIFY: locate constant in <file>`.

- [ ] **Step 2: Add the algorithm**

Insert an `algorithm2e` block for hybrid per-page extraction + degeneracy detection:
- per page: if text layer long enough → use directly; else render to PNG (~200 dpi) and transcribe via the multimodal gateway;
- classify output degenerate if length > ceiling OR (one char dominates > fraction of non-whitespace AND length > minimum);
- on degenerate: retry once at raised temperature; if still degenerate → mark page failed, continue document; document with zero text → leave un-ingested.

```latex
\begin{algorithm}[H]
\caption{Hybrid per-page extraction with degenerate-OCR detection}
\label{alg:ocr}
% ... fill with real thresholds from the module read in Step 1 ...
\end{algorithm}
```

Reference `\ref{alg:ocr}`; keep the `b41dd9f` commit reference.

- [ ] **Step 3: Re-verify result numbers**

The result paragraph cites store counts (HUST/VNU-UET records, knowledge docs/chunks). Replace with the re-verified values from Plan 00's `FACTS.md`; if the DB was unavailable, tag those numbers `% TODO-VERIFY`.

- [ ] **Step 4: Verify**

Run the shared refs/cites/gls check; confirm `alg:ocr` resolves and no invented threshold remains untagged.

- [ ] **Step 5: Commit**

```bash
git add latex/Chapter/5_Solution_contribution.tex
git commit -m "docs(thesis): add degenerate-OCR detection algorithm to Ch5.3"
```

---

### Self-review (run before marking plan done)

- [ ] Each algorithm matches the real module read in its Step 1 (no idealized logic).
- [ ] No earlier-chapter material repeated — Ch4/Ch2 referenced, not restated (Ch5 rule).
- [ ] Every `alg:*` label is defined and referenced exactly; every new `\cite` resolves.
- [ ] Result paragraphs use re-verified numbers or carry `% TODO-VERIFY`.
- [ ] Length is in the 9–11 page range by content.
