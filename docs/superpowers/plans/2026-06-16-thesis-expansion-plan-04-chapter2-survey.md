# Plan 04 — Chapter 2: Requirement Survey and Analysis

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Read the shared conventions in the plan index first.

**Goal:** Expand `latex/Chapter/2_Survey.tex` from ~10 to **12–14 pages**, mainly by grounding the §2.1 status survey in cited literature and deepening the non-functional rationale, without touching the use-case figures.

**Architecture:** Add an academic backdrop to the product-centric survey, add per-requirement justification tied to real code/config. Keep all existing tables and figures.

**Tech Stack:** LaTeX `subfiles`, biblatex IEEE, `glossary`.

**Depends on:** Plan 00 (`ji2023hallucination`), Plan 01 (reuse Ch3 citations consistently).

---

### Task 1: Add an academic backdrop to §2.1

**Files:**
- Modify: `latex/Chapter/2_Survey.tex` (§2.1, currently ll. 12–63)

- [ ] **Step 1: Read sources first**

Re-read `docs/admission-advisory-conversational-architecture.md` and `docs/happy-path.md` to keep the gap analysis grounded in the project's own framing.

- [ ] **Step 2: Add content (keep all five channels + the comparison table)**

- Add one paragraph positioning the work against the academic literature on conversational agents / chatbots in education and grounded question answering, so the three recurring gaps rest on more than product names. Cite the existing `\cite{rasa_calm}`, `\cite{dialogflow}`, `\cite{element451}`, `\cite{mainstay}` for products and add `\cite{ji2023hallucination}` to substantiate the "generic chatbots fabricate numbers" claim.
- Keep Table `table:channel-comparison` unchanged unless a new row is fully truthful.
- Keep the three-gaps closing paragraph; sharpen each gap with one extra grounded sentence.

- [ ] **Step 3: Verify + commit**

Run: `Select-String -Path latex\Chapter\2_Survey.tex -Pattern '\\cite\{ji2023hallucination\}'`
Expected: present and in `reference.bib`.
```bash
git add latex/Chapter/2_Survey.tex
git commit -m "docs(thesis): add academic backdrop to Ch2.1 status survey"
```

---

### Task 2: Deepen §2.4 non-functional requirements

**Files:**
- Modify: `latex/Chapter/2_Survey.tex` (§2.4, currently ll. 308–337)

- [ ] **Step 1: Read sources first**

For each NFR find its enforcing code/config: NFR-01 `services/inference/gateway.py` + `intent_router.py`; NFR-02 per-source canonical uniqueness + idempotent migrations; NFR-03 anonymous session token in `services/chat/session_service.py`; NFR-04 `run_dispatcher.py`/`run_queue_worker.py`; NFR-05 `tests/conftest.py::_isolate_test_db`; NFR-06 `ADVISORY_FETCH_VERIFY_SSL` in the fetcher.

- [ ] **Step 2: Add content**

For each of the six NFRs, add one sentence naming the concrete mechanism that enforces it (quote the real module/flag in `\texttt{...}`). Do not add new NFRs unless codebase-grounded.

- [ ] **Step 3: Verify + commit**

Run the shared refs/cites/gls check on the file.
```bash
git add latex/Chapter/2_Survey.tex
git commit -m "docs(thesis): ground Ch2.4 non-functional requirements in real mechanisms"
```

---

### Task 3: Light depth in §2.2 / §2.3 and refresh summary

**Files:**
- Modify: `latex/Chapter/2_Survey.tex` (§2.2 ll. 65–148, §2.3 ll. 150–306, summary ll. 338–341)

- [ ] **Step 1: Add at most one grounded sentence of rationale per UC table (UC-01..UC-05)** where the codebase justifies it; do not bloat the tables. Keep all five figures.

- [ ] **Step 2: Update the closing chapter-summary paragraph** to reflect the added literature framing; keep it one prose paragraph that links forward to Ch3.

- [ ] **Step 3: Verify + commit**

Run the shared check.
```bash
git add latex/Chapter/2_Survey.tex
git commit -m "docs(thesis): light rationale depth and summary refresh in Ch2"
```

---

### Self-review (run before marking plan done)

- [ ] All five use-case figures and existing tables intact.
- [ ] Every NFR names a real enforcing mechanism.
- [ ] New `\cite` keys resolve; no padding paragraphs.
- [ ] Length in the 12–14 page range by content.
