from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.chat.conversation_service import ConversationService
from services.chat.session_service import AnonymousSessionService
from services.tracing.trace_service import TraceService

router = APIRouter(prefix="/api/sessions", tags=["chat"])

class ChatMessageCreate(BaseModel):
    content: str = Field(max_length=4000)

def get_session_service():
    return AnonymousSessionService()

def get_conversation_service():
    return ConversationService()

def get_trace_service():
    return TraceService()

@router.post("", status_code=status.HTTP_201_CREATED)
def create_session():
    return get_session_service().start_session()

@router.get("/{session_token}")
def get_session(session_token: str):
    snapshot = get_session_service().get_session_snapshot(session_token)
    if not snapshot.session:
        raise HTTPException(status_code=404, detail="Session not found")
    return snapshot

@router.post("/{session_token}/messages")
def post_message(session_token: str, payload: ChatMessageCreate):
    service = get_conversation_service()
    result = service.handle_user_message(session_token, payload.content)
    service.start_run(session_token, payload.content, result)
    return result.model_dump()

@router.get("/{session_token}/trace")
def get_trace(session_token: str):
    payload = get_trace_service().get_trace(session_token)
    if payload is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return payload