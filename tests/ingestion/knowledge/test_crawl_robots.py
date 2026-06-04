from ingestion.knowledge.crawler.robots import build_robots_checker


class _FR:
    def __init__(self, body: bytes):
        self.raw_content = body


def test_respect_false_allows_everything():
    allowed = build_robots_checker(respect=False)
    assert allowed("https://a.vn/anything")


def test_disallow_blocks_matching_path():
    def fetch(url):
        return _FR(b"User-agent: *\nDisallow: /private\n")

    allowed = build_robots_checker(fetch=fetch, respect=True)
    assert allowed("https://a.vn/public/x")
    assert not allowed("https://a.vn/private/x")


def test_missing_robots_allows():
    def fetch(url):
        raise RuntimeError("404")

    allowed = build_robots_checker(fetch=fetch, respect=True)
    assert allowed("https://a.vn/anything")


def test_robots_fetched_once_per_host():
    calls = []

    def fetch(url):
        calls.append(url)
        return _FR(b"User-agent: *\nDisallow:\n")

    allowed = build_robots_checker(fetch=fetch, respect=True)
    allowed("https://a.vn/1")
    allowed("https://a.vn/2")
    assert calls == ["https://a.vn/robots.txt"]   # parsed once, then cached
