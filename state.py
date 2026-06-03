from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agents.models import (
    CandidateProgram,
    EligibilityCheck,
    Evidence,
    PolicyDecision,
    RankedRecommendation,
    StudentProfile,
)
from services.conflict.models import ConflictRecord, ResolutionOutcome

try:
    from ingestion.config.settings import ADMISSION_YEAR
except Exception:
    ADMISSION_YEAR = 2026


class AgentState(BaseModel):
    user_query: str
    chat_history: List[str] = Field(default_factory=list)
    intent: Optional[str] = None
    admission_year: int = ADMISSION_YEAR
    profile_seeded: bool = False

    student_profile: StudentProfile = Field(default_factory=StudentProfile)
    retrieval_filters: Dict[str, Any] = Field(default_factory=dict)
    retrieved_programs: List[CandidateProgram] = Field(default_factory=list)
    retrieval_missing_data: List[str] = Field(default_factory=list)

    conflicts: List[str] = Field(default_factory=list)
    conflict_records: List[ConflictRecord] = Field(default_factory=list)
    resolution_outcomes: List[ResolutionOutcome] = Field(default_factory=list)
    eligibility_checks: List[EligibilityCheck] = Field(default_factory=list)
    ranked_recommendations: List[RankedRecommendation] = Field(default_factory=list)

    policy_decision: Optional[PolicyDecision] = None
    citations: List[Evidence] = Field(default_factory=list)

    advisory: Optional[str] = None
    final_answer: Optional[str] = None
    trace_run_id: Optional[int] = None

    inference_warnings: List[str] = Field(default_factory=list)
    uncertainty_reasons: List[str] = Field(default_factory=list)


                                                 
ProgramInfo = CandidateProgram
