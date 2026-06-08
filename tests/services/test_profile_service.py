from services.profile_service import (
    build_profile,
    extract_preferred_majors,
    extract_score,
    normalize_text,
)


def test_normalize_text_maps_d_with_stroke_to_d():
    # "đ" (U+0111) has no NFKD decomposition, so a naive ascii-strip drops it
    # entirely ("điểm" -> "iem"). It must map to a plain "d" instead.
    assert normalize_text("điểm") == "diem"
    assert normalize_text("được") == "duoc"
    assert normalize_text("Đại học") == "dai hoc"


def test_extract_score_handles_vietnamese_diem():
    assert extract_score(normalize_text("29 điểm")) == 29.0
    assert extract_score(normalize_text("được 29 điểm")) == 29.0
    assert extract_score(normalize_text("khoảng 27.5 điểm")) == 27.5


def test_build_profile_extracts_score_from_bare_vietnamese_reply():
    profile = build_profile("29 điểm")
    assert profile.total_score == 29.0
    assert "total_score" not in profile.missing_slots


def test_alias_match_requires_word_boundary():
    # "hoa hoc" (Hóa học) nằm BÊN TRONG "k|hoa hoc may tinh" — substring thuần
    # gán nhầm tag chemistry cho mọi câu nhắc Khoa học máy tính.
    majors = extract_preferred_majors(
        normalize_text("Em muốn vào ngành Khoa học máy tính của Bách khoa Hà Nội")
    )
    assert "computer_science" in majors
    assert "chemistry" not in majors


def test_alias_word_boundary_still_matches_real_mention():
    majors = extract_preferred_majors(normalize_text("Em thích ngành hóa học"))
    assert "chemistry" in majors


def test_variant_longest_match_suppresses_base_program_troy():
    # Câu tự nhiên về chương trình hợp tác Troy phải về id variant,
    # KHÔNG lẫn computer_science gốc (điểm chuẩn khác hẳn).
    majors = extract_preferred_majors(
        normalize_text(
            "Em quan tâm chương trình Khoa học máy tính hợp tác ĐH Troy của Bách khoa"
        )
    )
    assert majors == ["computer_science_troy"]


def test_variant_longest_match_suppresses_base_program_viet_nhat():
    majors = extract_preferred_majors(
        normalize_text("Em thích Công nghệ thông tin Việt Nhật của Bách khoa")
    )
    assert "information_technology_viet_nhat" in majors
    assert "information_technology_uet" not in majors
