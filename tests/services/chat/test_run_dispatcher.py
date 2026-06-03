from services.chat.models import ChatProfileState
from services.chat.run_dispatcher import RunDispatcher


class FakeRepository:
    def __init__(self):
        self.completed = None
        self.messages = []
        self.status = None

    def mark_run_running(self, run_id):
        self.status = ("running", run_id)

    def complete_run(self, run_id, result_json, final_answer):
        self.completed = (run_id, result_json, final_answer)

    def append_message(self, session_token, role, content, kind="chat"):
        self.messages.append((session_token, role, kind, content))

    def update_session_status(self, session_token, status):
        self.status = (status, session_token)


class InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def test_dispatcher_completes_run_and_posts_result_message():
    repo = FakeRepository()
    dispatcher = RunDispatcher(
        repository=repo,
        runner=lambda profile_state, latest_user_message, trace_run_id=None: {"final_answer": "De xuat phu hop"},
        executor=InlineExecutor(),
    )

    dispatcher.submit(
        session_token="session-123",
        run_id=7,
        latest_user_message="Em duoc 27 diem",
        profile_state=ChatProfileState(
            admission_year=2026,
            total_score=27.0,
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
    )

    assert repo.completed[0] == 7
    assert repo.completed[2] == "De xuat phu hop"
    assert repo.messages[-1][2] == "assistant_result"


def test_dispatcher_posts_mock_conflict_verification_result_message(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")
    repo = FakeRepository()
    dispatcher = RunDispatcher(
        repository=repo,
        runner=lambda profile_state, latest_user_message, trace_run_id=None: {
            "final_answer": "Gợi ý CNTT\n\nXác minh dữ liệu\n- Hạn ngạch có mâu thuẫn."
        },
        executor=InlineExecutor(),
    )

    dispatcher.submit(
        session_token="session-456",
        run_id=8,
        latest_user_message="Tu van nganh Cong nghe thong tin UET nam 2026",
        profile_state=ChatProfileState(
            admission_year=2026,
            total_score=27.0,
            preferred_majors=["cntt"],
            preferred_schools=["vnu_uet"],
        ),
    )

    assert repo.completed[2].count("Xác minh dữ liệu") == 1
    assert repo.messages[-1] == (
        "session-456",
        "assistant",
        "assistant_result",
        repo.completed[2],
    )


def test_dispatcher_passes_run_id_as_trace_run_id_to_runner():
    repo = FakeRepository()
    captured = {}

    def runner(profile_state, latest_user_message, trace_run_id=None):
        captured["trace_run_id"] = trace_run_id
        return {"final_answer": "ok"}

    dispatcher = RunDispatcher(
        repository=repo,
        runner=runner,
        executor=InlineExecutor(),
    )

    dispatcher.submit(
        session_token="session-xyz",
        run_id=99,
        latest_user_message="hello",
        profile_state=ChatProfileState(admission_year=2026),
    )

    assert captured["trace_run_id"] == 99
