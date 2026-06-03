from functools import lru_cache

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from services.chat.conversation_service import ConversationService
from services.chat.hybrid_dispatcher import HybridDispatcher
from services.chat.intent_router import IntentResult
from services.chat.run_dispatcher import RunDispatcher
from services.chat.session_service import AnonymousSessionService
from services.tracing.trace_service import TraceService

router = APIRouter(prefix="/api/sessions", tags=["chat"])

class ChatMessageCreate(BaseModel):
    content: str
    
def get_session_service():
    return AnonymousSessionService()
    
def get_conversation_service():
    return ConversationService()

# Singletons: each holds a ThreadPoolExecutor. Building a new one per request
# leaked worker threads on every message that started a run.
@lru_cache(maxsize=1)
def get_run_dispatcher():
    return RunDispatcher()

@lru_cache(maxsize=1)
def get_hybrid_dispatcher():
    return HybridDispatcher()

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
    if result.should_start_run:
        repo = service.repository
        run_id = repo.create_run(session_token, result.profile_state)
        if result.run_kind == "hybrid":
            intent = IntentResult.model_validate(result.hybrid_intent or {"route": "HYBRID"})
            get_hybrid_dispatcher().submit(
                session_token=session_token,
                run_id=run_id,
                content=payload.content,
                profile_state=result.profile_state,
                intent=intent,
            )
        else:
            get_run_dispatcher().submit(
                session_token=session_token,
                run_id=run_id,
                latest_user_message=payload.content,
                profile_state=result.profile_state,
            )
    return result.model_dump()

@router.get("/{session_token}/trace")
def get_trace(session_token: str):
    payload = get_trace_service().get_trace(session_token)
    if payload is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return payload