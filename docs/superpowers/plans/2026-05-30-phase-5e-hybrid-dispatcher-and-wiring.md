# Phase 5e — HybridDispatcher + Wiring + Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the hybrid comparison end-to-end: a background `HybridDispatcher` that drives the `CompareOrchestrator` and persists the synthesized answer (mirroring `RunDispatcher`), the chat route picking the dispatcher by `run_kind`, and acceptance integration tests covering full-data / one-branch-missing / both-missing.

**Architecture:** `HybridDispatcher` submits to a `ThreadPoolExecutor`, calls `CompareOrchestrator.run(...)`, then `complete_run` + `append_message` + `update_session_status("completed")` — identical lifecycle to `RunDispatcher`, so the existing frontend polling surfaces the answer unchanged. The route reconstructs the `IntentResult` from `result.hybrid_intent` and hands it to the dispatcher.

**Tech Stack:** Python, `concurrent.futures.ThreadPoolExecutor`, FastAPI, pytest.

**Spec:** [`../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md`](../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md) — flow, Error handling, Acceptance Criteria.

**Depends on:** Phase 5c (`CompareOrchestrator`), Phase 5d (`ConversationTurnResult.run_kind`/`hybrid_intent`).

---

### Task 1: `HybridDispatcher`

**Files:**
- Create: `services/chat/hybrid_dispatcher.py`
- Test: `tests/services/chat/test_hybrid_dispatcher.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/chat/test_hybrid_dispatcher.py`:

```python
import pytest

from services.chat.hybrid_dispatcher import HybridDispatcher
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState


class FakeRepository:
    def __init__(self):
        self.completed = None
        self.messages = []
        self.status = None
        self.running = None

    def mark_run_running(self, run_id):
        self.running = run_id

    def complete_run(self, run_id, result_json, final_answer):
        self.completed = (run_id, result_json, final_answer)

    def append_message(self, session_token, role, content, kind="chat"):
        self.messages.append((session_token, role, kind, content))

    def update_session_status(self, session_token, status):
        self.status = (status, session_token)


class FakeOrchestrator:
    def __init__(self, answer="SYNTH ANSWER", raise_exc=False):
        self._answer = answer
        self._raise = raise_exc
        self.calls = []

    def run(self, intent, profile_state, content, trace_run_id=None):
        self.calls.append({"intent": intent, "content": content, "trace_run_id": trace_run_id})
        if self._raise:
            raise RuntimeError("orchestrator boom")
        return self._answer


class InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def _intent():
    return IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"], needs_advisory=True)


def test_dispatcher_runs_orchestrator_and_persists_answer():
    repo = FakeRepository()
    orch = FakeOrchestrator(answer="Tổng hợp xong")
    dispatcher = HybridDispatcher(repository=repo, orchestrator=orch, executor=InlineExecutor())

    dispatcher.submit(
        session_token="s1", run_id=42, content="so sánh UET và HUST",
        profile_state=ChatProfileState(total_score=27.0), intent=_intent(),
    )

    assert repo.running == 42
    assert orch.calls[0]["trace_run_id"] == 42
    assert repo.completed[0] == 42
    assert repo.completed[2] == "Tổng hợp xong"
    assert repo.messages[-1] == ("s1", "assistant", "assistant_result", "Tổng hợp xong")
    assert repo.status == ("completed", "s1")


def test_dispatcher_marks_failed_and_reraises_on_orchestrator_error():
    repo = FakeRepository()
    orch = FakeOrchestrator(raise_exc=True)
    dispatcher = HybridDispatcher(repository=repo, orchestrator=orch, executor=InlineExecutor())

    with pytest.raises(RuntimeError):
        dispatcher.submit(
            session_token="s2", run_id=9, content="q",
            profile_state=ChatProfileState(), intent=_intent(),
        )

    assert repo.messages[-1][2] == "assistant_error"
    assert repo.status == ("failed", "s2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_hybrid_dispatcher.py -v`
Expected: FAIL — `ModuleNotFoundError: services.chat.hybrid_dispatcher`.

- [ ] **Step 3: Implement the dispatcher**

