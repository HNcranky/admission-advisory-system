# Slice 1 — Plan B: Run the national-scope search once per topic in fan-out

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The national-scope (Bộ GD&ĐT) augmentation vector search currently re-runs once per `(school, topic)` even though its result depends only on `topic`. Run it **once per distinct topic** in the fan-out and reuse across schools.

**Architecture:** Expose `KnowledgeQAService.national_chunks(query_vector, topic)` and let `answer()` accept a precomputed `national=` list. The fan-out precomputes national chunks per distinct topic and passes them in. When `national` is not supplied, `answer()` computes it itself (unchanged behavior for standalone callers).

**Tech Stack:** Python, pytest.

**Depends on:** Plan A (`query_vector` already plumbed). Spec §1c.

---

### Task 1: Extract `national_chunks()` and accept a precomputed `national=`

**Files:**
- Modify: `services/knowledge/qa_service.py:59,65-80` (and `answer()` signature)
- Test: `tests/services/knowledge/test_qa_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_answer_uses_supplied_national_without_research():
    from services.knowledge.models import KnowledgeChunk  # adjust import to the real chunk type

    class _Repo:
        def __init__(self):
            self.national_searches = 0
        def vector_search(self, embedding, school, topic, limit):
            from services.knowledge.scope import NATIONAL_SCHOOL
            if school == NATIONAL_SCHOOL:
                self.national_searches += 1
            return []

    repo = _Repo()
    service = KnowledgeQAService(chunk_repository=repo, embedder=object(), gateway=object())
    service.answer("q", school="VNU-UET", topic="tuition",
                   query_vector=[0.1], national=[])

    assert repo.national_searches == 0   # supplied national list → no national search
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_service.py::test_answer_uses_supplied_national_without_research -v`
Expected: FAIL — `answer()` got an unexpected keyword argument `national`.

- [ ] **Step 3: Write minimal implementation**

In `services/knowledge/qa_service.py`:

```python
    def answer(
        self,
        question: str,
        school: Optional[str],
        topic: Optional[str],
        conversation_context: str = "",
        query_vector=None,
        national=None,
    ) -> KnowledgeQAResult:
        embedding = query_vector if query_vector is not None else self.embed_query(question)
        chunks = self._chunk_repository.vector_search(
            embedding, school=school, topic=topic, limit=self._top_k
        )
        chunks = self._augment_with_national(embedding, school, topic, chunks, national=national)
        confidence = chunks[0].score if chunks else 0.0
        if not chunks or confidence < self._min_score:
            return KnowledgeQAResult(has_data=False, confidence=confidence)
        return self._generate(question, chunks, confidence, conversation_context)

    def national_chunks(self, query_vector, topic):
        """National-scope chunks for a topic, score-filtered. Query-independent of
        school, so the fan-out can compute this once per topic."""
        national = self._chunk_repository.vector_search(
            query_vector, school=NATIONAL_SCHOOL, topic=topic, limit=self._national_top_k,
        )
        return [c for c in national if c.score >= self._min_score]

    def _augment_with_national(self, embedding, school, topic, chunks, national=None):
        if school in (None, NATIONAL_SCHOOL):
            return chunks
        if national is None:
            national = self.national_chunks(embedding, topic)
        merged = list(chunks) + list(national)
        merged.sort(key=lambda c: c.score, reverse=True)
        return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_service.py::test_answer_uses_supplied_national_without_research -v`
Expected: PASS

- [ ] **Step 5: Regression run**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_service.py -q`
Expected: PASS (default `national=None` reproduces the old `_augment_with_national` exactly).

- [ ] **Step 6: Commit**

```bash
git add services/knowledge/qa_service.py tests/services/knowledge/test_qa_service.py
git commit -m "feat(knowledge): allow precomputed national chunks in QA answer"
```

---

### Task 2: Fan-out precomputes national chunks per distinct topic

**Files:**
- Modify: `services/chat/knowledge_fanout.py` (after the `query_vector` embed)
- Test: `tests/services/chat/test_knowledge_fanout.py`

- [ ] **Step 1: Write the failing test**

```python
class _NationalCountingQA(FakeKnowledgeQA):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.national_calls = []
    def embed_query(self, question):
        return [0.5]
    def national_chunks(self, query_vector, topic):
        self.national_calls.append(topic)
        return []
    def answer(self, question, school, topic, conversation_context="", query_vector=None, national=None):
        return super().answer(question, school, topic, conversation_context)


def test_fanout_computes_national_once_per_topic():
    qa = _NationalCountingQA()
    intent = IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"])
    run_knowledge_fanout(qa, intent, "so sánh học phí", school_fallback=None)
    # 2 schools × 1 topic = 2 answer() calls, but national computed once for "tuition"
    assert qa.national_calls == ["tuition"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_fanout.py::test_fanout_computes_national_once_per_topic -v`
Expected: FAIL — `national_calls` is empty (fan-out never calls `national_chunks`).

- [ ] **Step 3: Write minimal implementation**

In `run_knowledge_fanout`, after computing `query_vector`, precompute national per distinct topic and pass it through:

```python
    # Precompute national-scope chunks once per distinct topic (query-independent
    # of school). Skipped when the embed failed (query_vector is None).
    national_by_topic = {}
    if query_vector is not None:
        for topic in {t for _, t in tasks}:
            try:
                national_by_topic[topic] = knowledge_qa.national_chunks(query_vector, topic)
            except Exception as exc:
                logger.warning("national precompute failed for topic=%r: %r", topic, exc)

    def _answer_one(task):
        school, topic = task
        try:
            return knowledge_qa.answer(
                question=content, school=school, topic=topic,
                conversation_context=conversation_context,
                query_vector=query_vector,
                national=national_by_topic.get(topic),
            )
        except Exception as exc:
            logger.warning(
                "knowledge fan-out failed for school=%r topic=%r: %r", school, topic, exc
            )
            return None
```

> NOTE: update the base `FakeKnowledgeQA.answer` signature in this test file to accept `national=None` as well, so other tests keep passing:
> `def answer(self, question, school, topic, conversation_context="", query_vector=None, national=None):`

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_fanout.py::test_fanout_computes_national_once_per_topic -v`
Expected: PASS

- [ ] **Step 5: Full suite for both modules**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_fanout.py tests/services/knowledge/test_qa_service.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/chat/knowledge_fanout.py tests/services/chat/test_knowledge_fanout.py
git commit -m "feat(chat): compute national-scope chunks once per topic in fan-out"
```

---

## Self-review notes

- `national=None` default preserves single-call behavior for `conversation_service._handle_knowledge_qa`.
- National precompute only runs when `query_vector` succeeded; otherwise each `answer()` self-serves (unchanged degraded path).
- A school-only query (`school in (None, NATIONAL_SCHOOL)`) still skips national entirely.
