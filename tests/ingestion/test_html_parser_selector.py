import pytest

from ingestion.parsers.html_parser import ContentSelectorNotFound, parse_html

HTML = b"""
<html><body>
  <nav>MENU LINK</nav>
  <div id="content"><p>Noi dung chinh cua trang du dai de tao mot chunk hop le.</p></div>
  <footer>FOOTER JUNK</footer>
</body></html>
"""


def test_selector_extracts_only_targeted_region():
    parsed = parse_html(HTML, "https://x", selector="#content")
    assert "Noi dung chinh" in parsed.text
    assert "MENU LINK" not in parsed.text
    assert "FOOTER JUNK" not in parsed.text


def test_selector_no_match_raises():
    with pytest.raises(ContentSelectorNotFound):
        parse_html(HTML, "https://x", selector="#nope")


def test_selector_none_uses_fallback_unchanged():
    # Default path: _find_content_area finds <div id="content"> via its fallback
    # chain, so the region is extracted and nav/footer are still dropped.
    parsed = parse_html(HTML, "https://x")
    assert "Noi dung chinh" in parsed.text
    assert "FOOTER JUNK" not in parsed.text
