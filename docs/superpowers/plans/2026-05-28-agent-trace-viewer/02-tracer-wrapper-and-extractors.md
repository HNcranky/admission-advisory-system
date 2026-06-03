# Slice 02 — Tracer Wrapper + Extractors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `traced()` decorator that wraps each LangGraph agent, define one output extractor per stage, and wire them into `graph.py`. After this slice, every advisory run produced via the chat flow writes 6 rows into `advisory_trace_events`.

**Architecture:** Decorator inspects `state.trace_run_id` — if `None`, bypass (preserves test/script invocations). On entry, calls `TraceRepository.start_event`; on success calls `complete_event(output_extractor(result, state))`; on exception calls `fail_event(repr(exc))` and re-raises. Extractors return Pydantic-friendly dicts (`.model_dump(mode="json")`).

**Tech Stack:** Python 3.12, pydantic v2, pytest, LangGraph (already in use).

---

### Task 1: `traced()` decorator — bypass when no `trace_run_id`

**Files:**
- Create: `services/tracing/agent_tracer.py`
- Create: `tests/services/tracing/test_agent_tracer.py`

- [ ] **Step 1: Write the failing test**

```python
from state import AgentState
from services.tracing.agent_tracer import traced


def test_traced_bypasses_when_trace_run_id_is_none():
    called_with = {}

    def agent(state):
        called_with["state"] = state
        state.user_query = "modified"
        return state

    wrapped = traced("profile", 0, lambda result, state: {})(agent)
    state = AgentState(user_query="hello", trace_run_id=None)

    result = wrapped(state)

    assert result.user_query == "modified"
    assert called_with["state"] is state
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_agent_tracer.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement minimal decorator**

Create `services/tracing/agent_tracer.py`:

```python
from typing import Callable

from services.tracing.trace_repository import TraceRepository

STAGE_ORDER = ["profile", "retrieve", "conflict", "reason", "policy", "explain"]

_default_repo = TraceRepository()


def traced(stage: str, sequence: int, output_extractor: Callable, repository: TraceRepository | None = None):
    repo = repository or _default_repo

    def decorator(agent_fn):
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            # tracing branch lands in next task
            return agent_fn(state)
        return wrapped

    return decorator
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_agent_tracer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/agent_tracer.py tests/services/tracing/test_agent_tracer.py
git commit -m "feat(tracing): traced() decorator skeleton with no-op bypass"
```

---

### Task 2: `traced()` — happy path writes start + complete events

**Files:**
- Modify: `services/tracing/agent_tracer.py`
- Modify: `tests/services/tracing/test_agent_tracer.py`

- [ ] **Step 1: Write the failing test**

```python
class FakeTraceRepo:
    def __init__(self, next_event_id=99):
        self.started = []
        self.completed = []
        self.failed = []
        self._next_id = next_event_id

    def start_event(self, run_id, stage, sequence):
        self.started.append((run_id, stage, sequence))
        return self._next_id

    def complete_event(self, event_id, output_json):
        self.completed.append((event_id, output_json))

    def fail_event(self, event_id, error_text):
        self.failed.append((event_id, error_text))


def test_traced_writes_start_then_complete_on_success():
    repo = FakeTraceRepo(next_event_id=42)

    def agent(state):
        state.user_query = "after"
        return state

    extractor = lambda result, state: {"snapshot": result.user_query}
    wrapped = traced("profile", 0, extractor, repository=repo)(agent)

    state = AgentState(user_query="before", trace_run_id=7)
    wrapped(state)

    assert repo.started == [(7, "profile", 0)]
    assert repo.completed == [(42, {"snapshot": "after"})]
    assert repo.failed == []
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_agent_tracer.py::test_traced_writes_start_then_complete_on_success -v`
Expected: FAIL — `repo.started == []` (decorator does not call `start_event` yet).

- [ ] **Step 3: Implement the tracing branch**

Replace the body of `wrapped` in `services/tracing/agent_tracer.py`:

```python
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            event_id = repo.start_event(run_id, stage, sequence)
            result = agent_fn(state)
            repo.complete_event(event_id, output_extractor(result, state))
            return result
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_agent_tracer.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/agent_tracer.py tests/services/tracing/test_agent_tracer.py
git commit -m "feat(tracing): traced() writes start+complete events on success"
```

---

### Task 3: `traced()` — error path writes fail_event and re-raises

**Files:**
- Modify: `services/tracing/agent_tracer.py`
- Modify: `tests/services/tracing/test_agent_tracer.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest


