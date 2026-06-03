# Student Advisory Chat V1 - Phase 4: Asynchronous Advisory Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the current advisory graph with seeded chat profile state, persist run artifacts, and dispatch full analysis asynchronously once a session is ready.

**Architecture:** Extend `AgentState` and `profile_agent` so the graph can reuse persisted profile state instead of re-extracting it from a single query. Build a thin `advisory_runner` adapter and an in-process `RunDispatcher` that persists run status and assistant result messages without introducing a second recommendation pipeline.

**Tech Stack:** Python, LangGraph, existing advisory agents, `concurrent.futures`, PostgreSQL, `pytest`, `monkeypatch`

---

## Planned File Structure

- `state.py`
  - Add a `profile_seeded` flag for chat-backed advisory runs.
- `agents/profile_agent.py`
  - Short-circuit profile extraction when profile state is already persisted.
- `services/chat/advisory_runner.py`
  - Translate chat profile state into `AgentState` and call `graph.invoke`.
- `services/chat/run_dispatcher.py`
  - Submit and persist background advisory runs.

### Task 1: Allow The Existing Graph To Reuse Seeded Profile State

**Files:**
- Modify: `state.py`
- Modify: `agents/profile_agent.py`
- Create: `services/chat/advisory_runner.py`
- Test: `tests/agents/test_profile_agent.py`
- Create: `tests/services/chat/test_advisory_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
import agents.profile_agent as profile_agent_module
from agents.models import StudentProfile
from state import AgentState


def test_profile_agent_reuses_seeded_student_profile(monkeypatch):
    seeded = StudentProfile(
        total_score=27.0,
        preferred_majors=["computer_science"],
        location_preference="Ha Noi",
        missing_slots=[],
    )

    monkeypatch.setattr(
        profile_agent_module,
        "build_profile_with_gateway",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected call")),
    )

    state = AgentState(
        user_query="ignored",
        admission_year=2026,
        student_profile=seeded,
        profile_seeded=True,
    )

    result = profile_agent_module.profile_agent(state)

    assert result.student_profile == seeded
    assert result.retrieval_missing_data == []
```

```python
from services.chat.advisory_runner import run_advisory_for_session
from services.chat.models import ChatProfileState


def test_run_advisory_for_session_seeds_agent_state(monkeypatch):
    captured = {}

    def fake_invoke(state):
        captured["state"] = state
        return {"final_answer": "ok"}

    monkeypatch.setattr("services.chat.advisory_runner.graph.invoke", fake_invoke)

    run_advisory_for_session(
        ChatProfileState(
            admission_year=2026,
            total_score=27.0,
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
        latest_user_message="Em duoc 27 diem va muon hoc CNTT",
    )

    assert captured["state"].profile_seeded is True
    assert captured["state"].student_profile.total_score == 27.0
    assert captured["state"].admission_year == 2026
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_profile_agent.py::test_profile_agent_reuses_seeded_student_profile tests/services/chat/test_advisory_runner.py -v`
Expected: FAIL because `AgentState` has no `profile_seeded` field and `services.chat.advisory_runner` does not exist yet

- [ ] **Step 3: Write minimal implementation**

```python
# state.py
class AgentState(BaseModel):
    user_query: str
    chat_history: List[str] = Field(default_factory=list)
    intent: Optional[str] = None
    admission_year: int = ADMISSION_YEAR
    profile_seeded: bool = False
```

```python
# agents/profile_agent.py
from services import build_default_gateway
from services.profile_inference_service import build_profile_with_gateway
from state import AgentState


def profile_agent(state: AgentState):
    if state.profile_seeded:
        state.retrieval_missing_data = list(state.student_profile.missing_slots)
        return state

    gateway = build_default_gateway()
    state.student_profile = build_profile_with_gateway(state.user_query, gateway)
    state.retrieval_missing_data = list(state.student_profile.missing_slots)
    return state
```

```python
# services/chat/advisory_runner.py
from agents.models import StudentProfile
from graph import graph
from state import AgentState


def run_advisory_for_session(profile_state, latest_user_message: str):
    student_profile = StudentProfile(
        total_score=profile_state.total_score,
        subject_combination=profile_state.subject_combination,
        preferred_majors=profile_state.preferred_majors,
        preferred_schools=profile_state.preferred_schools,
        location_preference=profile_state.location_preference,
        tuition_budget=profile_state.tuition_budget,
        constraints=profile_state.constraints,
        missing_slots=profile_state.missing_slots,
    )
    state = AgentState(
        user_query=latest_user_message,
        admission_year=profile_state.admission_year or 2026,
        student_profile=student_profile,
        profile_seeded=True,
    )
    return graph.invoke(state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_profile_agent.py::test_profile_agent_reuses_seeded_student_profile tests/services/chat/test_advisory_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add state.py agents/profile_agent.py services/chat/advisory_runner.py tests/agents/test_profile_agent.py tests/services/chat/test_advisory_runner.py
git commit -m "feat: allow advisory graph to reuse seeded chat profile"
```

### Task 2: Add Run Persistence, Dispatcher, And Automatic Background Execution

**Files:**
- Modify: `services/chat/models.py`
- Modify: `services/chat/repository.py`
- Modify: `services/chat/conversation_service.py`
- Create: `services/chat/run_dispatcher.py`
- Modify: `web/routes/chat_api.py`
- Test: `tests/services/chat/test_run_dispatcher.py`
- Test: `tests/e2e/test_chat_session_run_flow.py`

- [ ] **Step 1: Write the failing test**

