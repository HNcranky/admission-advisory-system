from services.chat.startup import reap_orphaned_runs


class FakeRepo:
    def __init__(self):
        self.stale = [(1, "tok-a"), (2, "tok-b")]
        self.messages = []
        self.statuses = []

    def reap_stale_runs(self):
        out, self.stale = self.stale, []
        return out

    def append_message(self, tok, role, content, kind="chat"):
        self.messages.append((tok, kind, content))

    def update_session_status(self, tok, status):
        self.statuses.append((tok, status))


def test_reap_finalizes_each_orphan():
    repo = FakeRepo()
    n = reap_orphaned_runs(repository=repo)
    assert n == 2
    assert ("tok-a", "failed") in repo.statuses
    assert ("tok-b", "failed") in repo.statuses
    assert all(m[1] == "assistant_error" for m in repo.messages)


def test_reap_idempotent_second_call_noop():
    repo = FakeRepo()
    reap_orphaned_runs(repository=repo)
    assert reap_orphaned_runs(repository=repo) == 0
