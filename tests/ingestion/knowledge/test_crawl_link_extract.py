from ingestion.knowledge.crawler.link_extract import extract_links

HTML = b"""
<html><body>
  <a href="/tuyen-sinh/de-an-2026.pdf">De an tuyen sinh 2026</a>
  <a href="https://hust.edu.vn/news/abc.htm">  Tin tuc  </a>
  <a href="#top">skip anchor</a>
  <a href="mailto:x@hust.edu.vn">skip mail</a>
  <a>no href</a>
</body></html>
"""


def test_extracts_absolute_urls_and_anchor_text():
    links = extract_links(HTML, "https://hust.edu.vn/tuyen-sinh.htm")
    urls = {u for u, _ in links}
    assert "https://hust.edu.vn/tuyen-sinh/de-an-2026.pdf" in urls
    assert "https://hust.edu.vn/news/abc.htm" in urls


def test_skips_fragment_mailto_and_missing_href():
    links = extract_links(HTML, "https://hust.edu.vn/tuyen-sinh.htm")
    urls = {u for u, _ in links}
    assert not any(u.startswith("mailto:") for u in urls)
    assert "https://hust.edu.vn/tuyen-sinh.htm#top" not in urls
    assert len(links) == 2


def test_anchor_text_is_stripped():
    links = dict(extract_links(HTML, "https://hust.edu.vn/tuyen-sinh.htm"))
    assert links["https://hust.edu.vn/news/abc.htm"] == "Tin tuc"


from ingestion.knowledge.crawler.link_extract import parse_sitemap_locs

URLSET = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://a.vn/de-an.pdf</loc></url>
  <url><loc>https://a.vn/page</loc></url>
</urlset>"""

SITEMAPINDEX = b"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://a.vn/sitemap-1.xml</loc></sitemap>
</sitemapindex>"""


def test_parse_urlset_returns_all_locs():
    assert parse_sitemap_locs(URLSET) == ["https://a.vn/de-an.pdf", "https://a.vn/page"]


def test_parse_sitemapindex_returns_nested_sitemap_locs():
    assert parse_sitemap_locs(SITEMAPINDEX) == ["https://a.vn/sitemap-1.xml"]


def test_parse_invalid_xml_returns_empty():
    assert parse_sitemap_locs(b"not xml at all") == []
