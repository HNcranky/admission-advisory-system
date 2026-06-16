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

    def _execute(self, *args):
        self.calls.append(args)


def test_poll_once_executes_claimed_advisory_run():
    repo = OneShotRepo()
    run = SpyDispatcher()
    w = RunQueueWorker("w1", repository=repo, run=run, hybrid=SpyDispatcher())
    assert w.poll_once() is True
    assert run.calls and run.calls[0][0] == "t" and run.calls[0][1] == 1
    assert w.poll_once() is False  # queue empty


def test_poll_once_returns_false_when_queue_empty():
    class EmptyRepo:
        def claim_next_queued_run(self, worker_id):
            return None

    w = RunQueueWorker("w2", repository=EmptyRepo())
    assert w.poll_once() is False
