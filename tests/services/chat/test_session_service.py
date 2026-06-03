from services.chat.models import ChatMessageRecord
from services.chat.session_service import AnonymousSessionService


class FakeRepository:
    def __init__(self):
        self.session = None
        self.messages = []

    def create_session(self, session_token):
        self.session = {
            "id": 1,
            "session_token": session_token,
            "status": "collecting_profile",
            "profile_state_json": {},
            "latest_run_id": None,
        }
        return self.session

    def append_message(self, session_token, role, content, kind="chat"):
        message = ChatMessageRecord(
            id=len(self.messages) + 1,
            session_token=session_token,
            role=role,
            kind=kind,
            content=content,
        )
        self.messages.append(message)
        return message
    
    def get_session_by_token(self, session_token):
        return self.session

    def list_message(self, session_token):
        return self.messages

def test_start_session_creates_welcome_message():
    service = AnonymousSessionService(repository=FakeRepository())

    snapshot = service.start_session()

    assert snapshot.session["status"] == "collecting_profile"
    assert snapshot.messages[0].role == "assistant"
    assert "cho mình biết điểm" in snapshot.messages[0].content.lower()

def test_get_session_snapshot_returns_existing_messages():
    repository = FakeRepository()
    service = AnonymousSessionService(repository=repository)
    snapshot = service.start_session()

    fetched = service.get_session_snapshot(snapshot.session["session_token"])

    assert fetched.session["session_token"] == snapshot.session["session_token"]
    assert fetched.messages[0].kind == "assistant_welcome"
