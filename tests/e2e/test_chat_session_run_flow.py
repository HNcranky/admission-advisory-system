from fastapi.testclient import TestClient

from services.chat.models import ChatMessageRecord, ChatProfileState, ChatSessionSnapshot, ConversationTurnResult
from web.app import build_app


def test_student_can_complete_follow_up_and_receive_final_result(monkeypatch):
    client = TestClient(build_app())

    session = {
        "id": 1,
        "session_token": "session-123",
        "status": "collecting_profile",
        "profile_state_json": {},
        "latest_run_id": None,
    }
    messages = [
        ChatMessageRecord(
            id=1,
            session_token="session-123",
            role="assistant",
            kind="assistant_welcome",
            content="Chào bạn",
        )
    ]

    class FakeSessionService:
        def start_session(self):
            return ChatSessionSnapshot(session=session, messages=list(messages))

        def get_session_snapshot(self, session_token):
            return ChatSessionSnapshot(session=session, messages=list(messages))

    class FakeRepository:
        def create_run(self, session_token, profile_state):
            session["status"] = "running"
            session["latest_run_id"] = 7
            session["profile_state_json"] = profile_state.model_dump(mode="json")
            return 7

    class FakeConversationService:
        def __init__(self):
            self.repository = FakeRepository()
            self.turn_count = 0

        def handle_user_message(self, session_token, content):
            self.turn_count += 1
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="user",
                    kind="user_message",
                    content=content,
                )
            )
            if self.turn_count == 1:
                session["status"] = "collecting_profile"
                session["profile_state_json"] = {
                    "admission_year": 2026,
                    "preferred_majors": ["computer_science"],
                    "location_preference": "Ha Noi",
                    "missing_slots": ["total_score"],
                }
                messages.append(
                    ChatMessageRecord(
                        id=len(messages) + 1,
                        session_token=session_token,
                        role="assistant",
                        kind="assistant_follow_up",
                        content="Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?",
                    )
                )
                return ConversationTurnResult(
                    session_status="collecting_profile",
                    assistant_message="Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?",
                    should_start_run=False,
                    profile_state=ChatProfileState(
                        admission_year=2026,
                        preferred_majors=["computer_science"],
                        location_preference="Ha Noi",
                        missing_slots=["total_score"],
                    ),
                )

            ready_state = ChatProfileState(
                admission_year=2026,
                total_score=27.0,
                preferred_majors=["computer_science"],
                location_preference="Ha Noi",
                missing_slots=[],
            )
            session["status"] = "ready"
            session["profile_state_json"] = ready_state.model_dump(mode="json")
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="assistant",
                    kind="assistant_ready",
                    content="Cảm ơn bạn. Mình đã có đủ thông tin và sẽ bắt đầu phân tích.",
                )
            )
            return ConversationTurnResult(
                session_status="ready",
                assistant_message="Cảm ơn bạn. Mình đã có đủ thông tin và sẽ bắt đầu phân tích.",
                should_start_run=True,
                profile_state=ready_state,
            )

    class FakeDispatcher:
        def submit(self, session_token, run_id, latest_user_message, profile_state):
            session["status"] = "completed"
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="assistant",
                    kind="assistant_result",
                    content="De xuat: CNTT Bach Khoa Ha Noi la mot lua chon phu hop.",
                )
            )

    fake_session_service = FakeSessionService()
    fake_conversation_service = FakeConversationService()

    monkeypatch.setattr("web.routes.chat_api.get_session_service", lambda: fake_session_service)
    monkeypatch.setattr("web.routes.chat_api.get_conversation_service", lambda: fake_conversation_service)
    monkeypatch.setattr("web.routes.chat_api.get_run_dispatcher", lambda: FakeDispatcher())

    created = client.post("/api/sessions")
    assert created.status_code == 201

    first = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em muon hoc CNTT o Ha Noi nam 2026"},
    )
    assert first.json()["should_start_run"] is False

    second = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em du kien duoc 27 diem"},
    )
    assert second.json()["should_start_run"] is True

    snapshot = client.get("/api/sessions/session-123")
    body = snapshot.json()
    assert body["session"]["status"] == "completed"
    assert body["messages"][-1]["kind"] == "assistant_result"
    assert "Bach Khoa Ha Noi" in body["messages"][-1]["content"]
