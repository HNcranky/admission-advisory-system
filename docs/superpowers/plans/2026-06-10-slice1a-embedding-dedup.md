# Slice 1 — Plan A: Deduplicate query embedding in knowledge fan-out

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed the user question **once** per knowledge fan-out instead of once per `(school, topic)` pair, removing N×M-1 redundant `RETRIEVAL_QUERY` embedding API calls.

**Architecture:** Add a public `embed_query()` method and an optional `query_vector` parameter to `KnowledgeQAService.answer()`. `run_knowledge_fanout` embeds once up front and passes the shared vector into every per-task call. When the up-front embed fails, `answer()` falls back to embedding internally per call (resilience preserved).

**Tech Stack:** Python, pytest, GeminiEmbedder (`task_type="RETRIEVAL_QUERY"`).

Spec: `docs/superpowers/specs/2026-06-10-slice1-cost-quickwins-design.md` §1c.

---

### Task 1: `query_vector` short-circuits internal embedding in `answer()`

**Files:**
- Modify: `services/knowledge/qa_service.py:48-63`
- Test: `tests/services/knowledge/test_qa_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_answer_uses_supplied_query_vector_without_embedding():
    class _CountingEmbedder:
        def __init__(self):
            self.calls = 0
        def embed(self, texts, task_type):
            self.calls += 1
            return [[0.0, 0.0, 0.0]]

    class _FakeRepo:
        def __init__(self):
            self.searched_with = []
        def vector_search(self, embedding, school, topic, limit):
            self.searched_with.append(list(embedding))
            return []  # no chunks → early no-data return, LLM never called

    embedder = _CountingEmbedder()
    repo = _FakeRepo()
    service = KnowledgeQAService(chunk_repository=repo, embedder=embedder, gateway=object())
    result = service.answer("học phí?", school="VNU-UET", topic="tuition",
                            query_vector=[0.1, 0.2, 0.3])

    assert embedder.calls == 0                       # supplied vector reused
    assert repo.searched_with[0] == [0.1, 0.2, 0.3]  # search used that vector
    assert result.has_data is False
```

