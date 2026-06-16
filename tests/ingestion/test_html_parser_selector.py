import pytest

from ingestion.parsers.html_parser import ContentSelectorNotFound, parse_html

HTML = b"""
<html><body>
  <nav>MENU LINK</nav>
  <div id="content"><p>Noi dung chinh cua trang du dai de tao mot chunk hop le.</p></div>
  <footer>FOOTER JUNK</footer>
</body></html>
"""

HTML_WITH_TABLE = b"""
<html><body>
<article>
<p>Gioi thieu</p>
<table>
  <tr><th>Nganh</th><th>Chi tieu</th><th>Diem chuan</th></tr>
  <tr><td>CNTT</td><td>200</td><td>28.5</td></tr>
  <tr><td>Dien tu</td><td>150</td><td>27.0</td></tr>
</table>
<p>Ket luan</p>
</article>
</body></html>
"""

HTML_WITH_HEADERLESS_TABLE = b"""
<html><body><article>
<table>
  <tr><td>A</td><td>B</td></tr>
  <tr><td>C</td><td>D</td></tr>
</table>
</article></body></html>
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


def test_table_rendered_as_markdown_in_text():
    parsed = parse_html(HTML_WITH_TABLE, "https://x")
    text = parsed.text
    # header row
    assert "| Nganh |" in text
    assert "| Chi tieu |" in text
    assert "| Diem chuan |" in text
    # separator
    assert "| --- |" in text
    # data rows
    assert "| CNTT | 200 | 28.5 |" in text
    assert "| Dien tu | 150 | 27.0 |" in text
    # surrounding prose preserved
    assert "Gioi thieu" in text
    assert "Ket luan" in text


def test_table_without_th_uses_first_row_as_header():
    parsed = parse_html(HTML_WITH_HEADERLESS_TABLE, "https://x")
    text = parsed.text
    assert "| A | B |" in text
    assert "| --- | --- |" in text
    assert "| C | D |" in text
