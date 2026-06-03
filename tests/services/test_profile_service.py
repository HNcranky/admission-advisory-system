from services.profile_service import build_profile, extract_score, normalize_text


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
