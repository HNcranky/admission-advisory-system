# P2 — Turn-Graph Routing (Boundary A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the imperative post-intent `if intent.route == …` dispatch in `ConversationService` with a compiled LangGraph (`intent_router` router node → conditional edges → handler nodes), **without changing behavior**, locked by a characterization test suite written first.

**Architecture:** Boundary **A** from the spec. The pre-intent pipeline (extract → safety-net → guards: reset / continue-advisory / correction) stays imperative inside `_handle_user_message_inner`. At the point where that method currently calls `intent_router.classify` and branches, it instead builds a `TurnState` and invokes `build_turn_graph(service)`. The graph's `classify` node runs the existing `IntentRouter`, and conditional edges route to handler nodes that each wrap an existing `_handle_*` method verbatim. The returned `ConversationTurnResult` is carried on `TurnState.result`.

**Tech Stack:** Python 3.12, `langgraph==1.1.10` (Pydantic state, conditional edges), pytest.

## Global Constraints

- **Never run `git push`.** Commit only. **No AI attribution** in commit messages.
- Pydantic **v2**. Tests: `.\.venv\Scripts\python.exe -m pytest` (→ `admission_test`).
- **Behavior parity is the contract.** The Task-1 characterization tests MUST stay green through Task 4 unchanged.
- LangGraph pattern as in `graph.py`/P1: Pydantic `state_schema`, nodes mutate + `return state`, `invoke()` returns a dict.
- **Depends on P1** (it added `_handle_user_message_inner`). Land P0+P1 first.
- Source of truth: spec §6.2, §8 (Phase 2), §9 (characterization).

---

## File Structure

**Create**
- `services/chat/turn_graph.py` — `TurnState` + `build_turn_graph(service)`.
- `tests/services/chat/test_turn_routing_characterization.py` — golden behavior per route (Task 1).
- `tests/services/chat/test_turn_graph.py` — graph-specific unit tests (Task 3).

**Modify**
- `services/chat/conversation_service.py` — `_handle_user_message_inner` builds `TurnState` + invokes the graph instead of the inline `if/elif route` block; build the graph once in `__init__`.

---

### Task 1: Characterization tests — lock current routing behavior

**Files:**
- Create: `tests/services/chat/test_turn_routing_characterization.py`

**Interfaces:**
- These tests exercise `ConversationService.handle_user_message` with a stubbed repository / intent router / knowledge_qa and assert the exact `ConversationTurnResult` + key repository side-effects per route. They are written against **current** code and must pass before any refactor.

- [ ] **Step 1: Write the characterization suite (must pass against current code)**

```python
# tests/services/chat/test_turn_routing_characterization.py
from unittest.mock import MagicMock

import pytest

from services.chat.conversation_service import ConversationService
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState, FlowState


def _svc(route_result, profile=None, flow=None, session_status="collecting_profile"):
    repo = MagicMock()
    repo.list_message.return_value = []
    repo.get_profile_state.return_value = profile or ChatProfileState()
    repo.get_flow_state.return_value = flow or FlowState()
    session = MagicMock(status=session_status, latest_run_id=None)
    repo.get_session_by_token.return_value = session
    repo.count_runs.return_value = 0
    svc = ConversationService(
        repository=repo,
        extract_profile=lambda *a, **k: {},
        intent_router=MagicMock(),
        knowledge_qa=MagicMock(),
    )
    svc.intent_router.classify.return_value = route_result
    return svc, repo


def test_conversational_route_returns_greeting_no_run():
    svc, repo = _svc(IntentResult(route="CONVERSATIONAL", subtype="GREETING"))
    result = svc.handle_user_message("tok", "xin chào")
    assert result.should_start_run is False
    assert result.assistant_message  # non-empty greeting
    # an assistant message was persisted
    assert any(c.args[1] == "assistant" for c in repo.append_message.call_args_list)


def test_out_of_scope_route():
    svc, repo = _svc(IntentResult(route="OUT_OF_SCOPE"))
    result = svc.handle_user_message("tok", "thời tiết hôm nay")
    assert result.should_start_run is False
    assert "ngoài phạm vi" in result.assistant_message.lower()


def test_clarification_route_uses_missing_field_prompt():
    svc, repo = _svc(IntentResult(route="CLARIFICATION", missing_fields=["school"]))
    result = svc.handle_user_message("tok", "thế còn cái đó")
    assert result.should_start_run is False
    assert "trường nào" in result.assistant_message.lower()


def test_knowledge_qa_route_calls_service_and_formats_answer():
    svc, repo = _svc(IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="UET"))
    answer = MagicMock(has_data=True, answer="Học phí 15tr.", citations=[])
    svc.knowledge_qa.answer.return_value = answer
    result = svc.handle_user_message("tok", "học phí UET?")
    assert result.should_start_run is False
    assert "Học phí 15tr." in result.assistant_message
    svc.knowledge_qa.answer.assert_called_once()


def test_hybrid_route_complete_profile_starts_hybrid_run():
    full = ChatProfileState(total_score=25, admission_method="thpt_score",
                            subject_combination="A00", admission_year=2026,
                            preferred_schools=["UET"], preferred_majors=["CNTT"])
    svc, repo = _svc(IntentResult(route="HYBRID", schools=["UET", "HUST"], topics=["tuition"],
                                  needs_advisory=True),
                     profile=full, session_status="ready")
    result = svc.handle_user_message("tok", "so sánh điểm chuẩn lẫn học phí UET HUST")
    assert result.should_start_run is True
    assert result.run_kind == "hybrid"
    assert result.hybrid_intent is not None


def test_advisory_route_incomplete_profile_asks_follow_up():
    svc, repo = _svc(IntentResult(route="ADVISORY_FLOW"),
                     profile=ChatProfileState(), flow=FlowState())
    result = svc.handle_user_message("tok", "tư vấn ngành CNTT")
    assert result.should_start_run is False
    assert result.assistant_message  # a follow-up question
    assert result.session_status == "collecting_profile"


def test_reset_route_starts_fresh_profile():
    svc, repo = _svc(IntentResult(route="RESET_PROFILE"))
    # Note: explicit reset phrases are caught pre-intent; this drives the router branch.
    result = svc.handle_user_message("tok", "tư vấn cho em gái mình")
    assert result.should_start_run is False
    assert result.profile_state is not None
```

