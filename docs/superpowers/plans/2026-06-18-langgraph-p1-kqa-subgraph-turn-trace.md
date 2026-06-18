# P1 — knowledge_qa Subgraph + turn_trace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `KnowledgeQAService.answer()` into a compiled LangGraph subgraph (behind the existing method, so callers are untouched) and add a `turn_trace` root span so the synchronous chat turn — and the inline knowledge QA it runs — produces a proper Langfuse trace.

**Architecture:** Two independent changes. (1) `turn_trace(turn_id, session_token, user_message)` mirrors the existing `advisory_run_trace`; wrapping `ConversationService.handle_user_message` in it gives every synchronous turn a root span, so the intent-router and inline knowledge-QA LLM generations (emitted by the gateway via `record_generation`) nest under it instead of being orphaned. (2) A `build_kqa_graph(service)` factory compiles `embed → retrieve_school → augment_national → gate → {generate | no_data}` from the **same** service helper methods; `answer()` becomes a thin facade that invokes the graph. Determinism, the confidence gate, and the fan-out batching hooks (`query_vector`/`national`) are all preserved.

**Tech Stack:** Python 3.12, `langgraph==1.1.10` (Pydantic state, conditional edges), Langfuse v3 OTEL seam, pytest.

## Global Constraints

- **Never run `git push`.** Commit only. **No AI attribution** in commit messages.
- Pydantic **v2** (`model_config = ConfigDict(...)`).
- Tests: `.\.venv\Scripts\python.exe -m pytest` (auto-redirects to `admission_test`).
- LangGraph state pattern follows `graph.py`: **Pydantic `state_schema`, nodes mutate and `return state`, `graph.invoke(input)` returns a dict** of channel values (cf. `run_dispatcher.py` reading `result.get("final_answer")`).
- **Depends on P0** (Task 1 simplified `agent_tracer`/`run_trace` import surface). Land P0 first.
- Source of truth: spec `2026-06-18-langgraph-agentization-design.md` §6.1, §6.5, §8 (Phase 1).

---

## File Structure

**Create**
- `services/knowledge/qa_graph.py` — `KQAState` + `build_kqa_graph(service)`.
- `tests/services/knowledge/test_qa_graph.py` — subgraph + facade parity tests.
- `tests/observability/test_turn_trace.py` — `turn_trace` unit tests.

**Modify**
- `observability/run_trace.py` — add `turn_trace`.
- `services/knowledge/qa_service.py` — `answer()` delegates to the compiled graph; build graph in `__init__`.
- `services/chat/conversation_service.py` — wrap `handle_user_message` in `turn_trace`.
- `tests/services/chat/test_conversation_service*.py` — assert the wrap (light).

---

### Task 1: Add `turn_trace` root span

**Files:**
- Modify: `observability/run_trace.py` (add after `advisory_run_trace`, ~line 54)
- Test: `tests/observability/test_turn_trace.py`

**Interfaces:**
- Produces: `turn_trace(turn_id: str, session_token: str, user_message: str)` — a context manager yielding the Langfuse span (or `None` when Langfuse is disabled / on error). Never raises.

- [ ] **Step 1: Write the failing test**

```python
# tests/observability/test_turn_trace.py
import contextlib

from observability import run_trace


def test_turn_trace_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(run_trace, "get_langfuse", lambda: None)
    with run_trace.turn_trace("tok:1", "tok", "hello") as span:
        assert span is None


def test_turn_trace_opens_and_closes_span(monkeypatch):
    events = []

    class FakeSpan:
        def update_trace(self, **kw): events.append(("update_trace", kw))

    class FakeCM:
        def __enter__(self): events.append(("enter", None)); return FakeSpan()
        def __exit__(self, *a): events.append(("exit", None)); return False

    class FakeClient:
        def create_trace_id(self, seed=None): return f"tid-{seed}"
        def start_as_current_span(self, **kw):
            events.append(("start", kw)); return FakeCM()

    monkeypatch.setattr(run_trace, "get_langfuse", lambda: FakeClient())
    with run_trace.turn_trace("tok:3", "tok", "học phí UET?") as span:
        assert span is not None
    names = [e[0] for e in events]
    assert names == ["start", "enter", "update_trace", "exit"]
    start_kw = events[0][1]
    assert start_kw["trace_context"] == {"trace_id": "tid-tok:3"}


def test_turn_trace_swallows_open_error(monkeypatch):
    class BoomClient:
        def create_trace_id(self, seed=None): raise RuntimeError("boom")
    monkeypatch.setattr(run_trace, "get_langfuse", lambda: BoomClient())
    with run_trace.turn_trace("tok:1", "tok", "x") as span:
        assert span is None  # degraded, no raise
```

