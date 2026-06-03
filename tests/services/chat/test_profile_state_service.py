from agents.models import StudentProfile
from services.chat.models import ChatProfileState
from services.chat.profile_state_service import (
    merge_profile_state,
    missing_critical_slots,
    next_follow_up_question,
)


def test_merge_profile_state_keeps_previous_values_and_orders_missing_slots():
    current = ChatProfileState(
        admission_year=2026,
        preferred_majors=["computer_science"],
    )
    extracted = StudentProfile(
        total_score=27.0,
        subject_combination="A00",
        location_preference="Ha Noi",
    )

    merged = merge_profile_state(
        current,
        extracted,
        "Em duoc khoang 27 diem A00 muon hoc tai Ha Noi",
    )

    assert merged.admission_year == 2026
    assert merged.total_score == 27.0
    assert merged.subject_combination == "A00"
    assert merged.preferred_majors == ["computer_science"]
    assert merged.location_preference == "Ha Noi"
    assert merged.missing_slots == []
    assert next_follow_up_question(merged) is None


def test_merge_profile_state_returns_first_missing_slot_prompt():
    merged = merge_profile_state(
        ChatProfileState(),
        StudentProfile(preferred_majors=["kinh_te"]),
        "Em muon hoc khoi kinh te",
    )

    assert merged.missing_slots == [
        "admission_year",
        "total_score",
        "subject_combination",
    ]
    assert next_follow_up_question(merged) == "Bạn đang xét tuyển cho năm nào?"


def test_missing_critical_slots_empty_profile_returns_all():
    missing = missing_critical_slots(ChatProfileState())
    assert "admission_year" in missing
    assert "total_score" in missing
    assert "preferred_majors" in missing
    # location_preference giờ là optional (spec mục 8) → không nằm trong critical.
    assert "location_preference" not in missing


def test_missing_critical_slots_complete_profile_returns_empty():
    profile = ChatProfileState(
        admission_year=2026,
        total_score=25.0,
        preferred_majors=["computer_science"],
        subject_combination="A00",
        location_preference="Ha Noi",
    )
    assert missing_critical_slots(profile) == []


def test_missing_critical_slots_ignores_stale_missing_slots_field():
    # missing_slots says empty, but the fields are actually empty → recompute wins.
    profile = ChatProfileState(missing_slots=[])
    assert "total_score" in missing_critical_slots(profile)
