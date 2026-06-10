from services.profile.slots import parse_score, parse_admission_year, parse_subject_combination


def test_parse_score_bare_number_in_range():
    assert parse_score("29") == 29.0
    assert parse_score("27,5") == 27.5


def test_parse_score_out_of_range_returns_none():
    assert parse_score("999") is None       # > 150 sanity cap
    assert parse_score("không có") is None


def test_parse_score_accepts_three_digit_competency_scores():
    assert parse_score("105") == 105.0      # điểm ĐGNL/ĐGTD
    assert parse_score("128,5") == 128.5


def test_parse_score_ignores_four_digit_year_tokens():
    # Bug cũ: "2026" bị regex \d{1,2} cắt thành 20.0 → điểm rác lọt vào profile.
    assert parse_score("2026") is None
    assert parse_score("năm 2026") is None
    assert parse_score("2026 em được 26.5") == 26.5


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
        admission_method=None,
        preferred_majors=[], inferred_interest_tags=[], explicit_preferred_majors=[],
        preferred_schools=[], location_preference=None,
        tuition_budget=None, constraints=[],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_missing_critical_slots_empty_state_returns_current_critical_set():
    missing = missing_critical_slots(_state())
    assert missing == [
        "admission_year", "total_score", "admission_method",
        "preferred_majors", "subject_combination",
    ]


def test_missing_critical_slots_complete_returns_empty():
    state = _state(
        admission_year=2026, total_score=25.0, admission_method="thpt_score",
        preferred_majors=["computer_science"], subject_combination="A00",
    )
    assert missing_critical_slots(state) == []


def test_major_slot_satisfied_by_inferred_tags_only():
    state = _state(
        admission_year=2026, total_score=25.0, admission_method="thpt_score",
        inferred_interest_tags=["data_science"], subject_combination="A00",
    )
    assert "preferred_majors" not in missing_critical_slots(state)
    assert missing_critical_slots(state) == []


def test_major_slot_satisfied_by_explicit_majors_only():
    state = _state(
        admission_year=2026, total_score=25.0, admission_method="thpt_score",
        explicit_preferred_majors=["computer_science"], subject_combination="A00",
    )
    assert "preferred_majors" not in missing_critical_slots(state)


def test_location_preference_is_not_critical():
    state = _state(
        admission_year=2026, total_score=25.0, admission_method="thpt_score",
        explicit_preferred_majors=["computer_science"], subject_combination="A00",
    )
    # location chưa điền nhưng vẫn đủ điều kiện retrieval.
    assert "location_preference" not in missing_critical_slots(state)


def test_next_follow_up_question_returns_first_missing_prompt():
    assert next_follow_up_question(_state()) == "Bạn đang xét tuyển cho năm nào?"
    assert next_follow_up_question(_state(
        admission_year=2026, total_score=25.0, admission_method="thpt_score",
        preferred_majors=["x"], subject_combination="A00", location_preference="Ha Noi",
    )) is None


def test_parse_slot_dispatches_to_named_parser():
    assert parse_slot("total_score", "29") == 29.0
    assert parse_slot("admission_year", "năm 2026") == 2026
    assert parse_slot("preferred_majors", "bất kỳ") is None  # không có parser


def test_admission_method_slot_asked_right_after_score():
    state = _state(admission_year=2026, total_score=27.0)
    assert missing_critical_slots(state)[0] == "admission_method"
    assert "phương thức" in next_follow_up_question(state)


def test_parse_slot_dispatches_admission_method():
    assert parse_slot("admission_method", "em xét học bạ") == "school_record"


from services.chat.models import ChatProfileState
from services.profile.slots import build_slot_acknowledgement


def test_ack_echoes_single_captured_value_when_under_two_filled():
    state = ChatProfileState(total_score=26.0)
    ack = build_slot_acknowledgement({"total_score": 26.0}, state)
    assert ack == "Mình ghi nhận mức điểm 26."


def test_ack_recaps_filled_and_missing_when_two_or_more_filled():
    state = ChatProfileState(admission_year=2026, total_score=26.0, admission_method="thpt_score")
    ack = build_slot_acknowledgement({"admission_method": "thpt_score"}, state)
    assert ack.startswith("Mình đã nắm:")
    assert "năm xét tuyển 2026" in ack
    assert "mức điểm 26" in ack
    assert "phương thức xét tuyển điểm thi tốt nghiệp THPT" in ack
    assert "Còn thiếu:" in ack
    assert "tổ hợp xét tuyển" in ack
    assert "ngành quan tâm" in ack


def test_ack_returns_none_when_nothing_captured():
    state = ChatProfileState(total_score=26.0)
    assert build_slot_acknowledgement({}, state) is None
    assert build_slot_acknowledgement({"preferred_schools": ["hust"]}, state) is None


def test_ack_dedupes_major_variants_to_one_label():
    state = ChatProfileState(preferred_majors=["computer_science"])
    ack = build_slot_acknowledgement(
        {"explicit_preferred_majors": ["computer_science"], "preferred_majors": ["computer_science"]},
        state,
    )
    assert ack == "Mình ghi nhận ngành quan tâm computer_science."