```python
from services.chat.models import ChatProfileState
from services.chat.run_dispatcher import RunDispatcher


class FakeRepository:
    def __init__(self):
        self.completed = None
        self.messages = []
        self.status = None

    def mark_run_running(self, run_id):
        self.status = ("running", run_id)

    def complete_run(self, run_id, result_json, final_answer):
        self.completed = (run_id, result_json, final_answer)

    def append_message(self, session_token, role, content, kind="chat"):
        self.messages.append((session_token, role, kind, content))

    def update_session_status(self, session_token, status):
        self.status = (status, session_token)


class InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def test_dispatcher_completes_run_and_posts_result_message():
    repo = FakeRepository()
    dispatcher = RunDispatcher(
        repository=repo,
        runner=lambda profile_state, latest_user_message: {"final_answer": "De xuat phu hop"},
        executor=InlineExecutor(),
    )

    dispatcher.submit(
        session_token="session-123",
        run_id=7,
        latest_user_message="Em duoc 27 diem",
        profile_state=ChatProfileState(
            admission_year=2026,
            total_score=27.0,
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
    )

    assert repo.completed[0] == 7
    assert repo.completed[2] == "De xuat phu hop"
    assert repo.messages[-1][2] == "assistant_result"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/chat/test_run_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.chat.run_dispatcher'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/chat/models.py
from typing import Any, Dict, Optional


class AdvisoryRunRecord(BaseModel):
    id: int
    session_token: str
    status: str
    result_json: Optional[Dict[str, Any]] = None
    final_answer: Optional[str] = None
```

```python
# services/chat/repository.py
    def create_run(self, session_token: str, profile_state):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chat_advisory_runs (session_id, profile_snapshot_json)
            SELECT id, %s
            FROM chat_sessions
            WHERE session_token = %s
            RETURNING id
            """,
            (profile_state.model_dump(mode="json"), session_token),
        )
        run_id = cur.fetchone()[0]
        cur.execute(
            """
            UPDATE chat_sessions
            SET latest_run_id = %s, status = 'running', updated_at = NOW()
            WHERE session_token = %s
            """,
            (run_id, session_token),
        )
        conn.commit()
        cur.close()
        conn.close()
        return run_id

    def mark_run_running(self, run_id: int):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE chat_advisory_runs
            SET status = 'running', started_at = NOW()
            WHERE id = %s
            """,
            (run_id,),
        )
        conn.commit()
        cur.close()
        conn.close()

    def complete_run(self, run_id: int, result_json, final_answer: str):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE chat_advisory_runs
            SET status = 'completed', result_json = %s, final_answer = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (result_json, final_answer, run_id),
        )
        conn.commit()
        cur.close()
        conn.close()

    def update_session_status(self, session_token: str, status: str):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE chat_sessions
            SET status = %s, updated_at = NOW()
            WHERE session_token = %s
            """,
            (status, session_token),
        )
        conn.commit()
        cur.close()
        conn.close()
```

```python
# services/chat/run_dispatcher.py
from concurrent.futures import ThreadPoolExecutor

from services.chat.advisory_runner import run_advisory_for_session
from services.chat.repository import ChatSessionRepository


class RunDispatcher:
    def __init__(self, repository=None, runner=None, executor=None):
        self.repository = repository or ChatSessionRepository()
        self.runner = runner or run_advisory_for_session
        self.executor = executor or ThreadPoolExecutor(max_workers=2)

    def submit(self, session_token: str, run_id: int, latest_user_message: str, profile_state):
        self.executor.submit(
            self._execute,
            session_token,
            run_id,
            latest_user_message,
            profile_state,
        )

    def _execute(self, session_token: str, run_id: int, latest_user_message: str, profile_state):
        self.repository.mark_run_running(run_id)
        try:
            result = self.runner(profile_state, latest_user_message)
            final_answer = result.get("final_answer") or result.get("advisory") or ""
            self.repository.complete_run(run_id, result, final_answer)
            self.repository.append_message(session_token, "assistant", final_answer, "assistant_result")
            self.repository.update_session_status(session_token, "completed")
        except Exception as exc:
            self.repository.append_message(
                session_token,
                "assistant",
                "Xin loi, qua trinh phan tich bi gian doan. Ban hay thu lai.",
                "assistant_error",
            )
            self.repository.update_session_status(session_token, "failed")
            raise exc
```

```python
# web/routes/chat_api.py
from services.chat.run_dispatcher import RunDispatcher


def get_run_dispatcher():
    return RunDispatcher()


@router.post("/{session_token}/messages")
def post_message(session_token: str, payload: ChatMessageCreate):
    service = get_conversation_service()
    result = service.handle_user_message(session_token, payload.content)
    if result.should_start_run:
        repo = service.repository
        run_id = repo.create_run(session_token, result.profile_state)
        get_run_dispatcher().submit(
            session_token=session_token,
            run_id=run_id,
            latest_user_message=payload.content,
            profile_state=result.profile_state,
        )
    return result.model_dump()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/services/chat/test_run_dispatcher.py tests/e2e/test_chat_session_run_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/models.py services/chat/repository.py services/chat/run_dispatcher.py web/routes/chat_api.py tests/services/chat/test_run_dispatcher.py tests/e2e/test_chat_session_run_flow.py
git commit -m "feat: add asynchronous chat advisory runs"
```

## Self-Review

Spec coverage in this plan:
- Background advisory execution: covered by Task 2.
- Reuse of the existing advisory core: covered by Task 1.
- Run history and persisted artifacts: covered by Task 2.

Intentional exclusions from this plan:
- No public HTML page yet.
- No browser-side session persistence yet.

Plan complete and saved to `docs/superpowers/plans/2026-05-01-student-advisory-chat-v1/04-asynchronous-advisory-runs.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