- [ ] **Step 2: Run — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/observability/test_turn_trace.py -v`
Expected: FAIL with `AttributeError: module 'observability.run_trace' has no attribute 'turn_trace'`.

- [ ] **Step 3: Implement `turn_trace` in `observability/run_trace.py`**

Add after `advisory_run_trace` (reuses `_redact`, `_safe_exit`, `get_langfuse` already in the module):

```python
@contextlib.contextmanager
def turn_trace(turn_id, session_token, user_message):
    """Root span/trace for one synchronous chat turn. Yields the span (or None
    when disabled). Generations emitted while active (intent router, inline
    knowledge QA) nest under it via OTEL contextvars. Errors are swallowed."""
    client = get_langfuse()
    cm = None
    span = None
    if client is not None:
        try:
            trace_id = client.create_trace_id(seed=str(turn_id))
            cm = client.start_as_current_span(
                name="chat-turn",
                input=_redact({"user_message": user_message}),
                trace_context={"trace_id": trace_id},
            )
            span = cm.__enter__()
            span.update_trace(
                session_id=str(session_token),
                metadata={"turn_id": turn_id},
                tags=["turn"],
            )
        except Exception as exc:
            logger.warning("langfuse turn_trace open failed: %r", exc)
            _safe_exit(cm)
            cm = None
            span = None
    try:
        yield span
    finally:
        _safe_exit(cm)
```

- [ ] **Step 4: Run — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/observability/test_turn_trace.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add observability/run_trace.py tests/observability/test_turn_trace.py
git commit -m "feat(observability): add turn_trace root span for synchronous chat turns"
```

---

### Task 2: Wrap `handle_user_message` in `turn_trace`

**Files:**
- Modify: `services/chat/conversation_service.py:95-160` (extract the body into an inner method, wrap the public method)
- Test: `tests/services/chat/test_conversation_service_turn_trace.py` (new, light)

**Interfaces:**
- Consumes: `turn_trace` from Task 1.
- Behavior preserved: `handle_user_message(session_token, content) -> ConversationTurnResult` returns exactly as before; it is now wrapped in a root span.

- [ ] **Step 1: Write the failing test**

```python
# tests/services/chat/test_conversation_service_turn_trace.py
import contextlib
from unittest.mock import MagicMock

from services.chat import conversation_service as cs_mod
from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, ConversationTurnResult, FlowState


def _service_with_stubs(monkeypatch):
    svc = ConversationService(
        repository=MagicMock(),
        extract_profile=lambda *a, **k: {},
        intent_router=MagicMock(),
        knowledge_qa=MagicMock(),
    )
    repo = svc.repository
    repo.list_message.return_value = []
    repo.get_session_by_token.return_value = None
    repo.get_profile_state.return_value = ChatProfileState()
    repo.get_flow_state.return_value = FlowState()
    svc.intent_router.classify.return_value = MagicMock(route="CONVERSATIONAL", subtype="GREETING")
    return svc


def test_handle_user_message_opens_turn_trace(monkeypatch):
    opened = []

    @contextlib.contextmanager
    def fake_turn_trace(turn_id, session_token, user_message):
        opened.append((turn_id, session_token, user_message))
        yield None

    monkeypatch.setattr(cs_mod, "turn_trace", fake_turn_trace)
    svc = _service_with_stubs(monkeypatch)

    result = svc.handle_user_message("tok", "xin chào")

    assert isinstance(result, ConversationTurnResult)
    assert len(opened) == 1
    assert opened[0][1] == "tok" and opened[0][2] == "xin chào"
```

