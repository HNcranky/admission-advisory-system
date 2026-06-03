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
