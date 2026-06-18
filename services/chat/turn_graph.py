from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState, ConversationTurnResult, FlowState


class TurnState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_token: str
    content: str
    history_ctx: str = ""
    prev_user: str = ""
    profile_state: ChatProfileState
    flow_state: FlowState
    delta: dict = Field(default_factory=dict)
    session_status: str = "collecting_profile"

    intent: Optional[IntentResult] = None
    route: Optional[str] = None
    result: Optional[ConversationTurnResult] = None
