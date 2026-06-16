from ingestion.parsers.hust_program_parser import _normalize_for_match


def test_normalize_for_match_strips_accents_and_lowercases():
    assert _normalize_for_match("Xét tuyển") == "xet tuyen"


def test_normalize_for_match_now_collapses_whitespace():
    # FIXED by PR7: gộp khoảng trắng trong (trước đây giữ nguyên).
    assert _normalize_for_match("xet   tuyen") == "xet tuyen"


def test_normalize_for_match_now_maps_d_stroke():
    # FIXED by PR7: "đ" -> "d" (trước đây giữ nguyên "đ").
    assert _normalize_for_match("đại học") == "dai hoc"
