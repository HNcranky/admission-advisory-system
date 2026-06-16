from services.chat.base_dispatcher import BaseRunDispatcher
from services.chat.hybrid_dispatcher import HybridDispatcher
from services.chat.run_dispatcher import RunDispatcher
from services.chat.models import ChatProfileState


def test_both_dispatchers_share_base_mark_failed():
    assert RunDispatcher._mark_failed is BaseRunDispatcher._mark_failed
    assert HybridDispatcher._mark_failed is BaseRunDispatcher._mark_failed


class FullExecutor:
    """Always returns False (queue full)."""
    def submit(self, fn, *args, **kwargs):
        return False


class RecordingRepo:
    def __init__(self):
        self.messages = []
        self.completed = None

    def complete_run(self, rid, res, ans):
        self.completed = (rid, res)

    def append_message(self, tok, role, content, kind="chat"):
        self.messages.append(kind)

    def update_session_status(self, tok, status):
        pass


def test_submit_rejects_when_queue_full():
    repo = RecordingRepo()
    d = RunDispatcher(
        repository=repo,
        runner=lambda *a, **k: {"final_answer": "x"},
        executor=FullExecutor(),
    )
    accepted = d.submit(
        session_token="t", run_id=5,
        latest_user_message="hi", profile_state=ChatProfileState(admission_year=2026),
    )
    assert accepted is False
    assert "assistant_error" in repo.messages
    assert repo.completed[1] == {"rejected": True}
