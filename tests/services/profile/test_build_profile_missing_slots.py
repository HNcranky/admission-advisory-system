from services.profile_service import build_profile


def test_build_profile_missing_slots_uses_registry_critical_set():
    # Không nhắc gì → các slot critical (registry) phải nằm trong missing_slots.
    profile = build_profile("xin chào")
    assert "total_score" in profile.missing_slots
    assert "preferred_majors" in profile.missing_slots
    assert "subject_combination" in profile.missing_slots  # nay critical
    assert "admission_method" in profile.missing_slots
