import re

from agents.models import StudentProfile
from services.chat.models import ChatProfileState
from services.profile.slots import (  # noqa: F401  (re-export cho callers/test cũ)
    missing_critical_slots,
    next_follow_up_question,
    parse_slot,
)


def _extract_admission_year(raw_message: str):
    match = re.search(r"\b20\d{2}\b", raw_message)
    return int(match.group(0)) if match else None


def parse_pending_slot_answer(pending_slot: str, raw_message: str):
    """Backward-compat shim → registry parser. Trả giá trị parse được hoặc None."""
    return parse_slot(pending_slot, raw_message)


def merge_profile_state(current: ChatProfileState, extracted: StudentProfile, raw_message: str) -> ChatProfileState:
    """DEPRECATED khỏi conversation flow (slice 3 dùng apply_profile_delta).
    Giữ lại cho test unit hiện có và tham chiếu ngoài."""
    merged = ChatProfileState(
        admission_year=_extract_admission_year(raw_message) or current.admission_year,
        total_score=extracted.total_score or current.total_score,
        subject_combination=extracted.subject_combination or current.subject_combination,
        preferred_majors=extracted.preferred_majors or current.preferred_majors,
        preferred_schools=extracted.preferred_schools or current.preferred_schools,
        location_preference=extracted.location_preference or current.location_preference,
        tuition_budget=extracted.tuition_budget or current.tuition_budget,
        constraints=extracted.constraints or current.constraints,
    )
    merged.missing_slots = missing_critical_slots(merged)
    return merged
