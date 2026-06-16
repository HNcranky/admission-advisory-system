from ingestion.parsers.hust_program_parser import _normalize_for_match


def test_normalize_for_match_strips_accents_and_lowercases():
    assert _normalize_for_match("Xét tuyển") == "xet tuyen"


def test_normalize_for_match_does_not_collapse_internal_whitespace():
    # QUIRK pinned: helper hust chỉ .lower().strip(), KHÔNG gộp khoảng trắng trong.
    assert _normalize_for_match("xet   tuyen") == "xet   tuyen"


def test_normalize_for_match_keeps_d_stroke():
    # QUIRK pinned (BUG): "đ" KHÔNG được map sang "d" (PR7 sẽ đổi giá trị này).
    out = _normalize_for_match("đại học")
    assert out == "đai hoc"