- [ ] **Step 2: Run — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service_turn_trace.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'turn_trace'` (not imported yet).

- [ ] **Step 3: Refactor `handle_user_message`**

Add the import at the top of `services/chat/conversation_service.py`:
```python
from observability.run_trace import turn_trace
```

Replace the method definition (line 95) so the public method computes a turn id, opens the span, and delegates to an inner method that holds the **unchanged** body. The existing first line of the body already fetches `prior_messages`; lift it so it is fetched once and reused:

```python
    def handle_user_message(self, session_token: str, content: str) -> ConversationTurnResult:
        prior_messages = self.repository.list_message(session_token)
        turn_id = f"{session_token}:{len(prior_messages) + 1}"
        with turn_trace(turn_id, session_token, content):
            return self._handle_user_message_inner(session_token, content, prior_messages)

    def _handle_user_message_inner(self, session_token: str, content: str, prior_messages) -> ConversationTurnResult:
        # NOTE: body is the former handle_user_message body, minus its first
        # `prior_messages = self.repository.list_message(...)` line (now passed in).
        history_ctx = build_history_context(prior_messages)
        prev_user = next(
            (m.content for m in reversed(prior_messages) if m.role == "user"), ""
        )
        self.repository.append_message(session_token, "user", content, "user_message")
        # ... rest of the original body unchanged ...
```

Do **not** alter any routing/guard logic — only move the `prior_messages` fetch out and indent the rest under the inner method.

- [ ] **Step 4: Run — expect pass (new test + existing conversation tests)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service_turn_trace.py tests/services/chat -q`
Expected: PASS (new test passes; no regression in existing conversation-service tests).

- [ ] **Step 5: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service_turn_trace.py
git commit -m "feat(chat): wrap synchronous turn in turn_trace root span"
```

---

### Task 3: Build the knowledge_qa subgraph

**Files:**
- Create: `services/knowledge/qa_graph.py`
- Test: `tests/services/knowledge/test_qa_graph.py`

**Interfaces:**
- Produces:
  - `KQAState` (Pydantic): `question:str`, `school:str|None`, `topic:str|None`, `conversation_context:str=""`, `retrieval_query:str|None`, `query_vector:Any|None`, `national:Any|None`, `embedding:Any|None`, `chunks:list`, `confidence:float`, `result:KnowledgeQAResult|None`.
  - `build_kqa_graph(service) -> CompiledGraph` — nodes close over a `KnowledgeQAService`-shaped object exposing `embed_query`, `_chunk_repository`, `_top_k`, `_min_score`, `_augment_with_national`, `_generate`.
- The compiled graph's terminal state carries `result: KnowledgeQAResult`.

- [ ] **Step 1: Write the failing test (uses a real service with injected fakes)**

```python
# tests/services/knowledge/test_qa_graph.py
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class _FakeEmbedder:
    def embed(self, texts, task_type=None):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeRepo:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    def vector_search(self, embedding, school, topic, limit):
        self.calls.append((school, topic, limit))
        return list(self._chunks)


class _FakeGateway:
    def __init__(self, answer="Học phí 15 triệu/năm."):
        self._answer = answer

    def run(self, request):
        class R: parsed_data = {"answer": self._answer, "used_source_ids": [1]}
        return R()


def _chunk(text, score, url="http://u"):
    return ScoredChunk(school="UET", topic="tuition", chunk_text=text, source_url=url, score=score)


def _service(chunks, min_score=0.2, answer="Học phí 15 triệu/năm."):
    return KnowledgeQAService(
        chunk_repository=_FakeRepo(chunks),
        embedder=_FakeEmbedder(),
        gateway=_FakeGateway(answer),
        min_score=min_score,
    )


def test_graph_generates_when_above_min_score():
    svc = _service([_chunk("học phí 15tr", 0.9)])
    result = svc.answer(question="học phí UET?", school="UET", topic="tuition")
    assert result.has_data is True
    assert "15 triệu" in result.answer
    assert result.confidence == 0.9
    assert result.citations and result.citations[0].source_url == "http://u"


