# Slice 2c (part 2) — Wire the Retrieval Query into the QA paths — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use `build_retrieval_query` so elided follow-ups embed with their
referent, while the generation prompt always uses the original question.

**Architecture:** Three small wirings. (1) `KnowledgeQAService.answer` gains an
optional `retrieval_query` used for **embedding only** (generation still uses
`question`). (2) The fan-out builds the augmented query, embeds it once, and
shares the vector via the existing `query_vector` param (no new kwarg → its fakes
are untouched). (3) `conversation_service` computes the previous user turn and
threads it into both QA paths.

**Tech Stack:** Python, pytest (in-memory fakes — no live DB needed).

**Spec:** `docs/superpowers/specs/2026-06-10-slice2-rag-latency-design.md` §2c

**Depends on:** `slice2c-retrieval-query-helper.md` (the helper must exist).

---

### Task 1: `answer()` embeds `retrieval_query`, generates from `question`

**Files:**
- Modify: `services/knowledge/qa_service.py:53-70` (`answer` signature + embedding line)
- Test: `tests/services/knowledge/test_qa_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/services/knowledge/test_qa_service.py`:

```python
def test_answer_embeds_retrieval_query_but_generates_from_question():
    chunks = [_chunk("Học phí HUST 30 triệu", "http://hust/fee", 0.9)]
    service, embedder, _, gateway = _build(
        chunks, parsed_data={"answer": "30 triệu", "used_source_ids": [1]}
    )
    service.answer(
        question="còn học phí thì sao",
        school="HUST", topic="tuition",
        retrieval_query="HUST học phí ra sao\ncòn học phí thì sao",
    )
    # embedding used the augmented retrieval text...
    assert embedder.calls[0]["texts"] == ["HUST học phí ra sao\ncòn học phí thì sao"]
    assert embedder.calls[0]["task_type"] == "RETRIEVAL_QUERY"
    # ...but the generation prompt's question stayed the original
    prompt = gateway.calls[0].user_prompt
    assert "Câu hỏi: còn học phí thì sao" in prompt
    assert "HUST học phí ra sao" not in prompt


def test_query_vector_takes_precedence_over_retrieval_query():
    chunks = [_chunk("x", "http://x", 0.9)]
    service, embedder, _, _ = _build(
        chunks, parsed_data={"answer": "ok", "used_source_ids": [1]}
    )
    service.answer(
        question="q", school="VNU-UET", topic="tuition",
        query_vector=[0.7, 0.7], retrieval_query="ignored",
    )
    assert embedder.calls == []  # supplied vector → no embedding at all
```

- [ ] **Step 2: Run them, verify they fail**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_service.py::test_answer_embeds_retrieval_query_but_generates_from_question tests/services/knowledge/test_qa_service.py::test_query_vector_takes_precedence_over_retrieval_query -v`
Expected: FAIL — `answer()` has no `retrieval_query` parameter (`TypeError`).

- [ ] **Step 3: Add the `retrieval_query` parameter**

In `services/knowledge/qa_service.py`, change the `answer` signature and the
embedding line. From:

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
```

to:

```python
    def answer(
        self,
        question: str,
        school: Optional[str],
        topic: Optional[str],
        conversation_context: str = "",
        query_vector=None,
        national=None,
        retrieval_query: Optional[str] = None,
    ) -> KnowledgeQAResult:
        # Embedding precedence: caller-supplied vector > retrieval_query (e.g. a
        # context-augmented follow-up) > the raw question. Generation always uses
        # `question` (see _generate), so the augmented text never reaches the prompt.
        if query_vector is not None:
            embedding = query_vector
        elif retrieval_query:
            embedding = self.embed_query(retrieval_query)
        else:
            embedding = self.embed_query(question)
```

