import secrets

from services.chat.models import ChatSessionSnapshot
from services.chat.repository import ChatSessionRepository

WELCOME_MESSAGE = (
    "Chào bạn, mình có thể tư vấn tuyển sinh. "
    "Hãy cho mình biết điểm, ngành bạn quan tâm, và khu vực bạn muốn học."
)

class AnonymousSessionService:
    def __init__(self, repository = None):
        self.repository = repository or ChatSessionRepository()
    
    def start_session(self) -> ChatSessionSnapshot:
        session_token = secrets.token_urlsafe(18)
        session = self.repository.create_session(session_token)
        welcome = self.repository.append_message(
            session_token,
            role="assistant",
            content = WELCOME_MESSAGE,
            kind = "assistant_welcome",
        )
        return ChatSessionSnapshot(session=session, messages=[welcome])
    
    def get_session_snapshot(self, session_token: str) -> ChatSessionSnapshot:
        session = self.repository.get_session_by_token(session_token)
        messages = self.repository.list_message(session_token) if session else []
        return ChatSessionSnapshot(session=session, messages=messages)
