from services.chat.run_queue_worker import RunQueueWorker


class OneShotRepo:
    def __init__(self):
        self._claim = {
            "run_id": 1,
            "session_token": "t",
            "dispatch_args": {
                "run_kind": "advisory",
                "latest_user_message": "hi",
                "profile_state": None,
            },
        }

    def claim_next_queued_run(self, worker_id):
        c, self._claim = self._claim, None
        return c


class SpyDispatcher:
    def __init__(self):
        self.calls = []

    def execute(self, *args):
        self.calls.append(args)


def test_poll_once_executes_claimed_advisory_run():
    repo = OneShotRepo()
    run = SpyDispatcher()
    w = RunQueueWorker("w1", repository=repo, run=run, hybrid=SpyDispatcher())
    assert w.poll_once() is True
    assert run.calls and run.calls[0][0] == "t" and run.calls[0][1] == 1
    assert w.poll_once() is False  # queue empty


def test_poll_once_rehydrates_profile_state_dict_to_model():
    """dispatch_args round-trips through JSONB; the dict must become a
    ChatProfileState before reaching the dispatcher (regression: AttributeError
    'dict' object has no attribute 'total_score')."""
    from services.chat.models import ChatProfileState

    class DictProfileRepo:
        def __init__(self):
            self._claim = {
                "run_id": 7, "session_token": "t",
                "dispatch_args": {
                    "run_kind": "advisory", "latest_user_message": "hi",
                    "profile_state": {"total_score": 27.5, "admission_year": 2026},
                },
            }

        def claim_next_queued_run(self, worker_id):
            c, self._claim = self._claim, None
            return c

    run = SpyDispatcher()
    w = RunQueueWorker("w3", repository=DictProfileRepo(), run=run, hybrid=SpyDispatcher())
    assert w.poll_once() is True
    passed = run.calls[0][3]
    assert isinstance(passed, ChatProfileState)
    assert passed.total_score == 27.5


def test_poll_once_returns_false_when_queue_empty():
    class EmptyRepo:
        def claim_next_queued_run(self, worker_id):
            return None

    w = RunQueueWorker("w2", repository=EmptyRepo())
    assert w.poll_once() is False