def test_traced_writes_fail_event_and_reraises_on_exception():
    repo = FakeTraceRepo(next_event_id=55)

    def agent(state):
        raise ValueError("bad input")

    wrapped = traced("retrieve", 1, lambda r, s: {}, repository=repo)(agent)

    state = AgentState(user_query="hi", trace_run_id=3)

    with pytest.raises(ValueError, match="bad input"):
        wrapped(state)

    assert repo.started == [(3, "retrieve", 1)]
    assert repo.completed == []
    assert len(repo.failed) == 1
    assert repo.failed[0][0] == 55
    assert "ValueError" in repo.failed[0][1]
    assert "bad input" in repo.failed[0][1]
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_agent_tracer.py::test_traced_writes_fail_event_and_reraises_on_exception -v`
Expected: FAIL — exception bubbles but no `fail_event` is recorded.

- [ ] **Step 3: Add try/except**

Update `wrapped` in `services/tracing/agent_tracer.py`:

```python
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            event_id = repo.start_event(run_id, stage, sequence)
            try:
                result = agent_fn(state)
            except Exception as exc:
                repo.fail_event(event_id, repr(exc))
                raise
            repo.complete_event(event_id, output_extractor(result, state))
            return result
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_agent_tracer.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/agent_tracer.py tests/services/tracing/test_agent_tracer.py
git commit -m "feat(tracing): traced() records fail_event and re-raises"
```

---

### Task 4: `traced()` — extractor errors don't break the run

**Files:**
- Modify: `services/tracing/agent_tracer.py`
- Modify: `tests/services/tracing/test_agent_tracer.py`

- [ ] **Step 1: Write the failing test**

```python
def test_traced_swallows_extractor_error_and_marks_completed():
    repo = FakeTraceRepo(next_event_id=88)

    def agent(state):
        return state

    def broken_extractor(result, state):
        raise TypeError("not serializable")

    wrapped = traced("policy", 4, broken_extractor, repository=repo)(agent)

    state = AgentState(user_query="hi", trace_run_id=1)
    wrapped(state)  # must not raise

    assert repo.completed == [(88, {"_extractor_error": "TypeError('not serializable')"})]
    assert repo.failed == []
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_agent_tracer.py::test_traced_swallows_extractor_error_and_marks_completed -v`
Expected: FAIL — `TypeError` propagates out.

- [ ] **Step 3: Guard the extractor call**

Update `wrapped` in `services/tracing/agent_tracer.py`:

```python
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            event_id = repo.start_event(run_id, stage, sequence)
            try:
                result = agent_fn(state)
            except Exception as exc:
                repo.fail_event(event_id, repr(exc))
                raise
            try:
                output_json = output_extractor(result, state)
            except Exception as exc:
                output_json = {"_extractor_error": repr(exc)}
            repo.complete_event(event_id, output_json)
            return result
```

- [ ] **Step 4: Run all tracer tests**

Run: `pytest tests/services/tracing/test_agent_tracer.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/agent_tracer.py tests/services/tracing/test_agent_tracer.py
git commit -m "feat(tracing): traced() degrades gracefully when extractor raises"
```

---

### Task 5: `traced()` — DB write failures don't break the run

**Files:**
- Modify: `services/tracing/agent_tracer.py`
- Modify: `tests/services/tracing/test_agent_tracer.py`

Tracing is observability — a DB hiccup must not crash advisory.

- [ ] **Step 1: Write the failing test**

```python
class ExplodingTraceRepo:
    def start_event(self, *a, **kw):
        raise RuntimeError("db down")

    def complete_event(self, *a, **kw):
        raise RuntimeError("db down")

    def fail_event(self, *a, **kw):
        raise RuntimeError("db down")


