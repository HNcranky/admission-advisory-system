# Plan 01 — Chapter 3: Theoretical Background & Technologies

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Read the shared conventions in the plan index first.

**Goal:** Expand `latex/Chapter/3_Methodology.tex` from ~7 to **13–15 pages** of cited theory, keeping the existing structure and each "requirement + alternative" mapping.

**Architecture:** Deepen each of the five sections with academic theory and citations from Plan 00. No code/algorithms here (those live in Ch4/Ch5); this chapter is conceptual background.

**Tech Stack:** LaTeX (`subfiles`), biblatex IEEE, `glossary`.

**Depends on:** Plan 00 (references `ouyang2022instruct`, `wei2022cot`, `reimers2019sbert`, `karpukhin2020dpr`, `malkov2020hnsw`, `gao2023ragsurvey`, `yao2023react`, `ji2023hallucination` must exist).

---

### Task 1: Expand §3.1 — LLMs and structured output

**Files:**
- Modify: `latex/Chapter/3_Methodology.tex` (§3.1, currently ll. 11–28)

- [ ] **Step 1: Read sources first**

Read `services/inference/gateway.py`, `services/inference/models.py` (the `failure_type` / `STRUCTURE_FAILURE` field), and `services/inference/providers/gemini_provider.py` to keep claims accurate.

- [ ] **Step 2: Add content (keep existing paragraphs, insert deeper material)**

Add, as new one-sentence-per-line prose:
- A paragraph on the Transformer self-attention mechanism (keep `\cite{vaswani2017attention}`) explaining why attention enables long-range conditioning.
- A paragraph on in-context learning (keep `\cite{brown2020fewshot}`) and **instruction tuning** as why instruction-only prompting works at all — cite `\cite{ouyang2022instruct}`.
- A short prompting taxonomy: role/instruction prompting, few-shot exemplars, and chain-of-thought for multi-step reasoning — cite `\cite{wei2022cot}`; tie each to a concrete system step (intent classification, conflict tie-break, explanation).
- A paragraph motivating **grounding**: bare LLMs hallucinate facts they were not given — cite `\cite{ji2023hallucination}` — which is the academic justification for the RAG approach in §3.2 and the structured-output safeguards.
- Keep and slightly expand the existing `failure_type` / `STRUCTURE_FAILURE` paragraph; forward-reference §5.2.

- [ ] **Step 3: Verify**

Run: `Select-String -Path latex\Chapter\3_Methodology.tex -Pattern '\\cite\{(ouyang2022instruct|wei2022cot|ji2023hallucination)\}'`
Expected: all three new keys appear and exist in `reference.bib`.

- [ ] **Step 4: Commit**

```bash
git add latex/Chapter/3_Methodology.tex
git commit -m "docs(thesis): deepen Ch3.1 LLM background with cited theory"
```

---

### Task 2: Expand §3.2 — RAG and vector search

**Files:**
- Modify: `latex/Chapter/3_Methodology.tex` (§3.2, currently ll. 30–47)

- [ ] **Step 1: Read sources first**

Read `services/knowledge/retrieval_query.py` (the cosine-distance `<=>` query, similarity conversion), `services/knowledge/db.py` / `db/migrations/013_*`, `db/migrations/017_knowledge_chunk_doc_index.sql`, and `services/inference/embedder.py` (embedding task types, dimension 768).

- [ ] **Step 2: Add content**

- A paragraph on embeddings: dense vector representations where semantic similarity ≈ geometric proximity — cite `\cite{reimers2019sbert}`; mention dense passage retrieval as the retrieval-QA lineage — cite `\cite{karpukhin2020dpr}`.
- A paragraph defining cosine distance/similarity formally (a single inline equation is acceptable) and tying it to the real `embedding <=> query` operator.
- A paragraph on approximate nearest neighbor search and the **HNSW** index pgvector uses — cite `\cite{malkov2020hnsw}` and define `\gls{ANN}` on first use; explain the exact-vs-approximate trade-off at the system's scale.
- Keep `\cite{lewis2020rag}` for the RAG pattern and add the survey `\cite{gao2023ragsurvey}` for the design-space framing.
- Keep the existing pgvector-vs-dedicated-store rationale (cite `\cite{pgvector}`, `\cite{postgresql}`); tie to NFR-02.

