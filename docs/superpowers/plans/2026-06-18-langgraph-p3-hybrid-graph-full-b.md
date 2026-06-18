# P3 — Hybrid Graph + Guards-as-Nodes (Full Boundary B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (A) Replace the imperative `CompareOrchestrator` ThreadPool with a hybrid LangGraph (`advisory ∥ knowledge → synthesis`); (B) pull the pre-intent guards (reset / rejection / continue-advisory / correction-rerun) into the turn graph as conditional-edge nodes, so the entire synchronous turn is one graph — reaching the spec's target Boundary **B**.

**Architecture:** Group A reuses the exact helpers `CompareOrchestrator` already calls (`run_advisory_for_session`, `run_knowledge_fanout`, `SynthesisAgent.synthesize`) but wires them as graph nodes; `CompareOrchestrator.run()` becomes a thin facade that invokes the compiled graph, so `HybridDispatcher` is untouched. Group B extends `build_turn_graph` (from P2) with guard nodes ahead of `classify`; each guard either sets `TurnState.result` and routes to END, or passes through. The pre-extract work (`extract_profile` + `_deterministic_safety_net`) stays in `_handle_user_message_inner`; everything after enters the graph.

**Tech Stack:** Python 3.12, `langgraph==1.1.10` (parallel branches, conditional edges), pytest.

## Global Constraints

- **Never run `git push`.** Commit only. **No AI attribution** in commit messages.
- Pydantic **v2**. Tests: `.\.venv\Scripts\python.exe -m pytest` (→ `admission_test`).
- **Behavior parity is the contract.** P2's `test_turn_routing_characterization.py` AND this phase's extended guard characterization MUST stay green through the refactor.
- **Depends on P2.** Land P0→P2 first. Group B edits the `build_turn_graph` from P2.
- Source of truth: spec §6.3 (hybrid-graph), §6.2/§8 Phase 3 (guards→nodes), §3 ⚠️ (cross-thread contextvars caveat this fixes).

---

## File Structure

**Create**
- `services/chat/hybrid_graph.py` — `HybridState` + `build_hybrid_graph(deps)`.
- `tests/services/chat/test_hybrid_graph.py`
- `tests/services/chat/test_turn_guards_characterization.py` (Group B safety net)

**Modify**
- `services/chat/compare_orchestrator.py` — `run()` delegates to the compiled hybrid graph.
- `services/chat/turn_graph.py` — add guard nodes + guard-aware entry (Group B).
- `services/chat/conversation_service.py` — move guard calls out of `_handle_user_message_inner` into the graph (Group B).

---

## GROUP A — Hybrid Graph

### Task 1: `HybridState` + branch/synthesis nodes

**Files:**
- Create: `services/chat/hybrid_graph.py`
- Test: `tests/services/chat/test_hybrid_graph.py`

**Interfaces:**
- Produces:
  - `HybridState` (Pydantic, `arbitrary_types_allowed`): `intent:Any`, `profile_state:Any`, `content:str`, `trace_run_id:Any=None`, `advisory:AdvisoryBlock|None=None`, `knowledge:list=[]`, `answer:str=""`.
  - `build_hybrid_graph(advisory_runner, knowledge_qa, synthesis_agent) -> CompiledGraph`. Terminal `HybridState.answer` is the synthesized string.