- [ ] **Step 2: Run against current code — expect PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_routing_characterization.py -v`
Expected: PASS (all routes). If any fails, the assertion is wrong about current behavior — fix the **test** to match current output (this is a snapshot, not a redesign).

- [ ] **Step 3: Commit the safety net**

```bash
git add tests/services/chat/test_turn_routing_characterization.py
git commit -m "test(chat): characterization suite locking turn routing behavior"
```

---

### Task 2: `TurnState` model

**Files:**
- Create: `services/chat/turn_graph.py` (state only in this task)
- Test: `tests/services/chat/test_turn_graph.py`

**Interfaces:**
- Produces: `TurnState` (Pydantic, `arbitrary_types_allowed`): `session_token:str`, `content:str`, `history_ctx:str=""`, `prev_user:str=""`, `profile_state:ChatProfileState`, `flow_state:FlowState`, `delta:dict`, `session_status:str="collecting_profile"`, `intent:IntentResult|None=None`, `route:str|None=None`, `result:ConversationTurnResult|None=None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/services/chat/test_turn_graph.py
from services.chat.models import ChatProfileState, FlowState


def test_turn_state_defaults():
    from services.chat.turn_graph import TurnState
    st = TurnState(session_token="tok", content="hi",
                   profile_state=ChatProfileState(), flow_state=FlowState(), delta={})
    assert st.route is None and st.result is None and st.session_status == "collecting_profile"
```

- [ ] **Step 2: Run — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_graph.py::test_turn_state_defaults -v`
Expected: FAIL — `ModuleNotFoundError: services.chat.turn_graph`.

- [ ] **Step 3: Create `services/chat/turn_graph.py` with `TurnState`**

```python
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState, ConversationTurnResult, FlowState


class TurnState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_token: str
    content: str
    history_ctx: str = ""
    prev_user: str = ""
    profile_state: ChatProfileState
    flow_state: FlowState
    delta: dict = Field(default_factory=dict)
    session_status: str = "collecting_profile"

    intent: Optional[IntentResult] = None
    route: Optional[str] = None
    result: Optional[ConversationTurnResult] = None
```

- [ ] **Step 4: Run — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_graph.py::test_turn_state_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/turn_graph.py tests/services/chat/test_turn_graph.py
git commit -m "feat(chat): add TurnState for the turn routing graph"
```

---

### Task 3: `build_turn_graph` — classify node + conditional routing

**Files:**
- Modify: `services/chat/turn_graph.py` (add `build_turn_graph`)
- Test: `tests/services/chat/test_turn_graph.py`

**Interfaces:**
- Consumes: `TurnState`; a `service` exposing `intent_router.classify`, and the handler methods `_handle_advisory`, `_handle_knowledge_qa`, `_handle_hybrid`, `_handle_out_of_scope`, `_handle_conversational`, `_handle_reset`, `_handle_clarification` (all already on `ConversationService`).
- Produces: `build_turn_graph(service) -> CompiledGraph`; terminal `TurnState.result` holds the `ConversationTurnResult`.
- **Routing table (must mirror `conversation_service.py:144-160` exactly):**
  `ADVISORY_FLOW→advisory`, `KNOWLEDGE_QA→knowledge_qa`, `HYBRID→hybrid`, `OUT_OF_SCOPE→out_of_scope`, `CONVERSATIONAL→conversational`, `RESET_PROFILE→reset`, anything else→`clarification`.

- [ ] **Step 1: Write the failing test (route dispatch + handler args)**

```python
# add to tests/services/chat/test_turn_graph.py
from unittest.mock import MagicMock

