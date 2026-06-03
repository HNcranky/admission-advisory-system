from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StudentProfile(BaseModel):
    total_score: Optional[float] = None
    subject_combination: Optional[str] = None
    preferred_majors: List[str] = Field(default_factory=list)
    preferred_schools: List[str] = Field(default_factory=list)
    location_preference: Optional[str] = None
    tuition_budget: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    missing_slots: List[str] = Field(default_factory=list)


class Evidence(BaseModel):
    source_url: str
    school_name: str
    admission_year: int
    field_name: str
    raw_value: Optional[str] = None
    normalized_value: Any = None
    confidence_score: Optional[float] = None
    trust_level: Optional[int] = None


class CandidateProgram(BaseModel):
    candidate_id: str
    school_id: str
    school_name: str
    admission_year: int
    program_id: Optional[str] = None
    program_name: str
    admission_method: Optional[str] = None
    subject_combinations: List[str] = Field(default_factory=list)
    quota: Optional[Dict[str, Any]] = None
    tuition: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[Evidence] = Field(default_factory=list)
    data_uncertain_fields: List[str] = Field(default_factory=list)


class EligibilityCheck(BaseModel):
    candidate_id: str
    eligible: Optional[bool] = None
    reasons: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None


class RankedRecommendation(BaseModel):
    candidate_id: str
    band: str
    score: float
    summary: str
    reasons: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    allow_answer: bool = True
    blocked_claims: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    policy_flags: List[str] = Field(default_factory=list)
    requires_follow_up: bool = False
    allowed_candidate_ids: List[str] = Field(default_factory=list)
