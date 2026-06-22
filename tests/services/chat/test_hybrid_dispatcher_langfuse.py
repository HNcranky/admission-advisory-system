import contextlib

from services.chat import hybrid_dispatcher as hd
from services.chat.hybrid_dispatcher import HybridDispatcher
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState


class FakeRepository:
    def __init__(self):
        self.completed = None
        self.messages = []

    def mark_run_running(self, run_id):
        pass

    def complete_run(self, run_id, result_json, final_answer):
        self.completed = (run_id, result_json, final_answer)

    def append_message(self, session_token, role, content, kind="chat"):
        self.messages.append((session_token, role, kind, content))

    def update_session_status(self, session_token, status):
        pass


class FakeOrchestrator:
    def run(self, intent, profile_state, content, trace_run_id=None):
        return "SYNTH"


def test_hybrid_execute_opens_advisory_run_trace(monkeypatch):
    captured = {}

    @contextlib.contextmanager
    def fake_trace(run_id, session_token, user_message, intent=None, admission_year=None):
        captured["args"] = (run_id, session_token, user_message)
        captured["intent"] = intent
        yield None

    monkeypatch.setattr(hd, "advisory_run_trace", fake_trace)

    dispatcher = HybridDispatcher(repository=FakeRepository(), orchestrator=FakeOrchestrator())
    dispatcher.execute(
        session_token="s", run_id=5, content="hi",
        profile_state=ChatProfileState(admission_year=2026),
        intent=IntentResult(route="HYBRID", schools=[], topics=[], needs_advisory=True),
    )

    assert captured["args"] == (5, "s", "hi")
    assert captured["intent"] == "HYBRID"
    assert dispatcher.repository.completed[0] == 5