- [ ] **Step 3: Verify**

Run: `Select-String -Path latex\Chapter\3_Methodology.tex -Pattern '\\(cite|gls)\{(reimers2019sbert|karpukhin2020dpr|malkov2020hnsw|gao2023ragsurvey|ANN)\}'`
Expected: each key present and defined.

- [ ] **Step 4: Commit**

```bash
git add latex/Chapter/3_Methodology.tex
git commit -m "docs(thesis): deepen Ch3.2 RAG/vector-search with embedding+HNSW theory"
```

---

### Task 3: Expand §3.3 — Agentic pipelines

**Files:**
- Modify: `latex/Chapter/3_Methodology.tex` (§3.3, currently ll. 49–64)

- [ ] **Step 1: Read sources first**

Read `graph.py` (42 lines — the fixed linear graph) and `state.py` (`AgentState`) to keep the six-node description exact.

- [ ] **Step 2: Add content**

- A paragraph framing the agent-design spectrum: autonomous tool-use/function-calling loops at one end, structured state graphs at the other — keep `\cite{wang2024agentsurvey}`.
- A paragraph naming the concrete alternative, a **ReAct**-style reason-act loop — cite `\cite{yao2023react}` — and why its run-time-decided control flow is a poor fit for a system that must be reproducible and traceable.
- Keep and sharpen the three-reason justification (determinism, traceability, separation of concerns) mapping to UC-04/NFR-01/NFR-02/NFR-05; keep `\cite{langgraph}`, `\cite{langgraph_docs}`.

- [ ] **Step 3: Verify**

Run: `Select-String -Path latex\Chapter\3_Methodology.tex -Pattern '\\cite\{yao2023react\}'`
Expected: present and in `reference.bib`.

- [ ] **Step 4: Commit**

```bash
git add latex/Chapter/3_Methodology.tex
git commit -m "docs(thesis): deepen Ch3.3 agentic-pipeline rationale with ReAct alternative"
```

---

### Task 4: Expand §3.4 (document processing) and §3.5 (web stack)

**Files:**
- Modify: `latex/Chapter/3_Methodology.tex` (§3.4 ll. 66–80, §3.5 ll. 82–92)

- [ ] **Step 1: Read sources first**

For §3.4 read the OCR path in `ingestion/` (the page-rendering + transcription + degenerate-output detection code). For §3.5 read `web/app.py` and `services/chat/run_dispatcher.py` + `run_queue_worker.py`.

- [ ] **Step 2: Add content**

- §3.4: add a citation-backed framing of OCR and of model-based-transcription as a multimodal task (keep `\cite{geminiteam2023}`, `\cite{pdfplumber}`, `\cite{pymupdf}`); briefly characterize the repetition-loop failure mode and forward-reference §5.3 (do not give the algorithm here).
- §3.5: add a short paragraph on the ASGI/async model and on the concurrency choice (thread-pool / run-queue worker vs a full broker-backed task queue) tied to NFR-04; keep `\cite{fastapi}`, `\cite{uvicorn}`, `\cite{jinja2}`, `\cite{pydantic}`. **Correct any claim that says only `ThreadPoolExecutor`** if the re-verified `FACTS.md` shows the run-queue worker is the active dispatch path.

- [ ] **Step 3: Verify**

Run the shared refs/cites/gls check on the file; confirm no `\cite` key is undefined.

- [ ] **Step 4: Update the chapter summary paragraph**

Adjust the closing summary (currently ll. 94–95) so it reflects the added theory; keep it one prose paragraph.

- [ ] **Step 5: Commit**

```bash
git add latex/Chapter/3_Methodology.tex
git commit -m "docs(thesis): deepen Ch3.4/3.5 document-processing and web-stack background"
```

---

### Self-review (run before marking plan done)

- [ ] Each of §3.1–3.5 maps to a Ch2 requirement and names an alternative (chapter rule).
- [ ] Every new `\cite`/`\gls` key resolves (run the index's verification loop on the whole file).
- [ ] Section reads as background, not implementation — no algorithms/listings leaked in from Ch4/Ch5.
- [ ] No `% TODO:`/placeholder prose; any unverifiable claim tagged `% TODO-VERIFY`.
- [ ] Length is in the 13–15 page range by content, not padding.
