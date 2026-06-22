from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class StudentProfile(BaseModel):
    total_score: Optional[float] = None
    admission_method: Optional[str] = None
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


class CutoffEntry(BaseModel):
    """Một dòng điểm chuẩn lịch sử của (trường, chương trình) từ một nguồn."""
    cutoff_year: int
    admission_method: str          # mã canonical: 'thpt_score'...
    cutoff_score: float
    score_scale: Optional[float] = None
    source_url: str
    trust_level: Optional[int] = None
    note: Optional[str] = None


class CutoffAssessment(BaseModel):
    """Kết quả đối chiếu điểm hồ sơ với điểm chuẩn lịch sử (EC-14/15/16/18).

    Đặt ở domain.models (không phải services/cutoff) để tránh vòng import:
    services/cutoff/assessment.py import CutoffEntry từ đây."""
    score_fit: Literal["above", "borderline", "below", "uncertain"]
    reference_year: int
    margin: float
    latest_values: List[Dict[str, Any]] = Field(default_factory=list)  # [{value, source_url, trust_level}]
    conflicted: bool = False
    decision_changing: bool = False
    volatile: bool = False
    volatility_min: Optional[float] = None
    volatility_max: Optional[float] = None
    years_used: List[int] = Field(default_factory=list)


class CandidateProgram(BaseModel):
    candidate_id: str
    school_id: str
    school_name: str
    admission_year: int
    program_id: Optional[str] = None
    program_name: str
    program_name_raw: Optional[str] = None
    admission_method: Optional[str] = None
    subject_combinations: List[str] = Field(default_factory=list)
    quota: Optional[Dict[str, Any]] = None
    tuition: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[Evidence] = Field(default_factory=list)
    data_uncertain_fields: List[str] = Field(default_factory=list)
    cutoff_history: List[CutoffEntry] = Field(default_factory=list)


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
    cutoff_assessment: Optional[CutoffAssessment] = None


class PolicyDecision(BaseModel):
    allow_answer: bool = True
    blocked_claims: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    policy_flags: List[str] = Field(default_factory=list)
    requires_follow_up: bool = False
    allowed_candidate_ids: List[str] = Field(default_factory=list)
