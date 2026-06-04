from ingestion.knowledge.crawler.url_utils import normalize_url


def test_strips_fragment():
    assert normalize_url("https://a.vn/p#sec") == "https://a.vn/p"


def test_strips_trailing_slash_but_keeps_root():
    assert normalize_url("https://a.vn/p/") == "https://a.vn/p"
    assert normalize_url("https://a.vn/") == "https://a.vn/"


def test_lowercases_scheme_and_host_keeps_path_case():
    assert normalize_url("HTTPS://A.VN/Path") == "https://a.vn/Path"


def test_keeps_query():
    assert normalize_url("https://a.vn/p?id=2") == "https://a.vn/p?id=2"
