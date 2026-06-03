from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceOption(BaseModel):
    evidence_id: str
    source_url: str
    trust_level: Optional[int] = None
    fetched_at: Optional[datetime] = None
    confidence_score: Optional[float] = None
    value: Any = None


class ConflictRecord(BaseModel):
    conflict_key: str
    field_name: str
    school_id: str
    school_name: str
    admission_year: int
    program_id: Optional[str] = None
    program_name: str
    admission_method: Optional[str] = None
    options: List[EvidenceOption] = Field(default_factory=list)


class ComparisonReport(BaseModel):
    ranked_options: List[EvidenceOption] = Field(default_factory=list)
    is_decisive: bool = False
    decision_axes: List[str] = Field(default_factory=list)


class ResolutionOutcome(BaseModel):
    conflict_key: str
    field_name: str
    school_id: str
    school_name: str
    program_name: str
    status: Literal["resolved", "unresolved"]
    resolved_value: Optional[Any] = None
    chosen_evidence: Optional[EvidenceOption] = None
    rejected_evidence: List[EvidenceOption] = Field(default_factory=list)
    rationale: str
    decision_axes: List[str] = Field(default_factory=list)
    uncertainty_reason: Optional[str] = None
    used_llm_tiebreaker: bool = False
