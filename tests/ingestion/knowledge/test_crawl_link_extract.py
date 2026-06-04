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
