from services.chat.models import ChatProfileState
from services.profile.validation import validate_profile_delta


def test_r1_score_over_scale_rejected_other_fields_kept():
    # EC-04: method đã biết (thang 30), delta điểm 35 → loại điểm, giữ field khác.
    current = ChatProfileState(admission_method="thpt_score")
    delta = {"total_score": 35.0, "location_preference": "Ha Noi"}

    clean, rejections = validate_profile_delta(delta, current)

    assert "total_score" not in clean
    assert clean["location_preference"] == "Ha Noi"
    assert len(rejections) == 1
    assert rejections[0]["slot"] == "total_score"
    assert "35" in rejections[0]["message"]
    assert "thang 30" in rejections[0]["message"]
    assert "phương thức" in rejections[0]["message"]


def test_r1_uses_method_from_same_delta():
    # Method đến cùng lượt với điểm → vẫn validate được.
    current = ChatProfileState()
    delta = {"admission_method": "school_record", "total_score": 31.0}

    clean, rejections = validate_profile_delta(delta, current)

    assert clean["admission_method"] == "school_record"
    assert "total_score" not in clean
    assert rejections[0]["slot"] == "total_score"


def test_r1_score_within_scale_passes():
    current = ChatProfileState(admission_method="thpt_score")
    clean, rejections = validate_profile_delta({"total_score": 26.5}, current)
    assert clean == {"total_score": 26.5}
    assert rejections == []


def test_r1_competency_scale_allows_three_digit_score():
    current = ChatProfileState(admission_method="competency_test")
    clean, rejections = validate_profile_delta({"total_score": 105.0}, current)
    assert clean == {"total_score": 105.0}
    assert rejections == []


def test_no_validation_when_method_unknown():
    # EC-13: chưa biết phương thức → nhận tạm, KHÔNG chặn (reasoning sẽ không chấm fit).
    current = ChatProfileState()
    clean, rejections = validate_profile_delta({"total_score": 99.0}, current)
    assert clean == {"total_score": 99.0}
    assert rejections == []


def test_r2_method_change_invalidates_existing_score():
    # Điểm 99 nhận tạm trước đó; giờ user chọn thang 30 → xoá điểm + hỏi lại.
    current = ChatProfileState(total_score=99.0)
    delta = {"admission_method": "thpt_score"}

    clean, rejections = validate_profile_delta(delta, current)

    assert clean["admission_method"] == "thpt_score"
    assert clean["total_score"] is None           # apply_profile_delta sẽ xoá điểm
    assert rejections[0]["slot"] == "total_score"
    assert "99" in rejections[0]["message"]
    assert "bao nhiêu" in rejections[0]["message"]  # message tự re-ask điểm


def test_r2_not_fired_when_existing_score_fits_new_scale():
    current = ChatProfileState(total_score=27.0)
    clean, rejections = validate_profile_delta({"admission_method": "thpt_score"}, current)
    assert clean == {"admission_method": "thpt_score"}
    assert rejections == []


def test_accumulation_ops_and_non_numeric_are_ignored():
    current = ChatProfileState(admission_method="thpt_score")
    delta = {
        "explicit_preferred_majors": {"__add__": ["computer_science"]},
        "total_score": "abc",  # LLM trả rác → bỏ qua validate, giữ nguyên cho coerce hạ nguồn
    }
    clean, rejections = validate_profile_delta(delta, current)
    assert clean["explicit_preferred_majors"] == {"__add__": ["computer_science"]}
    assert rejections == []


def test_scale_none_means_no_cap():
    current = ChatProfileState(admission_method="talent_admission")
    clean, rejections = validate_profile_delta({"total_score": 120.0}, current)
    assert rejections == []
