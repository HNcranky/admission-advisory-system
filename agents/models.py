"""Re-export shim. Domain models moved to domain.models (audit §4.1).

Kept so existing `from agents.models import X` keeps working.
New code should import from domain.models.
"""
from domain.models import (
    CandidateProgram,
    CutoffAssessment,
    CutoffEntry,
    EligibilityCheck,
    Evidence,
    PolicyDecision,
    RankedRecommendation,
    StudentProfile,
)

__all__ = [
    "CandidateProgram",
    "CutoffAssessment",
    "CutoffEntry",
    "EligibilityCheck",
    "Evidence",
    "PolicyDecision",
    "RankedRecommendation",
    "StudentProfile",
]
