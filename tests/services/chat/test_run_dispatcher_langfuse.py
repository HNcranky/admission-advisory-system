import contextlib

from services.chat import run_dispatcher as rd
from services.chat.models import ChatProfileState
from services.chat.run_dispatcher import RunDispatcher


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


def test_execute_opens_advisory_run_trace(monkeypatch):
    captured = {}

    @contextlib.contextmanager
    def fake_trace(run_id, session_token, user_message, intent=None, admission_year=None):
        captured["args"] = (run_id, session_token, user_message)
        yield None

    monkeypatch.setattr(rd, "advisory_run_trace", fake_trace)

    repo = FakeRepository()
    dispatcher = RunDispatcher(
        repository=repo,
        runner=lambda profile_state, latest_user_message, trace_run_id=None,
        correction_note=None, closing_seed=None: {"final_answer": "ok"},
    )
    dispatcher.execute(
        session_token="sess-1", run_id=42, latest_user_message="hi",
        profile_state=ChatProfileState(admission_year=2026),
    )

    assert captured["args"] == (42, "sess-1", "hi")
    assert repo.completed[0] == 42
