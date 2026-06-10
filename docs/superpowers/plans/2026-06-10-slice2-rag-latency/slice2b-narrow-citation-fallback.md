# Slice 2b — Narrow Citation Fallback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the LLM names no/invalid `used_source_ids` but still produced a
grounded answer, cite only the single top-scored chunk instead of every
retrieved chunk.

**Architecture:** A one-line change in `KnowledgeQAService._resolve_citations`:
the empty-`selected` fallback becomes `chunks[:1]` (chunks are already
score-sorted, so `chunks[0]` is the highest-score chunk). Three existing tests
assert the old cite-all behavior and are updated.

**Tech Stack:** Python, pytest (in-memory fakes — no live DB needed).

**Spec:** `docs/superpowers/specs/2026-06-10-slice2-rag-latency-design.md` §2b

**Behavior note:** this changes *which* source surfaces on the fallback path, not
only the count. A national-scope chunk that wasn't top-scored can drop out of the
citations when the LLM names no ids — intended (a fallback must not attribute the
answer to up to 8 chunks the model never named).

---

### Task 1: Narrow the fallback to the top-scored chunk

**Files:**
- Modify: `services/knowledge/qa_service.py:139-140` (the `if not selected:` branch)
- Test: `tests/services/knowledge/test_qa_service.py`

- [ ] **Step 1: Tighten the fallback test (top-1, not all)**

In `tests/services/knowledge/test_qa_service.py`, rename and rewrite
`test_citations_fallback_to_all_chunks_when_used_ids_empty`:

```python
def test_citations_fallback_to_top_chunk_when_used_ids_empty():
    chunks = [_chunk("a", "http://uet/a", 0.9), _chunk("b", "http://uet/b", 0.8)]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "ans", "used_source_ids": []}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert len(res.citations) == 1
    assert res.citations[0].source_url == "http://uet/a"  # highest score
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_service.py::test_citations_fallback_to_top_chunk_when_used_ids_empty -v`
Expected: FAIL — current code returns 2 citations (cite-all).

- [ ] **Step 3: Make the one-line change**

In `services/knowledge/qa_service.py`, inside `_resolve_citations`, change:

```python
        if not selected:
            selected = list(chunks)  # deterministic fallback: cite every passed chunk
```

to:

```python
        if not selected:
            selected = chunks[:1]  # fallback: cite only the top-scored chunk
```

- [ ] **Step 4: Run it, verify it passes**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_service.py::test_citations_fallback_to_top_chunk_when_used_ids_empty -v`
Expected: PASS

- [ ] **Step 5: Fix the second affected test (`test_above_threshold...`)**

`test_above_threshold_returns_grounded_answer_with_confidence` sends no
`used_source_ids` (→ fallback). Update its final two lines:

```python
    assert len(gateway.calls) == 1
    # No used_source_ids → fallback cites only the top-scored chunk.
    assert len(res.citations) == 1
```

- [ ] **Step 6: Fix the national-surfacing test (name the source explicitly)**

`test_specific_school_query_also_pulls_national_chunks` relied on the cite-all
fallback to surface the national source. Decouple it from the fallback by having
the LLM name the national chunk (index 2 after the score-sorted merge: HUST 0.92,
national 0.80). Change its `parsed_data` and keep the assertion:

```python
    service = _service_with(repo, parsed_data={"answer": "...", "used_source_ids": [2]})
    res = service.answer("HUST xét tuyển thế nào", school="HUST", topic="admission_policy")
    # two retrievals: the school scope, then the national scope with its own budget
    assert [c["school"] for c in repo.calls] == ["HUST", NATIONAL_SCHOOL]
    assert repo.calls[1]["limit"] == KNOWLEDGE_QA_NATIONAL_TOP_K
    # the national source (cited explicitly by the LLM) is in the answer's citations
    assert "https://chinhphu/r.pdf" in {c.source_url for c in res.citations}
```

- [ ] **Step 7: Run the full qa_service test file**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_service.py -v`
Expected: PASS (including `test_citations_fallback_when_used_ids_invalid` and `test_low_score_national_chunks_are_dropped`, which already satisfy ≤1 / top-1).

- [ ] **Step 8: Commit**

```bash
git add services/knowledge/qa_service.py tests/services/knowledge/test_qa_service.py
git commit -m "feat(knowledge): cite only the top chunk when the LLM names no sources"
```