from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState, ConversationTurnResult, FlowState


def _fake_service():
    svc = MagicMock()
    def _result(msg="ok", run=False):
        return ConversationTurnResult(session_status="collecting_profile",
                                      assistant_message=msg, should_start_run=run,
                                      profile_state=ChatProfileState())
    svc._handle_knowledge_qa.return_value = _result("kqa")
    svc._handle_conversational.return_value = _result("conv")
    svc._handle_clarification.return_value = _result("clar")
    return svc


def _state(route, **kw):
    return dict(session_token="tok", content="x", profile_state=ChatProfileState(),
                flow_state=FlowState(), delta={}, intent=IntentResult(route=route),
                **kw)


def test_turn_graph_routes_knowledge_qa():
    from services.chat.turn_graph import TurnState, build_turn_graph
    svc = _fake_service()
    svc.intent_router.classify.return_value = IntentResult(route="KNOWLEDGE_QA", topic="tuition")
    graph = build_turn_graph(svc)
    final = graph.invoke(TurnState(session_token="tok", content="học phí?",
                                   profile_state=ChatProfileState(), flow_state=FlowState(), delta={}))
    result = final["result"] if isinstance(final, dict) else final.result
    assert result.assistant_message == "kqa"
    svc._handle_knowledge_qa.assert_called_once()


def test_turn_graph_unknown_route_falls_to_clarification():
    from services.chat.turn_graph import TurnState, build_turn_graph
    svc = _fake_service()
    svc.intent_router.classify.return_value = IntentResult(route="CLARIFICATION", missing_fields=[])
    graph = build_turn_graph(svc)
    final = graph.invoke(TurnState(session_token="tok", content="?",
                                   profile_state=ChatProfileState(), flow_state=FlowState(), delta={}))
    result = final["result"] if isinstance(final, dict) else final.result
    assert result.assistant_message == "clar"
    svc._handle_clarification.assert_called_once()
```

- [ ] **Step 2: Run — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_graph.py -k "routes or clarification" -v`
Expected: FAIL — `ImportError: cannot import name 'build_turn_graph'`.

- [ ] **Step 3: Implement `build_turn_graph` in `services/chat/turn_graph.py`**

Append to the module:
```python
from langgraph.graph import END, StateGraph

_ROUTE_TO_NODE = {
    "ADVISORY_FLOW": "advisory",
    "KNOWLEDGE_QA": "knowledge_qa",
    "HYBRID": "hybrid",
    "OUT_OF_SCOPE": "out_of_scope",
    "CONVERSATIONAL": "conversational",
    "RESET_PROFILE": "reset",
}


def build_turn_graph(service):
    """Compile: classify → (conditional by route) → one handler node → END.
    Handler nodes wrap the existing ConversationService._handle_* methods, so
    behaviour mirrors the former inline if/elif block (conversation_service.py)."""

    def classify(state: TurnState) -> TurnState:
        if state.intent is None:
            state.intent = service.intent_router.classify(
                state.content, state.profile_state, history=state.history_ctx
            )
        state.route = state.intent.route
        return state

    def advisory(state: TurnState) -> TurnState:
        state.result = service._handle_advisory(
            state.session_token, state.profile_state, state.flow_state, state.delta)
        return state

    def knowledge_qa(state: TurnState) -> TurnState:
        state.result = service._handle_knowledge_qa(
            state.session_token, state.content, state.intent, state.profile_state,
            state.flow_state, state.session_status, state.history_ctx, state.prev_user)
        return state

    def hybrid(state: TurnState) -> TurnState:
        state.result = service._handle_hybrid(
            state.session_token, state.content, state.intent, state.profile_state,
            state.flow_state, state.session_status, state.history_ctx, state.prev_user)
        return state

    def out_of_scope(state: TurnState) -> TurnState:
        state.result = service._handle_out_of_scope(
            state.session_token, state.profile_state, state.flow_state, state.session_status)
        return state

    def conversational(state: TurnState) -> TurnState:
        state.result = service._handle_conversational(
            state.session_token, state.content, state.intent, state.profile_state,
            state.flow_state, state.session_status)
        return state

    def reset(state: TurnState) -> TurnState:
        state.result = service._handle_reset(state.session_token, state.delta, state.flow_state)
        return state

    def clarification(state: TurnState) -> TurnState:
        state.result = service._handle_clarification(
            state.session_token, state.intent, state.profile_state, state.flow_state,
            state.session_status)
        return state

    def route_selector(state: TurnState) -> str:
        return _ROUTE_TO_NODE.get(state.route, "clarification")

    builder = StateGraph(TurnState)
    for name, fn in [
        ("classify", classify), ("advisory", advisory), ("knowledge_qa", knowledge_qa),
        ("hybrid", hybrid), ("out_of_scope", out_of_scope), ("conversational", conversational),
        ("reset", reset), ("clarification", clarification),
    ]:
        builder.add_node(name, fn)

    builder.set_entry_point("classify")
    builder.add_conditional_edges("classify", route_selector, {
        "advisory": "advisory", "knowledge_qa": "knowledge_qa", "hybrid": "hybrid",
        "out_of_scope": "out_of_scope", "conversational": "conversational",
        "reset": "reset", "clarification": "clarification",
    })
    for name in ["advisory", "knowledge_qa", "hybrid", "out_of_scope",
                 "conversational", "reset", "clarification"]:
        builder.add_edge(name, END)
    return builder.compile()
```

