from services.profile.admission_methods import (
    METHOD_CODES,
    SCORE_SCALES,
    THANG_30_METHODS,
    method_display,
    parse_admission_method,
)


def test_method_codes_match_methods_json_vocabulary():
    assert METHOD_CODES == {
        "thpt_score", "school_record", "competency_test", "combined", "talent_admission",
    }


def test_score_scales_per_method():
    assert SCORE_SCALES["thpt_score"] == 30.0
    assert SCORE_SCALES["school_record"] == 30.0
    assert SCORE_SCALES["competency_test"] == 150.0
    assert SCORE_SCALES["combined"] == 100.0
    assert SCORE_SCALES["talent_admission"] is None  # không validate trần


def test_thang_30_methods_only_thpt_and_school_record():
    assert THANG_30_METHODS == {"thpt_score", "school_record"}


def test_parse_from_canonical_alias_with_diacritics():
    assert parse_admission_method("em xét điểm thi tốt nghiệp THPT") == "thpt_score"
    assert parse_admission_method("xét học bạ 3 năm") == "school_record"


def test_parse_from_conversational_alias_without_diacritics():
    assert parse_admission_method("em thi dgnl") == "competency_test"
    assert parse_admission_method("xet tuyen ket hop") == "combined"
    assert parse_admission_method("em duoc tuyen thang") == "talent_admission"


def test_parse_short_alias_uses_word_boundary():
    # "TSA" là alias ngắn → word boundary; không match bên trong từ khác.
    assert parse_admission_method("em thi TSA được 80") == "competency_test"
    assert parse_admission_method("em học lớp tsanv") is None


def test_parse_longest_alias_wins():
    # "điểm thi đánh giá năng lực" phải ra competency_test (alias dài hơn thắng
    # alias hội thoại "diem thi" của thpt_score).
    assert parse_admission_method("điểm thi đánh giá năng lực của em là 105") == "competency_test"


def test_parse_no_match_returns_none():
    assert parse_admission_method("em muốn học ở Hà Nội") is None
    assert parse_admission_method("") is None
    assert parse_admission_method(None) is None


def test_method_display_has_vietnamese_labels():
    assert method_display("thpt_score") == "điểm thi tốt nghiệp THPT"
    assert method_display("school_record") == "học bạ"
    assert method_display("competency_test") == "đánh giá năng lực / tư duy"
    assert method_display("combined") == "xét tuyển kết hợp"
    assert method_display("talent_admission") == "xét tuyển tài năng / tuyển thẳng"
    assert method_display("unknown_code") == "unknown_code"  # fallback an toàn


from types import SimpleNamespace

from services.profile.admission_methods import candidate_method_codes


def _candidate(method, school_id="hust"):
    return SimpleNamespace(admission_method=method, school_id=school_id)


def test_candidate_codes_accepts_raw_canonical_code():
    # Fixture/dev rows lưu thẳng mã code.
    assert candidate_method_codes(_candidate("thpt_score")) == {"thpt_score"}


def test_candidate_codes_maps_display_name():
    assert candidate_method_codes(_candidate("Xét điểm thi TN THPT")) == {"thpt_score"}


def test_candidate_codes_maps_joined_display_names():
    codes = candidate_method_codes(_candidate("Xét điểm thi TN THPT; Xét tuyển kết hợp"))
    assert codes == {"thpt_score", "combined"}


def test_candidate_codes_school_specific_display():
    assert candidate_method_codes(
        _candidate("Đánh giá tư duy (TSA)", school_id="hust")
    ) == {"competency_test"}


def test_candidate_codes_unknown_returns_none():
    # Không map được → None = unknown → caller KHÔNG gate theo phương thức.
    assert candidate_method_codes(_candidate("Phương thức bí ẩn XYZ")) is None
    assert candidate_method_codes(_candidate(None)) is None
    assert candidate_method_codes(_candidate("")) is None