- [ ] **Step 4: Run them, verify they pass**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_service.py::test_answer_embeds_retrieval_query_but_generates_from_question tests/services/knowledge/test_qa_service.py::test_query_vector_takes_precedence_over_retrieval_query -v`
Expected: PASS

- [ ] **Step 5: Run the full qa_service file (no regression)**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_service.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/knowledge/qa_service.py tests/services/knowledge/test_qa_service.py
git commit -m "feat(knowledge): answer() embeds an optional retrieval_query, generates from question"
```

---

### Task 2: Fan-out augments the embedded query from `prev_user`

**Files:**
- Modify: `services/chat/knowledge_fanout.py` (`run_knowledge_fanout` signature + embed line)
- Test: `tests/services/chat/test_knowledge_fanout.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/services/chat/test_knowledge_fanout.py`:

```python
class _PrevUserEmbedQA(FakeKnowledgeQA):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.embedded_texts = []

    def embed_query(self, question):
        self.embedded_texts.append(question)
        return [0.5]

    def national_chunks(self, query_vector, topic):
        return []


def test_fanout_prepends_prev_user_to_embedded_query():
    qa = _PrevUserEmbedQA()
    intent = IntentResult(route="HYBRID", school="HUST", topic="tuition")
    run_knowledge_fanout(
        qa, intent, "còn học phí thì sao",
        conversation_context="Trợ lý: ...", prev_user="HUST xét tuyển thế nào",
    )
    assert qa.embedded_texts == ["HUST xét tuyển thế nào\ncòn học phí thì sao"]


def test_fanout_standalone_question_embeds_verbatim():
    qa = _PrevUserEmbedQA()
    intent = IntentResult(route="HYBRID", school="HUST", topic="tuition")
    run_knowledge_fanout(
        qa, intent, "học phí HUST là bao nhiêu", prev_user="ngành CNTT thế nào",
    )
    assert qa.embedded_texts == ["học phí HUST là bao nhiêu"]  # has noun → not elliptical
```

- [ ] **Step 2: Run them, verify they fail**

Run: `.venv/bin/python -m pytest tests/services/chat/test_knowledge_fanout.py::test_fanout_prepends_prev_user_to_embedded_query tests/services/chat/test_knowledge_fanout.py::test_fanout_standalone_question_embeds_verbatim -v`
Expected: FAIL — `run_knowledge_fanout` has no `prev_user` parameter (`TypeError`).

- [ ] **Step 3: Wire `prev_user` + augmented embed into the fan-out**

In `services/chat/knowledge_fanout.py`:

Add the import near the top (after the existing imports):

```python
from services.knowledge.retrieval_query import build_retrieval_query
```

Change the signature:

```python
def run_knowledge_fanout(knowledge_qa, intent, content, school_fallback=None, conversation_context="", prev_user="") -> list:
```

Replace the embed line (currently `query_vector = knowledge_qa.embed_query(content)`)
so it embeds the context-augmented query instead:

```python
    # Embed the (optionally context-augmented) query once for the whole fan-out.
    # An elided follow-up gets its referent from prev_user; standalone questions
    # are embedded verbatim. On failure, leave the vector None so each answer()
    # embeds the original question internally (resilience over the micro-opt).
    retrieval_text = build_retrieval_query(content, prev_user)
    query_vector = None
    try:
        query_vector = knowledge_qa.embed_query(retrieval_text)
    except Exception as exc:
        logger.warning("knowledge fan-out query embed failed, per-call fallback: %r", exc)
```

Leave `_answer_one` unchanged — it still calls `answer(question=content, ...,
query_vector=query_vector, national=...)`, so the original question drives
generation while the augmented vector drives retrieval.

- [ ] **Step 4: Run them, verify they pass**

Run: `.venv/bin/python -m pytest tests/services/chat/test_knowledge_fanout.py::test_fanout_prepends_prev_user_to_embedded_query tests/services/chat/test_knowledge_fanout.py::test_fanout_standalone_question_embeds_verbatim -v`
Expected: PASS

- [ ] **Step 5: Run the full fan-out file (no regression)**