def test_graph_no_data_below_min_score():
    svc = _service([_chunk("noise", 0.05)], min_score=0.2)
    result = svc.answer(question="học phí UET?", school="UET", topic="tuition")
    assert result.has_data is False
    assert result.confidence == 0.05


def test_graph_no_data_when_no_chunks():
    svc = _service([])
    result = svc.answer(question="học phí UET?", school="UET", topic="tuition")
    assert result.has_data is False


def test_injected_national_is_not_refetched():
    # National-scope school is None → augment is a no-op; ensure injection path runs clean.
    svc = _service([_chunk("x", 0.9)])
    result = svc.answer(question="q", school="UET", topic="tuition",
                        query_vector=[0.5, 0.5, 0.5], national=[])
    # With national=[] injected and school-scoped, _augment_with_national merges [] → chunks unchanged.
    assert result.has_data is True
```

- [ ] **Step 2: Run — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_graph.py -v`
Expected: FAIL — `answer()` still uses the imperative path / `qa_graph` does not exist (import error once Task 4 wires it; for now the test exercises `answer()` which is rewritten in Task 4). Run order: Task 3 creates the graph, Task 4 wires `answer()`; this test goes green after Task 4. To see Task 3 in isolation, add the direct-graph assertion below.

```python
def test_build_kqa_graph_direct_invoke():
    from services.knowledge.qa_graph import KQAState, build_kqa_graph
    svc = _service([_chunk("học phí 15tr", 0.9)])
    graph = build_kqa_graph(svc)
    final = graph.invoke(KQAState(question="q", school="UET", topic="tuition"))
    result = final["result"] if isinstance(final, dict) else final.result
    assert result.has_data is True and result.confidence == 0.9
```

- [ ] **Step 3: Implement `services/knowledge/qa_graph.py`**

```python
from typing import Any, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from services.knowledge.models import KnowledgeQAResult


class KQAState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str
    school: Optional[str] = None
    topic: Optional[str] = None
    conversation_context: str = ""
    # Batching hooks (fan-out injects these; embed/augment no-op when present).
    retrieval_query: Optional[str] = None
    query_vector: Any = None
    national: Any = None
    # Working state.
    embedding: Any = None
    chunks: list = Field(default_factory=list)
    confidence: float = 0.0
    result: Optional[KnowledgeQAResult] = None


def build_kqa_graph(service):
    """Compile the single-(school,topic) knowledge QA pipeline. Nodes reuse the
    service's existing helpers, so behaviour is identical to the former
    answer() body — the gate short-circuits below min_score."""

    def embed(state: KQAState) -> KQAState:
        if state.query_vector is not None:
            state.embedding = state.query_vector
        elif state.retrieval_query:
            state.embedding = service.embed_query(state.retrieval_query)
        else:
            state.embedding = service.embed_query(state.question)
        return state

    def retrieve_school(state: KQAState) -> KQAState:
        state.chunks = service._chunk_repository.vector_search(
            state.embedding, school=state.school, topic=state.topic, limit=service._top_k
        )
        return state

    def augment_national(state: KQAState) -> KQAState:
        state.chunks = service._augment_with_national(
            state.embedding, state.school, state.topic, state.chunks, national=state.national
        )
        state.confidence = state.chunks[0].score if state.chunks else 0.0
        return state

    def generate(state: KQAState) -> KQAState:
        state.result = service._generate(
            state.question, state.chunks, state.confidence, state.conversation_context
        )
        return state

    def no_data(state: KQAState) -> KQAState:
        state.result = KnowledgeQAResult(has_data=False, confidence=state.confidence)
        return state

    def gate(state: KQAState) -> str:
        if state.chunks and state.confidence >= service._min_score:
            return "generate"
        return "no_data"

    builder = StateGraph(KQAState)
    builder.add_node("embed", embed)
    builder.add_node("retrieve_school", retrieve_school)
    builder.add_node("augment_national", augment_national)
    builder.add_node("generate", generate)
    builder.add_node("no_data", no_data)

    builder.set_entry_point("embed")
    builder.add_edge("embed", "retrieve_school")
    builder.add_edge("retrieve_school", "augment_national")
    builder.add_conditional_edges("augment_national", gate,
                                  {"generate": "generate", "no_data": "no_data"})
    builder.add_edge("generate", END)
    builder.add_edge("no_data", END)
    return builder.compile()
```