(Add `from services.knowledge.qa_service import KnowledgeQAService` if not already imported in the file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_service.py::test_answer_uses_supplied_query_vector_without_embedding -v`
Expected: FAIL — `answer()` got an unexpected keyword argument `query_vector`.

- [ ] **Step 3: Write minimal implementation**

In `services/knowledge/qa_service.py`, add the method and extend `answer()`:

```python
    def embed_query(self, question: str):
        """Embed a retrieval query. Exposed so callers (e.g. the fan-out) can
        embed once and reuse the vector across many answer() calls."""
        return self._embedder.embed([question], task_type="RETRIEVAL_QUERY")[0]

    def answer(
        self,
        question: str,
        school: Optional[str],
        topic: Optional[str],
        conversation_context: str = "",
        query_vector=None,
    ) -> KnowledgeQAResult:
        embedding = query_vector if query_vector is not None else self.embed_query(question)
        chunks = self._chunk_repository.vector_search(
            embedding, school=school, topic=topic, limit=self._top_k
        )
        chunks = self._augment_with_national(embedding, school, topic, chunks)
        confidence = chunks[0].score if chunks else 0.0
        if not chunks or confidence < self._min_score:
            return KnowledgeQAResult(has_data=False, confidence=confidence)
        return self._generate(question, chunks, confidence, conversation_context)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_service.py::test_answer_uses_supplied_query_vector_without_embedding -v`
Expected: PASS

- [ ] **Step 5: Run the existing qa_service tests for regressions**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_service.py -q`
Expected: PASS (the `query_vector=None` default keeps every existing call identical).

- [ ] **Step 6: Commit**

```bash
git add services/knowledge/qa_service.py tests/services/knowledge/test_qa_service.py
git commit -m "feat(knowledge): allow reusing a precomputed query vector in QA answer"
```

---

### Task 2: Fan-out embeds once and shares the vector

**Files:**
- Modify: `services/chat/knowledge_fanout.py:29-58`
- Test: `tests/services/chat/test_knowledge_fanout.py`

- [ ] **Step 1: Write the failing test**

The existing `FakeKnowledgeQA` (top of the file) must learn `embed_query` and accept the new kwarg. Add an embed-counting subclass and a test:

```python
class _EmbedCountingQA(FakeKnowledgeQA):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.embed_calls = 0
        self.vectors_seen = []

    def embed_query(self, question):
        self.embed_calls += 1
        return [0.5, 0.5]

    def answer(self, question, school, topic, conversation_context="", query_vector=None):
        self.vectors_seen.append(query_vector)
        return super().answer(question, school, topic, conversation_context)


def test_fanout_embeds_query_once_and_shares_vector():
    qa = _EmbedCountingQA()
    intent = IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"])
    run_knowledge_fanout(qa, intent, "so sánh học phí", school_fallback=None)
    assert qa.embed_calls == 1                       # one embed for the whole fan-out
    assert len(qa.vectors_seen) == 2                 # but both tasks ran
    assert all(v == [0.5, 0.5] for v in qa.vectors_seen)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_fanout.py::test_fanout_embeds_query_once_and_shares_vector -v`
Expected: FAIL — `embed_query` not called (count 0) / `query_vector` not forwarded.

- [ ] **Step 3: Write minimal implementation**

In `services/chat/knowledge_fanout.py`, embed once before dispatch and forward the vector:

```python
def run_knowledge_fanout(knowledge_qa, intent, content, school_fallback=None, conversation_context="") -> list:
    """Call the single-school KnowledgeQA once per (school, topic) pair, in parallel.

    Each call swallows its own error → a no-data KnowledgeBlock; siblings survive.
    Block order matches the original (school, topic) iteration order.
    The query is embedded once and shared across all calls (see spec §1c).
    """
    tasks = [
        (school, topic)
        for school in _resolve_schools(intent, school_fallback)
        for topic in _resolve_topics(intent)
    ]

    # Embed the query once for the whole fan-out. On failure, leave it None so
    # each answer() embeds internally (resilience over the micro-optimization).
    query_vector = None
    try:
        query_vector = knowledge_qa.embed_query(content)
    except Exception as exc:
        logger.warning("knowledge fan-out query embed failed, per-call fallback: %r", exc)

    def _answer_one(task):
        school, topic = task
        try:
            return knowledge_qa.answer(
                question=content, school=school, topic=topic,
                conversation_context=conversation_context,
                query_vector=query_vector,
            )
        except Exception as exc:
            logger.warning(
                "knowledge fan-out failed for school=%r topic=%r: %r", school, topic, exc
            )
            return None
    ...
```

(Leave the rest of the function — the `if len(tasks) <= 1` block, the executor, and block assembly — unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_fanout.py::test_fanout_embeds_query_once_and_shares_vector -v`
Expected: PASS

- [ ] **Step 5: Run the full fan-out + qa suites**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_knowledge_fanout.py tests/services/knowledge/test_qa_service.py -q`
Expected: PASS (existing `FakeKnowledgeQA.answer` already accepts `conversation_context`; the subclass adds `query_vector`; the base callers are unaffected because `run_knowledge_fanout` now passes the kwarg and the real service defaults it).

> NOTE: the base `FakeKnowledgeQA.answer` signature in this file does **not** declare `query_vector`. After Task 2, `run_knowledge_fanout` passes `query_vector=...` to it. Update the base `FakeKnowledgeQA.answer` signature to `def answer(self, question, school, topic, conversation_context="", query_vector=None):` so the other tests in this file keep passing. Make that one-line signature edit as part of Step 3.

- [ ] **Step 6: Commit**

```bash
git add services/chat/knowledge_fanout.py tests/services/chat/test_knowledge_fanout.py
git commit -m "feat(chat): embed knowledge fan-out query once and share the vector"
```

---

## Self-review notes

- Behavior unchanged: `query_vector` defaults to `None`; standalone `answer()` callers (`conversation_service._handle_knowledge_qa`) keep embedding internally.
- Resilience: embed failure in the fan-out degrades to per-call embedding, never crashes.
- The national-scope search still runs per call — that is **Plan B** (`2026-06-10-slice1b-national-search-dedup.md`).