Run: `.venv/bin/python -m pytest tests/services/chat/test_knowledge_fanout.py -q`
Expected: PASS — `test_fanout_embeds_query_once_and_shares_vector` still holds (default `prev_user=""` → `build_retrieval_query` returns `content` verbatim → one embed of the original text).

- [ ] **Step 6: Commit**

```bash
git add services/chat/knowledge_fanout.py tests/services/chat/test_knowledge_fanout.py
git commit -m "feat(chat): augment fan-out retrieval query with the prior user turn"
```

---

### Task 3: `conversation_service` threads the prior user turn into both QA paths

**Files:**
- Modify: `services/chat/conversation_service.py` (`handle_user_message`, `_handle_knowledge_qa`, `_handle_hybrid`)
- Test: regression via existing `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Add the helper import**

In `services/chat/conversation_service.py`, add to the imports:

```python
from services.knowledge.retrieval_query import build_retrieval_query
```

- [ ] **Step 2: Compute `prev_user` once in `handle_user_message`**

Replace the top of `handle_user_message` (the two lines that build history and
append the message):

```python
        # Build history from turns BEFORE this one — fetch prior to appending so
        # the message being processed is excluded.
        history_ctx = build_history_context(self.repository.list_message(session_token))
        self.repository.append_message(session_token, "user", content, "user_message")
```

with:

```python
        # Build history from turns BEFORE this one — fetch prior to appending so
        # the message being processed is excluded. The last user turn in that
        # history is the referent for an elided follow-up (used by retrieval).
        prior_messages = self.repository.list_message(session_token)
        history_ctx = build_history_context(prior_messages)
        prev_user = next(
            (m.content for m in reversed(prior_messages) if m.role == "user"), ""
        )
        self.repository.append_message(session_token, "user", content, "user_message")
```

- [ ] **Step 3: Pass `prev_user` to the two QA dispatchers**

In the routing block of `handle_user_message`, update the KNOWLEDGE_QA and
HYBRID calls to forward `prev_user`:

```python
        if intent.route == "KNOWLEDGE_QA":
            return self._handle_knowledge_qa(session_token, content, intent, profile_state, flow_state, session_status, history_ctx, prev_user)
        if intent.route == "HYBRID":
            return self._handle_hybrid(session_token, content, intent, profile_state, flow_state, session_status, history_ctx, prev_user)
```

- [ ] **Step 4: Use the augmented query in `_handle_knowledge_qa`**

Change the signature to accept `prev_user`:

```python
    def _handle_knowledge_qa(self, session_token, content, intent, profile_state, flow_state, session_status, history_ctx="", prev_user=""):
```

and pass `retrieval_query` into the `answer()` call:

```python
            result = self.knowledge_qa.answer(
                question=content,
                school=school,
                topic=intent.topic,
                conversation_context=history_ctx,
                retrieval_query=build_retrieval_query(content, prev_user),
            )
```

- [ ] **Step 5: Forward `prev_user` from `_handle_hybrid` into the fan-out**

Change the signature:

```python
    def _handle_hybrid(self, session_token, content, intent, profile_state, flow_state, session_status, history_ctx="", prev_user=""):
```

and the inline fan-out call:

```python
        blocks = run_knowledge_fanout(self.knowledge_qa, intent, content, school_fallback, conversation_context=history_ctx, prev_user=prev_user)
```

- [ ] **Step 6: Run the chat suite (regression)**

Run: `.venv/bin/python -m pytest tests/services/chat -q`
Expected: PASS — the wiring is additive (new params default to `""`), so existing conversation/knowledge/hybrid tests stay green.

- [ ] **Step 7: Commit**

```bash
git add services/chat/conversation_service.py
git commit -m "feat(chat): thread the prior user turn into knowledge-QA retrieval"
```

---

### Task 4: Full-suite green

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (integration/e2e tests need the Docker DB up — start it with `docker compose up -d --wait db` first if they are included).

- [ ] **Step 2: If anything fails, stop and fix before marking the slice done.**
