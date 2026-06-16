from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, ConversationTurnResult


class FakeRepository:
    def __init__(self, run_id=7, runs=1):
        self._run_id = run_id
        self._runs = runs
        self.created = []

    def create_run(self, session_token, profile_state):
        self.created.append((session_token, profile_state))
        return self._run_id

    def count_runs(self, session_token):
        return self._runs


class FakeRunDispatcher:
    def __init__(self):
        self.calls = []

    def submit(self, **kwargs):
        self.calls.append(kwargs)


class FakeHybridDispatcher:
    def __init__(self):
        self.calls = []

    def submit(self, **kwargs):
        self.calls.append(kwargs)


def _service(repo, run_dispatcher=None, hybrid_dispatcher=None):
    return ConversationService(
        repository=repo,
        run_dispatcher=run_dispatcher or FakeRunDispatcher(),
        hybrid_dispatcher=hybrid_dispatcher or FakeHybridDispatcher(),
    )


def test_start_run_dispatches_advisory_with_closing_seed():
    repo = FakeRepository(run_id=42, runs=3)
    run_dispatcher = FakeRunDispatcher()
    service = _service(repo, run_dispatcher=run_dispatcher)

    result = ConversationTurnResult(
        session_status="ready",
        assistant_message="ok",
        should_start_run=True,
        profile_state=ChatProfileState(admission_year=2026, total_score=27.0),
        correction_note={"slot": "total_score"},
    )
    service.start_run("sess", "Em duoc 27 diem", result)

    assert repo.created == [("sess", result.profile_state)]
    assert len(run_dispatcher.calls) == 1
    call = run_dispatcher.calls[0]
    assert call["run_id"] == 42
    assert call["latest_user_message"] == "Em duoc 27 diem"
    assert call["closing_seed"] == 2  # count_runs - 1
    assert call["correction_note"] == {"slot": "total_score"}


def test_start_run_dispatches_hybrid_with_validated_intent():
    repo = FakeRepository(run_id=55, runs=1)
    hybrid_dispatcher = FakeHybridDispatcher()
    run_dispatcher = FakeRunDispatcher()
    service = _service(repo, run_dispatcher=run_dispatcher, hybrid_dispatcher=hybrid_dispatcher)

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

    assert run_dispatcher.calls == []  # advisory dispatcher untouched
    assert len(hybrid_dispatcher.calls) == 1
    call = hybrid_dispatcher.calls[0]
    assert call["run_id"] == 55
    assert call["content"] == "so sanh UET va HUST"
    assert call["intent"].schools == ["VNU-UET", "HUST"]


def test_start_run_noop_when_should_start_run_false():
    repo = FakeRepository()
    run_dispatcher = FakeRunDispatcher()
    service = _service(repo, run_dispatcher=run_dispatcher)

    result = ConversationTurnResult(
        session_status="collecting_profile",
        assistant_message="cau hoi tiep theo",
        should_start_run=False,
        profile_state=ChatProfileState(),
    )
    service.start_run("sess", "Em muon hoc CNTT", result)

    assert repo.created == []
    assert run_dispatcher.calls == []