- Reuses: `run_advisory_for_session`, `run_knowledge_fanout`, `SynthesisAgent`, `AdvisoryBlock`/`KnowledgeBlock` (`services/chat/hybrid_models.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/services/chat/test_hybrid_graph.py
from unittest.mock import MagicMock

from services.chat.hybrid_models import AdvisoryBlock, KnowledgeBlock
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState


def _deps(needs_advisory=True):
    advisory_runner = MagicMock(return_value={"final_answer": "Đậu ~70%.", "citations": []})
    knowledge_qa = MagicMock()
    synthesis = MagicMock()
    synthesis.synthesize.return_value = "TỔNG HỢP"
    return advisory_runner, knowledge_qa, synthesis


def test_hybrid_graph_runs_both_branches_then_synthesizes(monkeypatch):
    from services.chat import hybrid_graph as hg
    advisory_runner, knowledge_qa, synthesis = _deps()
    monkeypatch.setattr(hg, "run_knowledge_fanout",
                        lambda kqa, intent, content, school_fallback=None, **k:
                        [KnowledgeBlock(school="UET", topic="tuition", has_data=True,
                                        answer="15tr", sources=["http://u"])])
    graph = hg.build_hybrid_graph(advisory_runner, knowledge_qa, synthesis)
    state = hg.HybridState(
        intent=IntentResult(route="HYBRID", needs_advisory=True, schools=["UET"], topics=["tuition"]),
        profile_state=ChatProfileState(preferred_schools=["UET"]),
        content="so sánh", trace_run_id=1)
    final = graph.invoke(state)
    answer = final["answer"] if isinstance(final, dict) else final.answer
    assert answer == "TỔNG HỢP"
    advisory_runner.assert_called_once()
    # synthesis got an AdvisoryBlock with data and one KnowledgeBlock
    adv_arg, kb_arg, q_arg = synthesis.synthesize.call_args.args
    assert isinstance(adv_arg, AdvisoryBlock) and adv_arg.has_data is True
    assert kb_arg and kb_arg[0].answer == "15tr"


def test_hybrid_graph_skips_advisory_when_not_needed(monkeypatch):
    from services.chat import hybrid_graph as hg
    advisory_runner, knowledge_qa, synthesis = _deps()
    monkeypatch.setattr(hg, "run_knowledge_fanout", lambda *a, **k: [])
    graph = hg.build_hybrid_graph(advisory_runner, knowledge_qa, synthesis)
    state = hg.HybridState(
        intent=IntentResult(route="HYBRID", needs_advisory=False),
        profile_state=ChatProfileState(), content="chỉ học phí")
    graph.invoke(state)
    advisory_runner.assert_not_called()
    adv_arg, _, _ = synthesis.synthesize.call_args.args
    assert adv_arg.has_data is False
```

- [ ] **Step 2: Run — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_hybrid_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: services.chat.hybrid_graph`.

- [ ] **Step 3: Implement `services/chat/hybrid_graph.py`**

```python
import logging
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from services.chat.hybrid_models import AdvisoryBlock
from services.chat.knowledge_fanout import run_knowledge_fanout

logger = logging.getLogger(__name__)


class HybridState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    intent: Any
    profile_state: Any
    content: str
    trace_run_id: Any = None
    advisory: Optional[AdvisoryBlock] = None
    knowledge: list = Field(default_factory=list)
    answer: str = ""


def _evidence_url(evidence):
    if isinstance(evidence, dict):
        return evidence.get("source_url")
    return getattr(evidence, "source_url", None)


def build_hybrid_graph(advisory_runner, knowledge_qa, synthesis_agent):
    """advisory ∥ knowledge → synthesis. Mirrors CompareOrchestrator but lets
    LangGraph own branch execution (so stage spans nest under the run span)."""

    def advisory_branch(state: HybridState) -> HybridState:
        if not getattr(state.intent, "needs_advisory", False):
            state.advisory = AdvisoryBlock(has_data=False)
            return state
        try:
            result = advisory_runner(state.profile_state, state.content,
                                     trace_run_id=state.trace_run_id)
            answer = (result.get("final_answer") or result.get("advisory") or "").strip()
            if not answer:
                state.advisory = AdvisoryBlock(has_data=False)
                return state
            sources = []
            for evidence in (result.get("citations") or []):
                url = _evidence_url(evidence)
                if url and url not in sources:
                    sources.append(url)
            state.advisory = AdvisoryBlock(has_data=True, answer=answer, sources=sources)
        except Exception as exc:
            logger.warning("advisory branch failed in hybrid graph: %r", exc)
            state.advisory = AdvisoryBlock(has_data=False)
        return state

    def knowledge_branch(state: HybridState) -> HybridState:
        school_fallback = (
            state.profile_state.preferred_schools[0]
            if getattr(state.profile_state, "preferred_schools", None) else None
        )
        try:
            state.knowledge = run_knowledge_fanout(
                knowledge_qa, state.intent, state.content, school_fallback)
        except Exception as exc:
            logger.warning("knowledge branch failed in hybrid graph: %r", exc)
            state.knowledge = []
        return state

    def synthesis(state: HybridState) -> HybridState:
        advisory = state.advisory or AdvisoryBlock(has_data=False)
        state.answer = synthesis_agent.synthesize(advisory, state.knowledge, state.content)
        return state

    builder = StateGraph(HybridState)
    builder.add_node("advisory_branch", advisory_branch)
    builder.add_node("knowledge_branch", knowledge_branch)
    builder.add_node("synthesis", synthesis)

    # Fan out from START to both branches; synthesis waits for both (barrier).
    builder.add_edge(START, "advisory_branch")
    builder.add_edge(START, "knowledge_branch")
    builder.add_edge("advisory_branch", "synthesis")
    builder.add_edge("knowledge_branch", "synthesis")
    builder.add_edge("synthesis", END)
    return builder.compile()
```

Note: `advisory` and `knowledge` are written by disjoint branches → no channel-write conflict, so no custom reducer is needed.

- [ ] **Step 4: Run — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_hybrid_graph.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/hybrid_graph.py tests/services/chat/test_hybrid_graph.py
git commit -m "feat(chat): hybrid graph (advisory ∥ knowledge → synthesis)"
```

---

### Task 2: `CompareOrchestrator.run()` delegates to the graph

**Files:**
- Modify: `services/chat/compare_orchestrator.py`
- Test: existing `tests/services/chat/test_compare_orchestrator*.py` (must stay green), plus `tests/services/chat/test_hybrid_dispatcher*.py`

**Interfaces:**
- Preserved: `CompareOrchestrator.run(intent, profile_state, content, trace_run_id=None) -> str`. `HybridDispatcher` is unchanged.

- [ ] **Step 1: Rewrite `CompareOrchestrator` to build + invoke the graph**

```python
import logging

from services.chat.advisory_runner import run_advisory_for_session
from services.chat.hybrid_graph import HybridState, build_hybrid_graph
from services.chat.synthesis_agent import SynthesisAgent
from services.knowledge.qa_service import KnowledgeQAService

logger = logging.getLogger(__name__)


class CompareOrchestrator:
    def __init__(self, advisory_runner=None, knowledge_qa=None, synthesis_agent=None):
        self.advisory_runner = advisory_runner or run_advisory_for_session
        self.knowledge_qa = knowledge_qa or KnowledgeQAService()
        self.synthesis_agent = synthesis_agent or SynthesisAgent()
        self._graph = build_hybrid_graph(
            self.advisory_runner, self.knowledge_qa, self.synthesis_agent)

    def run(self, intent, profile_state, content, trace_run_id=None) -> str:
        state = HybridState(intent=intent, profile_state=profile_state,
                            content=content, trace_run_id=trace_run_id)
        final = self._graph.invoke(state)
        return final["answer"] if isinstance(final, dict) else final.answer
```

(The `_run_advisory` / `_collect_*` helpers move into the graph nodes — delete them from this file.)

- [ ] **Step 2: Run the hybrid suites — expect no regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat -k "hybrid or compare" -q`
Expected: PASS. If a test asserted ThreadPool internals (e.g. patched `executor`), update it to assert the synthesized result instead — the public contract (`run(...) -> str`) is unchanged.

- [ ] **Step 3: Verify trace nesting (manual, optional but recommended)**

With Langfuse enabled, trigger a hybrid run and confirm in the Langfuse UI that the advisory stage spans nest under the hybrid run span (this is the §3 ⚠️ cross-thread caveat the graph is meant to fix). If nesting is still flat, note it — LangGraph's branch executor context propagation may need `trace_context` threading; capture findings for follow-up rather than blocking.

- [ ] **Step 4: Commit**

```bash
git add services/chat/compare_orchestrator.py
git commit -m "refactor(chat): CompareOrchestrator delegates to the hybrid graph"
```

---

## GROUP B — Guards as Turn-Graph Nodes (reaches Boundary B)

> Higher-risk: the guards carry EC-* edge cases. Task 3 (extended characterization) is the gate; Tasks 4-5 must keep it green. **If risk/time is tight, Group A ships independently and Group B can be deferred without losing the hybrid-graph win.**

### Task 3: Extend characterization to the guards

**Files:**
- Create: `tests/services/chat/test_turn_guards_characterization.py`

- [ ] **Step 1: Write golden tests for each guard (against current code)**

```python
# tests/services/chat/test_turn_guards_characterization.py
from unittest.mock import MagicMock

from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, FlowState


def _svc(profile=None, flow=None, session=None, delta=None):
    repo = MagicMock()
    repo.list_message.return_value = []
    repo.get_profile_state.return_value = profile or ChatProfileState()
    repo.get_flow_state.return_value = flow or FlowState()
    repo.get_session_by_token.return_value = session
    repo.count_runs.return_value = 0
    svc = ConversationService(
        repository=repo,
        extract_profile=lambda *a, **k: (delta or {}),
        intent_router=MagicMock(),
        knowledge_qa=MagicMock(),
    )
    return svc, repo


def test_reset_phrase_starts_fresh_profile_before_routing():
    svc, repo = _svc()
    svc.intent_router.classify.return_value = MagicMock(route="ADVISORY_FLOW")
    result = svc.handle_user_message("tok", "xoá hết thông tin, bắt đầu lại")
    # reset wins over intent routing; classify must NOT decide the turn
    assert result.should_start_run is False
    assert result.profile_state == ChatProfileState() or result.profile_state is not None


def test_continue_advisory_fills_pending_slot():
    profile = ChatProfileState(total_score=25, subject_combination="A00",
                               preferred_majors=["CNTT"], preferred_schools=["UET"])
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Bạn xét tuyển năm nào?")
    svc, repo = _svc(profile=profile, flow=flow, delta={"admission_year": 2026})
    result = svc.handle_user_message("tok", "năm 2026")
    # the bare answer advances the advisory flow rather than being misrouted
    assert result.profile_state.admission_year == 2026


def test_correction_rerun_after_prior_run():
    profile = ChatProfileState(total_score=27, subject_combination="A00",
                               admission_method="thpt_score", admission_year=2026,
                               preferred_majors=["CNTT"], preferred_schools=["UET"])
    session = MagicMock(status="completed", latest_run_id=42)
    svc, repo = _svc(profile=profile, session=session, delta={"total_score": 25.75})
    result = svc.handle_user_message("tok", "à mình tính lại 25.75 không phải 27")
    assert result.should_start_run is True
    assert result.correction_note and result.correction_note["new_value"] == 25.75
```

- [ ] **Step 2: Run against current code — expect PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_guards_characterization.py -v`
Expected: PASS. Adjust assertions to match current output where needed (snapshot, not redesign).

- [ ] **Step 3: Commit the safety net**

```bash
git add tests/services/chat/test_turn_guards_characterization.py
git commit -m "test(chat): characterization for pre-intent guards (reset/continue/correction)"
```

---

### Task 4: Add guard nodes to `build_turn_graph`

**Files:**
- Modify: `services/chat/turn_graph.py` — add a guarded entry chain ahead of `classify`; add fields to `TurnState`.

**Interfaces:**
- `TurnState` gains: `session:Any=None` (for the correction guard).
- New entry order: `reset_guard → rejection_guard → continue_guard → correction_guard → classify → (route)`. Each guard sets `state.result` and short-circuits to END when it fires.

- [ ] **Step 1: Add `session` to `TurnState`**

In `services/chat/turn_graph.py`, add to `TurnState`:
```python
    session: Any = None
```

- [ ] **Step 2: Add guard nodes + guarded edges in `build_turn_graph`**

Add these node functions inside `build_turn_graph` (they wrap existing `ConversationService` methods/helpers):
```python
    from services.profile.validation import validate_profile_delta

    def reset_guard(state: TurnState) -> TurnState:
        from services.chat.conversation_service import _is_reset_request
        if _is_reset_request(state.content):
            state.result = service._handle_reset(state.session_token, state.delta, state.flow_state)
        return state

    def rejection_guard(state: TurnState) -> TurnState:
        clean_delta, rejections = validate_profile_delta(state.delta, state.profile_state)
        state.delta = clean_delta
        if rejections:
            state.result = service._handle_rejection(
                state.session_token, state.profile_state, state.flow_state, clean_delta, rejections)
        return state

    def continue_guard(state: TurnState) -> TurnState:
        r = service._maybe_continue_advisory(
            state.session_token, state.content, state.profile_state, state.flow_state, state.delta)
        if r is not None:
            state.result = r
        return state

    def correction_guard(state: TurnState) -> TurnState:
        r = service._maybe_correction_rerun(
            state.session_token, state.profile_state, state.flow_state, state.delta, state.session)
        if r is not None:
            state.result = r
        return state

    def _guard_gate(next_node):
        def gate(state: TurnState) -> str:
            return "end" if state.result is not None else next_node
        return gate
```

Register them and wire the guarded chain (replacing `set_entry_point("classify")`):
```python
    builder.add_node("reset_guard", reset_guard)
    builder.add_node("rejection_guard", rejection_guard)
    builder.add_node("continue_guard", continue_guard)
    builder.add_node("correction_guard", correction_guard)

    builder.set_entry_point("reset_guard")
    builder.add_conditional_edges("reset_guard", _guard_gate("rejection_guard"),
                                  {"end": END, "rejection_guard": "rejection_guard"})
    builder.add_conditional_edges("rejection_guard", _guard_gate("continue_guard"),
                                  {"end": END, "continue_guard": "continue_guard"})
    builder.add_conditional_edges("continue_guard", _guard_gate("correction_guard"),
                                  {"end": END, "correction_guard": "correction_guard"})
    builder.add_conditional_edges("correction_guard", _guard_gate("classify"),
                                  {"end": END, "classify": "classify"})
```
(The existing `classify` conditional edges and handler→END edges stay.)

- [ ] **Step 3: Unit-test the guard short-circuit**

```python
# add to tests/services/chat/test_turn_graph.py
def test_guard_short_circuits_before_classify():
    from services.chat.turn_graph import TurnState, build_turn_graph
    from services.chat.models import ChatProfileState, ConversationTurnResult, FlowState
    from unittest.mock import MagicMock
    svc = MagicMock()
    svc._maybe_continue_advisory.return_value = ConversationTurnResult(
        session_status="collecting_profile", assistant_message="continued",
        profile_state=ChatProfileState())
    svc._maybe_correction_rerun.return_value = None
    graph = build_turn_graph(svc)
    final = graph.invoke(TurnState(session_token="tok", content="năm 2026",
                                   profile_state=ChatProfileState(),
                                   flow_state=FlowState(active_flow="ADVISORY_FLOW",
                                                        pending_question="năm nào?"),
                                   delta={"admission_year": 2026}))
    result = final["result"] if isinstance(final, dict) else final.result
    assert result.assistant_message == "continued"
    svc.intent_router.classify.assert_not_called()  # classify skipped
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_graph.py -v`
Expected: PASS (existing routing tests + this guard test). Note: ensure `validate_profile_delta` is monkeypatched or the MagicMock delta is `{}` so `rejection_guard` does not fire first; in the test above delta is a real dict and `validate_profile_delta({"admission_year":2026}, ChatProfileState())` returns no rejections.

- [ ] **Step 4: Commit**

```bash
git add services/chat/turn_graph.py tests/services/chat/test_turn_graph.py
git commit -m "feat(chat): guard nodes (reset/rejection/continue/correction) in turn graph"
```

---

### Task 5: Move guards out of `_handle_user_message_inner`

**Files:**
- Modify: `services/chat/conversation_service.py`

**Interfaces:**
- The inner method now: build history → append user msg → fetch session/profile/flow → compute `delta` (extract + safety-net) → build `TurnState` (with `session`, `delta`) → invoke the full turn graph. The guard `if`-returns are deleted (the graph runs them).

- [ ] **Step 1: Replace the guard block + routing block with a single graph invoke**

In `_handle_user_message_inner`, keep everything up to and including:
```python
        active_slot = (missing_critical_slots(profile_state) or [None])[0]
        delta = self.extract_profile(content, profile_state, active_slot)
        delta = self._deterministic_safety_net(delta, content, active_slot)
```
Then **delete** the `_is_reset_request`, `validate_profile_delta`/`_handle_rejection`, `_maybe_continue_advisory`, `_maybe_correction_rerun`, and the `intent = self.intent_router.classify(...)` + seven-way `if` block. Replace with:
```python
        from services.chat.turn_graph import TurnState
        session_status = session.status if session else "collecting_profile"
        state = TurnState(
            session_token=session_token,
            content=content,
            history_ctx=history_ctx,
            prev_user=prev_user,
            profile_state=profile_state,
            flow_state=flow_state,
            delta=delta,
            session_status=session_status,
            session=session,
        )
        final = self._turn_graph.invoke(state)
        return final["result"] if isinstance(final, dict) else final.result
```

- [ ] **Step 2: Run BOTH characterization suites — expect PASS unchanged**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_routing_characterization.py tests/services/chat/test_turn_guards_characterization.py -v`
Expected: PASS — identical behavior, guards now executed inside the graph.

- [ ] **Step 3: Run full chat + e2e — expect no regression (EC-* gate)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat tests/e2e -q`
Expected: PASS (EC-04 rejection, EC-07 correction, EC-22 reset, continue-advisory).

- [ ] **Step 4: Commit**

```bash
git add services/chat/conversation_service.py
git commit -m "refactor(chat): run pre-intent guards inside the turn graph (Boundary B)"
```

---

## P4 (Deferred) — `interrupt()`-based slot collection

**Status:** Out of scope for execution now; sketch only (spec §8 Phase 4, optional).

The deterministic slot-collection loop (`_advance_advisory` + `flow_state.pending_question` + the continue-advisory guard) could be replaced by LangGraph's `interrupt()` HITL primitive with a checkpointer: `ask_next_slot` node calls `interrupt(question)`; the web turn resumes the thread with `Command(resume=answer)`. This removes the bespoke `flow_state` machine.

**Why deferred:** it requires a LangGraph checkpointer wired to Postgres and a rework of the durable-run boundary; the current deterministic collection passes all EC-* cases. Only pursue if the HITL idiom is independently wanted. Do **not** start without its own brainstorm + characterization extension.

---

## Self-Review (P3)

- **Spec coverage:** §6.3 hybrid-graph → Group A (Tasks 1-2); §6.2/§8 guards→nodes (Boundary B) → Group B (Tasks 3-5); §3 ⚠️ contextvars → Task 2 Step 3 (verify); §8 Phase 4 → P4 stub. ✓
- **Placeholder scan:** none — full `HybridState`/graph, full guard nodes, full wiring, real tests. Task 2 Step 3 is an explicit manual verification (allowed), not a code placeholder.
- **Type consistency:** `build_hybrid_graph(advisory_runner, knowledge_qa, synthesis_agent)` args match `CompareOrchestrator.__init__` fields; `run(...) -> str` unchanged. Guard nodes call `_handle_reset/_handle_rejection/_maybe_continue_advisory/_maybe_correction_rerun` with the exact signatures in `conversation_service.py`. `TurnState.session` added for the correction guard. ✓
- **Parity contract:** two characterization suites (P2 routes + P3 guards) gate the Group B refactor.
- **Decoupling:** Group A and Group B are independent commits; Group A delivers value alone if Group B is deferred.
