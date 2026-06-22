from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, ConversationTurnResult


class FakeRepository:
    def __init__(self, runs=1):
        self._runs = runs
        self.enqueued = []

    def enqueue_run(self, session_token, profile_state, dispatch_args):
        self.enqueued.append((session_token, profile_state, dispatch_args))
        return len(self.enqueued)

    def count_runs(self, session_token):
        return self._runs


def _service(repo):
    return ConversationService(repository=repo)


def test_start_run_enqueues_advisory_with_closing_seed():
    repo = FakeRepository(runs=3)
    service = _service(repo)

    result = ConversationTurnResult(
        session_status="ready",
        assistant_message="ok",
        should_start_run=True,
        profile_state=ChatProfileState(admission_year=2026, total_score=27.0),
        correction_note={"slot": "total_score"},
    )
    service.start_run("sess", "Em duoc 27 diem", result)

    assert len(repo.enqueued) == 1
    tok, profile, args = repo.enqueued[0]
    assert tok == "sess"
    assert args["run_kind"] == "advisory"
    assert args["latest_user_message"] == "Em duoc 27 diem"
    assert args["closing_seed"] == 2  # count_runs - 1
    assert args["correction_note"] == {"slot": "total_score"}


def test_start_run_enqueues_hybrid_with_intent():
    repo = FakeRepository(runs=1)
    service = _service(repo)

    result = ConversationTurnResult(
        session_status="running",
        assistant_message="dang tong hop",
        should_start_run=True,
        run_kind="hybrid",
        hybrid_intent={"route": "HYBRID", "schools": ["VNU-UET", "HUST"],
                       "topics": ["tuition"], "needs_advisory": True},
        profile_state=ChatProfileState(admission_year=2026, total_score=27.0),
    )
    service.start_run("sess", "so sanh UET va HUST", result)

    assert len(repo.enqueued) == 1
    tok, profile, args = repo.enqueued[0]
    assert args["run_kind"] == "hybrid"
    assert args["content"] == "so sanh UET va HUST"
    assert args["intent"]["route"] == "HYBRID"


def test_start_run_noop_when_should_start_run_false():
    repo = FakeRepository()
    service = _service(repo)

    result = ConversationTurnResult(
        session_status="collecting_profile",
        assistant_message="cau hoi tiep theo",
        should_start_run=False,
        profile_state=ChatProfileState(),
    )
    service.start_run("sess", "Em muon hoc CNTT", result)

    assert repo.enqueued == []
