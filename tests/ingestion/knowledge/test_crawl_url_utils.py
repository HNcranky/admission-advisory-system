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


from ingestion.knowledge.crawler.url_utils import (
    host_allowed, path_allowed, is_pdf_url,
)


def test_host_allowed_matches_subdomains():
    assert host_allowed("https://ts.hust.edu.vn/x", ["hust.edu.vn"])
    assert host_allowed("https://hust.edu.vn/x", ["hust.edu.vn"])
    assert not host_allowed("https://evil.com/x", ["hust.edu.vn"])
    assert not host_allowed("https://nothust.edu.vn.evil.com/x", ["hust.edu.vn"])


def test_path_allowed_empty_prefixes_allows_all():
    assert path_allowed("https://a.vn/anything", [])


def test_path_allowed_prefix_match():
    assert path_allowed("https://a.vn/tuyen-sinh/x", ["/tuyen-sinh"])
    assert not path_allowed("https://a.vn/news/x", ["/tuyen-sinh"])


def test_is_pdf_url_by_extension_and_content_type():
    assert is_pdf_url("https://a.vn/de-an.pdf")
    assert is_pdf_url("https://a.vn/file", content_type="application/pdf")
    assert not is_pdf_url("https://a.vn/page.html")
