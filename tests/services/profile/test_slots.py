from services.profile.slots import parse_score, parse_admission_year, parse_subject_combination


def test_parse_score_bare_number_in_range():
    assert parse_score("29") == 29.0
    assert parse_score("27,5") == 27.5


def test_parse_score_out_of_range_returns_none():
    assert parse_score("99") is None
    assert parse_score("không có") is None


def test_parse_admission_year_extracts_four_digit_year():
    assert parse_admission_year("mình xét tuyển năm 2026") == 2026
    assert parse_admission_year("không nhắc năm") is None


def test_parse_subject_combination_valid_code():
    assert parse_subject_combination("em thi khối A00") == "A00"


def test_parse_subject_combination_unknown_returns_none():
    assert parse_subject_combination("em thi khối Z99") is None


from types import SimpleNamespace

from services.profile.slots import (
    SLOTS, missing_critical_slots, next_follow_up_question, parse_slot,
)


def _state(**kwargs):
    base = dict(
        admission_year=None, total_score=None, subject_combination=None,
        preferred_majors=[], inferred_interest_tags=[], explicit_preferred_majors=[],
        preferred_schools=[], location_preference=None,
        tuition_budget=None, constraints=[],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_missing_critical_slots_empty_state_returns_current_critical_set():
    # location_preference KHÔNG còn critical (spec mục 8).
    missing = missing_critical_slots(_state())
    assert missing == [
        "admission_year", "total_score", "preferred_majors", "subject_combination",
    ]


def test_missing_critical_slots_complete_returns_empty():
    state = _state(
        admission_year=2026, total_score=25.0,
        preferred_majors=["computer_science"], subject_combination="A00",
    )
    assert missing_critical_slots(state) == []


def test_major_slot_satisfied_by_inferred_tags_only():
    state = _state(
        admission_year=2026, total_score=25.0,
        inferred_interest_tags=["data_science"], subject_combination="A00",
    )
    assert "preferred_majors" not in missing_critical_slots(state)
    assert missing_critical_slots(state) == []


def test_major_slot_satisfied_by_explicit_majors_only():
    state = _state(
        admission_year=2026, total_score=25.0,
        explicit_preferred_majors=["computer_science"], subject_combination="A00",
    )
    assert "preferred_majors" not in missing_critical_slots(state)


def test_location_preference_is_not_critical():
    state = _state(
        admission_year=2026, total_score=25.0,
        explicit_preferred_majors=["computer_science"], subject_combination="A00",
    )
    # location chưa điền nhưng vẫn đủ điều kiện retrieval.
    assert "location_preference" not in missing_critical_slots(state)


def test_next_follow_up_question_returns_first_missing_prompt():
    assert next_follow_up_question(_state()) == "Bạn đang xét tuyển cho năm nào?"
    assert next_follow_up_question(_state(
        admission_year=2026, total_score=25.0,
        preferred_majors=["x"], subject_combination="A00", location_preference="Ha Noi",
    )) is None


def test_parse_slot_dispatches_to_named_parser():
    assert parse_slot("total_score", "29") == 29.0
    assert parse_slot("admission_year", "năm 2026") == 2026
    assert parse_slot("preferred_majors", "bất kỳ") is None  # không có parser