- [ ] **Step 4: Run — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_graph.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/turn_graph.py tests/services/chat/test_turn_graph.py
git commit -m "feat(chat): build_turn_graph (intent_router node + conditional routing)"
```

---

### Task 4: Wire `_handle_user_message_inner` to the turn graph

**Files:**
- Modify: `services/chat/conversation_service.py` — `__init__` (build graph) and `_handle_user_message_inner` (replace the inline `if/elif route` block, lines ~141-160 post-P1)

**Interfaces:**
- Consumes: `TurnState`, `build_turn_graph` (Task 3).
- The Task-1 characterization suite is the acceptance gate — it must pass unchanged.

- [ ] **Step 1: Build the graph in `__init__`**

After the existing assignments in `ConversationService.__init__`:
```python
        from services.chat.turn_graph import build_turn_graph
        self._turn_graph = build_turn_graph(self)
```

- [ ] **Step 2: Replace the inline route dispatch**

In `_handle_user_message_inner`, locate the block that starts with `intent = self.intent_router.classify(...)` and the following `if intent.route == "ADVISORY_FLOW": ...` chain (the seven-way branch). Replace **the whole block** with a graph invocation:

```python
        session_status = session.status if session else "collecting_profile"
        from services.chat.turn_graph import TurnState
        state = TurnState(
            session_token=session_token,
            content=content,
            history_ctx=history_ctx,
            prev_user=prev_user,
            profile_state=profile_state,
            flow_state=flow_state,
            delta=delta,
            session_status=session_status,
        )
        final = self._turn_graph.invoke(state)
        return final["result"] if isinstance(final, dict) else final.result
```

The `classify` node performs the `intent_router.classify(...)` call that the deleted line used to do, so the LLM classification still happens exactly once, now inside the graph (and nested under the P1 `turn_trace` span).

- [ ] **Step 3: Run the characterization suite — expect PASS unchanged**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_routing_characterization.py -v`
Expected: PASS — identical behavior to Task 1.

- [ ] **Step 4: Run the full chat + e2e suite — expect no regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat tests/e2e -q`
Expected: PASS (guards, continue-advisory, correction-rerun, EC-* all unaffected — they run before the graph).

- [ ] **Step 5: Commit**

```bash
git add services/chat/conversation_service.py
git commit -m "refactor(chat): route post-intent dispatch through the turn graph"
```

---

## Self-Review (P2)

- **Spec coverage:** §6.2 (intent_router node + conditional routing + handler nodes; guards stay imperative) → Tasks 2-4; §9 characterization → Task 1. ✓
- **Placeholder scan:** none — full graph, full TurnState, full wiring, real tests.
- **Type consistency:** handler-node call signatures copied verbatim from `conversation_service.py:144-160`; `_ROUTE_TO_NODE` keys are the exact `IntentResult.route` literals (`intent_router.py:122-130`). `final["result"]` matches the dict-return convention. `build_turn_graph(service)` reads only methods that exist on `ConversationService`. ✓
- **Parity contract:** Task 1 suite is written first against current code and re-run unchanged after Task 4 — the explicit regression gate.
- **Note for executor:** the `classify` node skips re-classifying when `state.intent` is preset — harmless now (we never preset it), but lets P3 inject a route without an LLM call.