Create `services/chat/hybrid_dispatcher.py`:

```python
from concurrent.futures import ThreadPoolExecutor

from services.chat.compare_orchestrator import CompareOrchestrator
from services.chat.repository import ChatSessionRepository


class HybridDispatcher:
    def __init__(self, repository=None, orchestrator=None, executor=None):
        self.repository = repository or ChatSessionRepository()
        self.orchestrator = orchestrator or CompareOrchestrator()
        self.executor = executor or ThreadPoolExecutor(max_workers=2)

    def submit(self, session_token: str, run_id: int, content: str, profile_state, intent):
        self.executor.submit(self._execute, session_token, run_id, content, profile_state, intent)

    def _execute(self, session_token: str, run_id: int, content: str, profile_state, intent):
        self.repository.mark_run_running(run_id)
        try:
            answer = self.orchestrator.run(intent, profile_state, content, trace_run_id=run_id)
            self.repository.complete_run(run_id, {"final_answer": answer, "kind": "hybrid"}, answer)
            self.repository.append_message(session_token, "assistant", answer, "assistant_result")
            self.repository.update_session_status(session_token, "completed")
        except Exception as exc:
            self.repository.append_message(
                session_token,
                "assistant",
                "Xin loi, qua trinh tong hop bi gian doan. Ban hay thu lai.",
                "assistant_error",
            )
            self.repository.update_session_status(session_token, "failed")
            raise exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_hybrid_dispatcher.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/chat/hybrid_dispatcher.py tests/services/chat/test_hybrid_dispatcher.py
git commit -m "feat(hybrid): HybridDispatcher drives CompareOrchestrator as a background run"
```

---

### Task 2: Route wiring — pick the dispatcher by `run_kind`

**Files:**
- Modify: `web/routes/chat_api.py`
- Test: `tests/web/test_chat_session_api.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/web/test_chat_session_api.py`:

```python
def test_post_message_dispatches_hybrid_run(monkeypatch):
    from services.chat.models import ConversationTurnResult

    client = TestClient(build_app())

    class FakeRepository:
        def create_run(self, session_token, profile_state):
            return 55

    class FakeService:
        def __init__(self):
            self.repository = FakeRepository()

        def handle_user_message(self, session_token, content):
            return ConversationTurnResult(
                session_status="running",
                assistant_message="đang tổng hợp",
                should_start_run=True,
                run_kind="hybrid",
                hybrid_intent={"route": "HYBRID", "schools": ["VNU-UET", "HUST"],
                               "topics": ["tuition"], "needs_advisory": True},
                profile_state=ChatProfileState(
                    admission_year=2026, total_score=27.0,
                    preferred_majors=["computer_science"], location_preference="Ha Noi",
                ),
            )

    captured = {}

    class FakeHybridDispatcher:
        def submit(self, session_token, run_id, content, profile_state, intent):
            captured["run_id"] = run_id
            captured["intent_schools"] = intent.schools
            captured["content"] = content

    class FailRunDispatcher:
        def submit(self, **kwargs):
            raise AssertionError("advisory dispatcher must not be used for a hybrid run")

    monkeypatch.setattr("web.routes.chat_api.get_conversation_service", lambda: FakeService())
    monkeypatch.setattr("web.routes.chat_api.get_hybrid_dispatcher", lambda: FakeHybridDispatcher())
    monkeypatch.setattr("web.routes.chat_api.get_run_dispatcher", lambda: FailRunDispatcher())

    response = client.post("/api/sessions/s/messages", json={"content": "so sánh UET và HUST"})

    assert response.status_code == 200
    assert response.json()["run_kind"] == "hybrid"
    assert captured["run_id"] == 55
    assert captured["intent_schools"] == ["VNU-UET", "HUST"]
    assert captured["content"] == "so sánh UET và HUST"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_chat_session_api.py::test_post_message_dispatches_hybrid_run -v`
Expected: FAIL — `get_hybrid_dispatcher` does not exist and the route always uses `get_run_dispatcher`.

- [ ] **Step 3: Wire the route**

In `web/routes/chat_api.py`:

(a) Extend imports at the top:

```python
from services.chat.hybrid_dispatcher import HybridDispatcher
from services.chat.intent_router import IntentResult
```

(b) Add a dispatcher factory next to `get_run_dispatcher`:

```python
def get_hybrid_dispatcher():
    return HybridDispatcher()
```

(c) Replace the body of `post_message`'s `if result.should_start_run:` block with:

```python
    if result.should_start_run:
        repo = service.repository
        run_id = repo.create_run(session_token, result.profile_state)
        if result.run_kind == "hybrid":
            intent = IntentResult.model_validate(result.hybrid_intent or {"route": "HYBRID"})
            get_hybrid_dispatcher().submit(
                session_token=session_token,
                run_id=run_id,
                content=payload.content,
                profile_state=result.profile_state,
                intent=intent,
            )
        else:
            get_run_dispatcher().submit(
                session_token=session_token,
                run_id=run_id,
                latest_user_message=payload.content,
                profile_state=result.profile_state,
            )
    return result.model_dump()
```

- [ ] **Step 4: Run the web suite**

Run: `python -m pytest tests/web/test_chat_session_api.py -v`
Expected: PASS — the new hybrid test plus the existing advisory `test_post_message_returns_ready_payload` (still routes through `get_run_dispatcher`, since its `run_kind` defaults to `"advisory"`).

- [ ] **Step 5: Commit**

```bash
git add web/routes/chat_api.py tests/web/test_chat_session_api.py
git commit -m "feat(chat-api): route hybrid runs to HybridDispatcher by run_kind"
```

---

### Task 3: Acceptance integration — full / one-missing / both-missing

**Files:**
- Create: `tests/services/chat/test_hybrid_integration.py`

This exercises the real `CompareOrchestrator` + real `SynthesisAgent` (forced down the deterministic concatenation path with a failing gateway, so the two-section separation is asserted deterministically), with a fake advisory runner and fake KnowledgeQA.

- [ ] **Step 1: Write the failing tests**

Create `tests/services/chat/test_hybrid_integration.py`:

```python
from agents.models import Evidence
from services.chat.compare_orchestrator import CompareOrchestrator
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState
from services.chat.synthesis_agent import SynthesisAgent
from services.knowledge.models import Citation, KnowledgeQAResult


class FailingGateway:
    """Force SynthesisAgent down the deterministic concatenation path."""
    def is_available(self):
        return True

    def run(self, request):
        raise RuntimeError("llm down")


class FakeKnowledgeQA:
    def __init__(self, by_school=None):
        self._by_school = by_school or {}

    def answer(self, question, school, topic, conversation_context=""):
        return self._by_school.get(school, KnowledgeQAResult(has_data=False, confidence=0.0))


def _orchestrator(advisory_runner, knowledge_qa):
    return CompareOrchestrator(
        advisory_runner=advisory_runner,
        knowledge_qa=knowledge_qa,
        synthesis_agent=SynthesisAgent(gateway=FailingGateway()),
    )


def _intent():
    return IntentResult(
        route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"], needs_advisory=True,
    )


def _profile():
    return ChatProfileState(
        admission_year=2026, total_score=27.0,
        preferred_majors=["computer_science"], location_preference="Ha Noi",
        preferred_schools=["VNU-UET", "HUST"],
    )


def test_full_data_both_branches_separates_sections_and_sources():
    advisory_runner = lambda profile_state, content, trace_run_id=None: {
        "final_answer": "Bạn có khả năng đậu UET ngành CNTT.",
        "citations": [Evidence(source_url="https://uet/diem", school_name="VNU-UET",
                               admission_year=2026, field_name="benchmark")],
    }
    qa = FakeKnowledgeQA(by_school={
        "VNU-UET": KnowledgeQAResult(has_data=True, answer="Học phí UET ~35 triệu/năm.",
                                     citations=[Citation(source_url="https://uet/hp", chunk_text="..")], confidence=0.9),
        "HUST": KnowledgeQAResult(has_data=True, answer="Học phí HUST ~24 triệu/năm.",
                                  citations=[Citation(source_url="https://hust/hp", chunk_text="..")], confidence=0.9),
    })
    out = _orchestrator(advisory_runner, qa).run(_intent(), _profile(), "so sánh UET và HUST")

    assert "Theo dữ liệu tuyển sinh" in out          # structured section present
    assert "Thông tin trường" in out                  # knowledge section present
    assert "khả năng đậu UET" in out
    assert "35 triệu" in out and "24 triệu" in out
    assert "Nguồn:" in out
    for url in ("https://uet/diem", "https://uet/hp", "https://hust/hp"):
        assert url in out


def test_knowledge_missing_marks_that_part_only():
    advisory_runner = lambda profile_state, content, trace_run_id=None: {
        "final_answer": "Tư vấn: UET phù hợp với điểm của bạn.", "citations": [],
    }
    qa = FakeKnowledgeQA(by_school={})  # no knowledge data for any school
    out = _orchestrator(advisory_runner, qa).run(_intent(), _profile(), "q")

    assert "UET phù hợp" in out                        # advisory still answered
    assert "chưa có dữ liệu" in out.lower()            # knowledge part flagged missing


def test_advisory_missing_marks_that_part_only():
    def advisory_runner(profile_state, content, trace_run_id=None):
        raise RuntimeError("advisory graph failed")

    qa = FakeKnowledgeQA(by_school={
        "VNU-UET": KnowledgeQAResult(has_data=True, answer="Học phí UET ~35 triệu.", citations=[], confidence=0.9),
    })
    out = _orchestrator(advisory_runner, qa).run(_intent(), _profile(), "q")

    assert "35 triệu" in out                            # knowledge still answered
    assert "chưa có dữ liệu" in out.lower()            # advisory part flagged missing


def test_both_missing_produces_no_data_response_without_fabrication():
    def advisory_runner(profile_state, content, trace_run_id=None):
        return {"final_answer": "", "citations": []}

    qa = FakeKnowledgeQA(by_school={})
    out = _orchestrator(advisory_runner, qa).run(_intent(), _profile(), "q")

    assert "chưa có dữ liệu" in out.lower()
    assert "Nguồn:" not in out                          # no sources, nothing fabricated
```

- [ ] **Step 2: Run tests to verify they fail or pass**

Run: `python -m pytest tests/services/chat/test_hybrid_integration.py -v`
Expected: PASS once Phases 5b/5c are implemented (this plan adds no new production code — it is the acceptance gate). If any assertion fails, fix the relevant production file in 5b/5c, not the test.

- [ ] **Step 3: Run the full Phase 5 suite**

Run: `python -m pytest tests/services/chat tests/web/test_chat_session_api.py tests/services/inference/test_factory.py -v`
Expected: PASS — every Phase 5 unit + integration test green, and no Phase 1–4 regressions in `tests/services/chat`.

- [ ] **Step 4: Commit**

```bash
git add tests/services/chat/test_hybrid_integration.py
git commit -m "test(hybrid): acceptance integration — full / one-missing / both-missing"
```

---

## Self-Review

- **Spec coverage:** "both branches called, latency ≈ max" → covered by 5c + dispatcher driving it. "response separates structured vs knowledge" → Task 3 `test_full_data_both_branches`. "one branch missing → fallback, other answers, states missing" → Task 3 knowledge-missing + advisory-missing tests. "integration: full / one-missing / both-missing" → Task 3 four tests. "pure advisory does not trigger HYBRID" → covered by router tests in 5a. Background lifecycle parity → Task 1 mirrors `RunDispatcher`. Route picks dispatcher by `run_kind` → Task 2.
- **Placeholder scan:** None.
- **Type consistency:** `HybridDispatcher.submit(session_token, run_id, content, profile_state, intent)` matches the route call in Task 2. `orchestrator.run(intent, profile_state, content, trace_run_id=...)` matches Phase 5c. `IntentResult.model_validate(result.hybrid_intent)` consumes the dict produced by Phase 5d's `intent.model_dump()`. `complete_run(run_id, result_json, final_answer)` / `append_message` / `update_session_status` match `ChatSessionRepository`.
