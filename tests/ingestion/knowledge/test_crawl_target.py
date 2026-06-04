from ingestion.knowledge.crawler.config import CrawlTarget
from ingestion.knowledge.crawler.pdf_crawler import CandidatePdf, crawl_target


def _page(html: str):
    class FR:
        content_type = "text/html"
        raw_content = html.encode("utf-8")
    return FR()


# Fake site graph keyed by normalized URL.
SITE = {
    "https://a.vn/seed": _page(
        '<a href="/seed/de-an.pdf">De an</a>'
        '<a href="/seed/sub">Sub page</a>'
        '<a href="https://other.com/x.pdf">offsite pdf</a>'
    ),
    "https://a.vn/seed/sub": _page(
        '<a href="/seed/phu-luc.pdf">Phu luc</a>'
        '<a href="/seed/sub">self loop</a>'
    ),
}


def _fake_fetch(url):
    return SITE[url]


def _no_head(url, verify_ssl=True):
    return None


def test_crawl_collects_same_domain_pdfs_and_skips_offsite():
    target = CrawlTarget(school="HUST", seeds=["https://a.vn/seed"],
                         allow_domains=["a.vn"], max_depth=2, max_pages=50)
    pdfs = crawl_target(target, fetch=_fake_fetch, head=_no_head, sitemap=False)
    urls = {p.url for p in pdfs}
    assert urls == {"https://a.vn/seed/de-an.pdf", "https://a.vn/seed/phu-luc.pdf"}
    assert all(isinstance(p, CandidatePdf) and p.school == "HUST" for p in pdfs)


def test_depth_limit_blocks_deeper_pages():
    target = CrawlTarget(school="HUST", seeds=["https://a.vn/seed"],
                         allow_domains=["a.vn"], max_depth=0, max_pages=50)
    pdfs = crawl_target(target, fetch=_fake_fetch, head=_no_head, sitemap=False)
    # depth 0: only the seed page is read; its sub page is never crawled
    assert {p.url for p in pdfs} == {"https://a.vn/seed/de-an.pdf"}


def test_max_pages_caps_crawl():
    seen = []

    def counting_fetch(url):
        seen.append(url)
        return _fake_fetch(url)

    target = CrawlTarget(school="HUST", seeds=["https://a.vn/seed"],
                         allow_domains=["a.vn"], max_depth=5, max_pages=1)
    crawl_target(target, fetch=counting_fetch, head=_no_head, sitemap=False)
    assert len(seen) == 1


def test_crawl_skips_pages_blocked_by_allowed_gate():
    site = {
        "https://a.vn/seed": _page(
            '<a href="/seed/open.pdf">open</a>'
            '<a href="/seed/blocked">blocked page</a>'
        ),
        "https://a.vn/seed/blocked": _page('<a href="/seed/secret.pdf">secret</a>'),
    }

    def fetch(url):
        return site[url]

    target = CrawlTarget(school="HUST", seeds=["https://a.vn/seed"],
                         allow_domains=["a.vn"], max_depth=3, max_pages=50)
    allowed = lambda url: "/seed/blocked" not in url   # block the sub page

    pdfs = crawl_target(target, fetch=fetch, head=_no_head, sitemap=False,
                        allowed=allowed)
    urls = {p.url for p in pdfs}
    # the blocked page is never fetched, so its secret.pdf is never discovered
    assert urls == {"https://a.vn/seed/open.pdf"}