def test_traced_swallows_repo_errors_and_still_runs_agent():
    repo = ExplodingTraceRepo()

    def agent(state):
        state.user_query = "ran-anyway"
        return state

    wrapped = traced("profile", 0, lambda r, s: {}, repository=repo)(agent)

    state = AgentState(user_query="hi", trace_run_id=1)
    result = wrapped(state)

    assert result.user_query == "ran-anyway"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_agent_tracer.py::test_traced_swallows_repo_errors_and_still_runs_agent -v`
Expected: FAIL — `RuntimeError: db down`.

- [ ] **Step 3: Wrap repo calls in safety net**

Update `services/tracing/agent_tracer.py`:

```python
import logging

logger = logging.getLogger(__name__)


def _safe(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except Exception as exc:
        logger.warning("trace persistence failed: %r", exc)
        return None
```

Then update `wrapped`:

```python
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            event_id = _safe(repo.start_event, run_id, stage, sequence)
            try:
                result = agent_fn(state)
            except Exception as exc:
                if event_id is not None:
                    _safe(repo.fail_event, event_id, repr(exc))
                raise
            try:
                output_json = output_extractor(result, state)
            except Exception as exc:
                output_json = {"_extractor_error": repr(exc)}
            if event_id is not None:
                _safe(repo.complete_event, event_id, output_json)
            return result
```

- [ ] **Step 4: Run all tracer tests**

Run: `pytest tests/services/tracing/test_agent_tracer.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/agent_tracer.py tests/services/tracing/test_agent_tracer.py
git commit -m "feat(tracing): traced() never lets observability errors break a run"
```

---

### Task 6: Extractors — `profile` stage

**Files:**
- Create: `services/tracing/extractors.py`
- Create: `tests/services/tracing/test_extractors.py`

- [ ] **Step 1: Write the failing test**

```python
from agents.models import StudentProfile
from state import AgentState
from services.tracing.extractors import extract_profile


def test_extract_profile_returns_dumped_student_profile():
    profile = StudentProfile(total_score=27.0, preferred_majors=["cntt"])
    state_after = AgentState(user_query="hi", student_profile=profile)
    state_before = AgentState(user_query="hi")

    result = extract_profile(state_after, state_before)

    assert isinstance(result, dict)
    assert "student_profile" in result
    assert result["student_profile"]["total_score"] == 27.0
    assert result["student_profile"]["preferred_majors"] == ["cntt"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_extractors.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Create `services/tracing/extractors.py`:

```python
def extract_profile(result, state):
    return {"student_profile": result.student_profile.model_dump(mode="json")}
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_extractors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/extractors.py tests/services/tracing/test_extractors.py
git commit -m "feat(tracing): extract_profile dumps the student profile"
```

---

### Task 7: Extractors — `retrieve` stage

**Files:**
- Modify: `services/tracing/extractors.py`
- Modify: `tests/services/tracing/test_extractors.py`

- [ ] **Step 1: Write the failing test**

```python
from agents.models import CandidateProgram


def test_extract_candidates_includes_count_and_list():
    candidates = [
        CandidateProgram(school_id="vnu_uet", program_name="CNTT"),
        CandidateProgram(school_id="hust",    program_name="KHMT"),
    ]
    state = AgentState(user_query="hi", retrieved_programs=candidates)

    result = extract_candidates(state, state)

    assert result["count"] == 2
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["program_name"] == "CNTT"
```

Add the import: `from services.tracing.extractors import extract_candidates`.

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_extractors.py::test_extract_candidates_includes_count_and_list -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Append to `services/tracing/extractors.py`:

```python
def extract_candidates(result, state):
    candidates = result.retrieved_programs or []
    return {
        "count": len(candidates),
        "candidates": [c.model_dump(mode="json") for c in candidates],
    }
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/services/tracing/test_extractors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/extractors.py tests/services/tracing/test_extractors.py
git commit -m "feat(tracing): extract_candidates summarizes retrieval output"
```

---

### Task 8: Extractors — `conflict`, `reason`, `policy`, `explain`

**Files:**
- Modify: `services/tracing/extractors.py`
- Modify: `tests/services/tracing/test_extractors.py`

- [ ] **Step 1: Write the failing test for all four**

```python
from agents.models import (
    EligibilityCheck,
    Evidence,
    PolicyDecision,
    RankedRecommendation,
)
from services.conflict.models import ResolutionOutcome
from services.tracing.extractors import (
    extract_conflicts,
    extract_reasoning,
    extract_policy,
    extract_explanation,
)


def test_extract_conflicts_returns_resolution_outcomes():
    state = AgentState(
        user_query="hi",
        resolution_outcomes=[
            ResolutionOutcome(
                conflict_key="quota:cs:hust",
                field_name="quota",
                status="resolved",
                resolved_value="120",
                rationale="latest source",
                uncertainty_reason=None,
            ),
        ],
    )

    result = extract_conflicts(state, state)

    assert len(result["resolution_outcomes"]) == 1
    assert result["resolution_outcomes"][0]["conflict_key"] == "quota:cs:hust"


def test_extract_reasoning_returns_eligibility_and_ranked():
    state = AgentState(
        user_query="hi",
        eligibility_checks=[EligibilityCheck(candidate_id="x", eligible=True, risks=[], confidence=0.9)],
        ranked_recommendations=[RankedRecommendation(candidate_id="x", band="match", score=0.8, summary="ok")],
    )

    result = extract_reasoning(state, state)

    assert len(result["eligibility_checks"]) == 1
    assert len(result["ranked_recommendations"]) == 1


def test_extract_policy_returns_decision_and_recommendations():
    state = AgentState(
        user_query="hi",
        policy_decision=PolicyDecision(allow_answer=True, blocked_claims=[], warnings=[], policy_flags=[]),
        ranked_recommendations=[RankedRecommendation(candidate_id="y", band="reach", score=0.4, summary="risky")],
    )

    result = extract_policy(state, state)

    assert result["policy_decision"]["allow_answer"] is True
    assert len(result["filtered_recommendations"]) == 1


def test_extract_explanation_returns_final_answer_and_evidence():
    state = AgentState(
        user_query="hi",
        final_answer="Here is your recommendation.",
        citations=[Evidence(source_url="https://x", school_name="UET", field_name="quota",
                            normalized_value="120", confidence_score=0.9)],
    )

    result = extract_explanation(state, state)

    assert result["final_answer"] == "Here is your recommendation."
    assert len(result["evidence"]) == 1
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/services/tracing/test_extractors.py -v`
Expected: FAIL — `ImportError` for the four new extractors.

- [ ] **Step 3: Implement the four extractors**

Append to `services/tracing/extractors.py`:

```python
def extract_conflicts(result, state):
    return {
        "resolution_outcomes": [r.model_dump(mode="json") for r in result.resolution_outcomes or []],
    }


def extract_reasoning(result, state):
    return {
        "eligibility_checks": [c.model_dump(mode="json") for c in result.eligibility_checks or []],
        "ranked_recommendations": [r.model_dump(mode="json") for r in result.ranked_recommendations or []],
    }


def extract_policy(result, state):
    decision = result.policy_decision
    return {
        "policy_decision": decision.model_dump(mode="json") if decision else None,
        "filtered_recommendations": [r.model_dump(mode="json") for r in result.ranked_recommendations or []],
    }


def extract_explanation(result, state):
    return {
        "final_answer": result.final_answer or "",
        "evidence": [e.model_dump(mode="json") for e in result.citations or []],
    }
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/services/tracing/test_extractors.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```powershell
git add services/tracing/extractors.py tests/services/tracing/test_extractors.py
git commit -m "feat(tracing): conflict/reason/policy/explain extractors"
```

---

### Task 9: Wire `traced()` into `graph.py`

**Files:**
- Modify: `graph.py`
- Test: covered by the integration test in Task 10.

- [ ] **Step 1: Update `graph.py`**

Replace the file with:

```python
from langgraph.graph import StateGraph

from state import AgentState

from agents.profile_agent import profile_agent
from agents.retrieval_agent import retrieval_agent
from agents.conflict_agent import conflict_agent
from agents.reasoning_agent import reasoning_agent
from agents.policy_agent import policy_agent
from agents.explanation_agent import explanation_agent

from services.tracing.agent_tracer import traced
from services.tracing.extractors import (
    extract_profile,
    extract_candidates,
    extract_conflicts,
    extract_reasoning,
    extract_policy,
    extract_explanation,
)


builder = StateGraph(AgentState)

builder.add_node("profile",  traced("profile",  0, extract_profile)(profile_agent))
builder.add_node("retrieve", traced("retrieve", 1, extract_candidates)(retrieval_agent))
builder.add_node("conflict", traced("conflict", 2, extract_conflicts)(conflict_agent))
builder.add_node("reason",   traced("reason",   3, extract_reasoning)(reasoning_agent))
builder.add_node("policy",   traced("policy",   4, extract_policy)(policy_agent))
builder.add_node("explain",  traced("explain",  5, extract_explanation)(explanation_agent))


builder.set_entry_point("profile")

builder.add_edge("profile", "retrieve")
builder.add_edge("retrieve", "conflict")
builder.add_edge("conflict", "reason")
builder.add_edge("reason", "policy")
builder.add_edge("policy", "explain")


graph = builder.compile()
```

- [ ] **Step 2: Run the existing non-integration test suite**

Run: `pytest -m "not integration"`
Expected: PASS. Because `traced()` bypasses when `trace_run_id is None`, every existing test that invokes the graph keeps working.

- [ ] **Step 3: Commit**

```powershell
git add graph.py
git commit -m "feat(graph): wrap every agent node with traced() decorator"
```

---

### Task 10: End-to-end integration test (real DB + real graph, mocked agents)

**Files:**
- Create: `tests/services/tracing/test_graph_tracing_integration.py`

This test confirms that running the graph with `trace_run_id` set causes 6 rows to land in `advisory_trace_events`. It mocks the actual agent function bodies to keep the test fast (no Gemini calls).

- [ ] **Step 1: Write the integration test**

```python
import pytest
from unittest.mock import patch

from agents.models import (
    CandidateProgram,
    EligibilityCheck,
    PolicyDecision,
    RankedRecommendation,
    StudentProfile,
)
from services.chat.db import get_db_connection
from services.tracing.trace_repository import TraceRepository
from state import AgentState
from graph import graph


@pytest.fixture
def seeded_run_id():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO chat_sessions (session_token) VALUES (%s) RETURNING id",
                ("trace-graph-int",))
    session_id = cur.fetchone()[0]
    cur.execute("INSERT INTO chat_advisory_runs (session_id) VALUES (%s) RETURNING id",
                (session_id,))
    run_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    yield run_id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
    conn.commit()
    cur.close()
    conn.close()


def _stub_state_returning(updates):
    def stub(state):
        for key, value in updates.items():
            setattr(state, key, value)
        return state
    return stub


@pytest.mark.integration
def test_graph_writes_six_trace_events_when_trace_run_id_set(seeded_run_id):
    state = AgentState(
        user_query="Em duoc 27 diem",
        student_profile=StudentProfile(total_score=27.0),
        profile_seeded=True,
        trace_run_id=seeded_run_id,
    )

    with patch("graph.profile_agent",     _stub_state_returning({})), \
         patch("graph.retrieval_agent",   _stub_state_returning({"retrieved_programs":
                                                                 [CandidateProgram(school_id="x", program_name="y")]})), \
         patch("graph.conflict_agent",    _stub_state_returning({"resolution_outcomes": []})), \
         patch("graph.reasoning_agent",   _stub_state_returning({"eligibility_checks":
                                                                 [EligibilityCheck(candidate_id="x", eligible=True, risks=[], confidence=0.9)],
                                                                 "ranked_recommendations":
                                                                 [RankedRecommendation(candidate_id="x", band="match", score=0.8, summary="ok")]})), \
         patch("graph.policy_agent",      _stub_state_returning({"policy_decision":
                                                                 PolicyDecision(allow_answer=True, blocked_claims=[], warnings=[], policy_flags=[])})), \
         patch("graph.explanation_agent", _stub_state_returning({"final_answer": "Done."})):
        graph.invoke(state)

    repo = TraceRepository()
    events = repo.list_events_for_run(seeded_run_id)

    assert [e["stage"] for e in events] == ["profile", "retrieve", "conflict", "reason", "policy", "explain"]
    assert all(e["status"] == "completed" for e in events)
    assert all(e["duration_ms"] is not None for e in events)
    assert all(e["output_json"] is not None for e in events)
```

- [ ] **Step 2: Note about patch targets**

LangGraph nodes already-wrapped reference the original agent symbol bound inside the `add_node(... )(...)` call, so the patch above only works if the graph imports each agent by name. The current `graph.py` does — that's why `patch("graph.profile_agent", ...)` is the right target. The wrapper sees the patched function because the wrapper closes over `agent_fn` at *call time*: the `add_node` call captures the reference once at import. ❗ This means `patch` happens too late.

To make this test robust, an alternative is to mock at the `graph` object level using LangGraph's `aupdate_state` or to refactor `graph.py` to look up agents from a registry. For this slice, the simpler path is:

- Re-build the graph inside the test with the stubbed agents.

Replace the test body's graph use with:

```python
from langgraph.graph import StateGraph
from services.tracing.agent_tracer import traced
from services.tracing.extractors import (
    extract_profile, extract_candidates, extract_conflicts,
    extract_reasoning, extract_policy, extract_explanation,
)

def _build_test_graph(stubs):
    b = StateGraph(AgentState)
    b.add_node("profile",  traced("profile",  0, extract_profile)(stubs["profile"]))
    b.add_node("retrieve", traced("retrieve", 1, extract_candidates)(stubs["retrieve"]))
    b.add_node("conflict", traced("conflict", 2, extract_conflicts)(stubs["conflict"]))
    b.add_node("reason",   traced("reason",   3, extract_reasoning)(stubs["reason"]))
    b.add_node("policy",   traced("policy",   4, extract_policy)(stubs["policy"]))
    b.add_node("explain",  traced("explain",  5, extract_explanation)(stubs["explain"]))
    b.set_entry_point("profile")
    b.add_edge("profile", "retrieve")
    b.add_edge("retrieve", "conflict")
    b.add_edge("conflict", "reason")
    b.add_edge("reason", "policy")
    b.add_edge("policy", "explain")
    return b.compile()
```

Then rewrite the test:

```python
@pytest.mark.integration
def test_graph_writes_six_trace_events_when_trace_run_id_set(seeded_run_id):
    stubs = {
        "profile":  _stub_state_returning({}),
        "retrieve": _stub_state_returning({"retrieved_programs":
                                           [CandidateProgram(school_id="x", program_name="y")]}),
        "conflict": _stub_state_returning({"resolution_outcomes": []}),
        "reason":   _stub_state_returning({
            "eligibility_checks": [EligibilityCheck(candidate_id="x", eligible=True, risks=[], confidence=0.9)],
            "ranked_recommendations": [RankedRecommendation(candidate_id="x", band="match", score=0.8, summary="ok")],
        }),
        "policy":   _stub_state_returning({"policy_decision":
                                           PolicyDecision(allow_answer=True, blocked_claims=[], warnings=[], policy_flags=[])}),
        "explain":  _stub_state_returning({"final_answer": "Done."}),
    }
    g = _build_test_graph(stubs)

    state = AgentState(
        user_query="Em duoc 27 diem",
        student_profile=StudentProfile(total_score=27.0),
        profile_seeded=True,
        trace_run_id=seeded_run_id,
    )
    g.invoke(state)

    repo = TraceRepository()
    events = repo.list_events_for_run(seeded_run_id)

    assert [e["stage"] for e in events] == ["profile", "retrieve", "conflict", "reason", "policy", "explain"]
    assert all(e["status"] == "completed" for e in events)
    assert all(e["duration_ms"] is not None for e in events)
    assert all(e["output_json"] is not None for e in events)
```

- [ ] **Step 3: Run the integration test**

Run:
```powershell
docker compose up -d --wait db
pytest tests/services/tracing/test_graph_tracing_integration.py -m integration -v
```
Expected: PASS.

- [ ] **Step 4: Run the full non-integration suite**

Run: `pytest -m "not integration"`
Expected: PASS — no regression.

- [ ] **Step 5: Commit**

```powershell
git add tests/services/tracing/test_graph_tracing_integration.py
git commit -m "test(tracing): integration test confirms 6 trace events per run"
```

---

## Slice 02 Done When

- `traced()` decorator handles: bypass, success, agent-error, extractor-error, repo-error — all unit-tested.
- All 6 extractors produce JSON-serializable dicts for representative state.
- `graph.py` wraps every node with `traced()`.
- Integration test confirms 6 rows land in `advisory_trace_events` per run when `trace_run_id` is set.
- `pytest -m "not integration"` passes; `pytest -m integration` passes with docker DB up.

Next slice: [03 — Trace API endpoint](./03-trace-api-endpoint.md).