- [ ] **Step 4: Run the direct-invoke test — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_graph.py::test_build_kqa_graph_direct_invoke -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/qa_graph.py tests/services/knowledge/test_qa_graph.py
git commit -m "feat(knowledge): add knowledge_qa subgraph (KQAState + build_kqa_graph)"
```

---

### Task 4: Make `answer()` a facade over the subgraph

**Files:**
- Modify: `services/knowledge/qa_service.py` (`__init__` builds the graph; `answer()` delegates)
- Test: `tests/services/knowledge/test_qa_graph.py` (the remaining facade tests go green), plus existing `tests/services/knowledge/*` and `tests/services/chat/test_knowledge_fanout*` must stay green.

**Interfaces:**
- Consumes: `KQAState`, `build_kqa_graph` (Task 3).
- Preserved public surface: `answer(question, school, topic, conversation_context="", query_vector=None, national=None, retrieval_query=None) -> KnowledgeQAResult`. `retrieve()`, `generate_from_chunks()`, `embed_query()`, `national_chunks()` are **unchanged** (eval hooks keep working).

- [ ] **Step 1: Build the graph in `__init__` and rewrite `answer()`**

In `KnowledgeQAService.__init__`, after the existing assignments, add:
```python
        from services.knowledge.qa_graph import build_kqa_graph
        self._graph = build_kqa_graph(self)
```

Replace the `answer(...)` method body (`qa_service.py:53-79`) with the facade:
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
        from services.knowledge.qa_graph import KQAState
        state = KQAState(
            question=question,
            school=school,
            topic=topic,
            conversation_context=conversation_context,
            query_vector=query_vector,
            national=national,
            retrieval_query=retrieval_query,
        )
        final = self._graph.invoke(state)
        return final["result"] if isinstance(final, dict) else final.result
```

(The old retrieval/gate/generate logic now lives in the graph nodes, which call the very same helper methods — `embed_query`, `_chunk_repository.vector_search`, `_augment_with_national`, `_generate` — so there is no logic duplication and no behaviour change.)

- [ ] **Step 2: Run the full knowledge_qa subgraph + facade tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge/test_qa_graph.py -v`
Expected: PASS (all five facade tests + the direct-invoke test).

- [ ] **Step 3: Run the broader knowledge + fan-out suites — expect no regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/knowledge tests/services/chat/test_knowledge_fanout.py -q`
Expected: PASS. (Confirms inline QA, fan-out batching with injected `query_vector`/`national`, and eval hooks are unaffected.)

- [ ] **Step 4: Commit**

```bash
git add services/knowledge/qa_service.py
git commit -m "refactor(knowledge): answer() delegates to knowledge_qa subgraph"
```

---

## Self-Review (P1)

- **Spec coverage:** §6.1 (KQA subgraph nodes + injected batching hooks) → Tasks 3-4; §6.5 (`turn_trace`, generations nest, no CallbackHandler) → Tasks 1-2; §8 Phase 1 exit criteria (inline KQA has a parent trace; eval hooks不 regress) → Task 2 + Task 4 Step 3. ✓
- **Placeholder scan:** none — full code for `turn_trace`, `qa_graph.py`, the `answer()` facade, and every test.
- **Type consistency:** `build_kqa_graph(service)` reads `service._top_k`, `service._min_score`, `service._chunk_repository`, `service._augment_with_national`, `service._generate`, `service.embed_query` — all present on `KnowledgeQAService` (`qa_service.py`). `answer()` keyword set matches the four call sites (`conversation_service._handle_knowledge_qa`, `knowledge_fanout._answer_one`, `qa_service.retrieve`, eval). Graph result read via `final["result"]` matches the dict-return convention used by `run_dispatcher`. ✓
- **Determinism:** the confidence gate (`confidence >= _min_score`) is the conditional edge `gate`; below-threshold → `no_data` → `has_data=False`, identical to the former early return.
