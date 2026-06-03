from services.chat.models import ChatProfileState
from services.profile.extractor import apply_profile_delta


def test_delta_overrides_existing_value_correction():
    current = ChatProfileState(preferred_schools=["hust"])
    merged = apply_profile_delta(current, {"preferred_schools": ["neu"]})
    assert merged.preferred_schools == ["neu"]  # đính chính được


def test_unmentioned_slots_preserved():
    current = ChatProfileState(total_score=25.0, subject_combination="A00")
    merged = apply_profile_delta(current, {"location_preference": "Ha Noi"})
    assert merged.total_score == 25.0
    assert merged.subject_combination == "A00"
    assert merged.location_preference == "Ha Noi"


def test_missing_slots_recomputed_after_apply():
    current = ChatProfileState(admission_year=2026)
    merged = apply_profile_delta(current, {"total_score": 27.0})
    assert "total_score" not in merged.missing_slots
    assert "preferred_majors" in merged.missing_slots
