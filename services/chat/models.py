from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field

from services.knowledge.models import Citation


class ChatSessionRecord(BaseModel):
    id: int
    session_token: str
    status: str = "collecting_profile"
    profile_state_json: Dict[str, Any] = Field(default_factory=dict)
    latest_run_id: Optional[int] = None
    
class ChatMessageRecord(BaseModel):
    id: int
    session_token: str
    role: str
    kind: str = "chat"
    content: str
    
class ChatSessionSnapshot(BaseModel):
    session: Any
    messages: List[ChatMessageRecord] = Field(default_factory=list)
    
def union_majors(explicit: List[str], inferred: List[str]) -> List[str]:
    """View dẫn xuất preferred_majors = explicit ∪ inferred (explicit trước, dedupe)."""
    return list(dict.fromkeys([*(explicit or []), *(inferred or [])]))


class ChatProfileState(BaseModel):
    admission_year: Optional[int] = None
    total_score: Optional[float] = None
    subject_combination: Optional[str] = None
    # inferred_interest_tags: sở thích suy luận ("thích lập trình/AI") — tích luỹ, bền.
    # explicit_preferred_majors: ngành user chốt rõ ("ưu tiên KHMT"). Tách theo AC4.
    inferred_interest_tags: List[str] = Field(default_factory=list)
    explicit_preferred_majors: List[str] = Field(default_factory=list)
    # preferred_majors: view dẫn xuất = explicit ∪ inferred (giữ cho retrieval/reasoning).
    preferred_majors: List[str] = Field(default_factory=list)
    preferred_schools: List[str] = Field(default_factory=list)
    location_preference: Optional[str] = None
    tuition_budget: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    missing_slots: List[str] = Field(default_factory=list)
    
class FlowState(BaseModel):
    active_flow: Optional[str] = None       # "ADVISORY_FLOW" khi đang trong luồng tư vấn
    pending_question: Optional[str] = None  # follow-up question cuối cùng đã hỏi user

class ConversationTurnResult(BaseModel):
    session_status: str
    assistant_message: str
    should_start_run: bool = False
    profile_state: ChatProfileState
    citations: List[Citation] = Field(default_factory=list)
    run_kind: str = "advisory"                      # "advisory" | "hybrid"
    hybrid_intent: Optional[Dict[str, Any]] = None  # serialized IntentResult, replayed by HybridDispatcher
    correction_note: Optional[Dict[str, Any]] = None  # {slot, previous_value, new_value} khi re-rank (AC7)

class AdvisoryRunRecord(BaseModel):
    id: int
    session_token: str
    status: str
    result_json: Optional[Dict[str, Any]] = None
    final_answer: Optional[str] = None

    
