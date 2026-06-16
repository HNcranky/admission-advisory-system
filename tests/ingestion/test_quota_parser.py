from ingestion.normalization.quota_parser import parse_quota


def test_parse_quota_none_returns_none():
    assert parse_quota(None) is None
    assert parse_quota("") is None


def test_parse_quota_pure_digits_is_exact():
    q = parse_quota("300")
    assert q.value == 300 and q.quota_type == "exact"


def test_parse_quota_range():
    q = parse_quota("khoảng 200-300")
    assert q.min_value == 200 and q.max_value == 300 and q.quota_type == "range"


def test_parse_quota_with_label_is_exact():
    q = parse_quota("300 chỉ tiêu")
    assert q.value == 300 and q.quota_type == "exact"


def test_parse_quota_khoang_with_number_is_exact_not_approximate():
    # QUIRK pinned: exact_match (\d+) bắt trước nhánh "khoảng" ⇒ exact, KHÔNG approximate.
    q = parse_quota("khoảng 250")
    assert q.value == 250 and q.quota_type == "exact"


def test_parse_quota_unknown_keyword():
    assert parse_quota("chưa công bố").quota_type == "unknown"


def test_parse_quota_no_match_falls_back_unknown():
    assert parse_quota("tuyển sinh").quota_type == "unknown"
