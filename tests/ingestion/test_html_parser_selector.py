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

# Mirrors the HUST program-page shape: sectioned <h2> headings, label/value
# lists, bold labels, and whitespace-padded inline runs.
HTML_STRUCTURED = b"""
<html><body><div class="container">
  <section>
    <h2 class="sec-title">Tong quan</h2>
    <div class="sec-con">
      <ul>
        <li>Ngon ngu dao tao: Tieng Anh</li>
        <li>Ma xet tuyen:        IT-E15</li>
      </ul>
      <p><strong>Gioi thieu</strong></p>
      <p>Chuong trinh dao tao chuyen gia an toan khong gian so.</p>
    </div>
  </section>
  <section>
    <h2 class="sec-title">Co hoi viec lam</h2>
    <div class="sec-con"><p>Chuyen gia van hanh, quan tri he thong.</p></div>
  </section>
</div></body></html>
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


def test_headings_rendered_as_markdown():
    text = parse_html(HTML_STRUCTURED, "https://x").text
    assert "## Tong quan" in text
    assert "## Co hoi viec lam" in text


def test_list_items_rendered_as_markdown_bullets():
    text = parse_html(HTML_STRUCTURED, "https://x").text
    assert "- Ngon ngu dao tao: Tieng Anh" in text
    # inner whitespace runs collapsed to a single space
    assert "- Ma xet tuyen: IT-E15" in text


def test_bold_label_preserved():
    text = parse_html(HTML_STRUCTURED, "https://x").text
    assert "**Gioi thieu**" in text


def test_blocks_separated_by_blank_lines_for_chunking():
    # The chunker splits on blank lines; structured output must expose them so
    # each section becomes its own chunk boundary instead of one giant block.
    text = parse_html(HTML_STRUCTURED, "https://x").text
    assert "\n\n" in text
    # heading and following list are distinct blocks
    assert "## Tong quan\n\n- Ngon ngu" in text
    # no run of 3+ newlines
    assert "\n\n\n" not in text


HTML_WITH_BREADCRUMB = b"""
<html><head><title>Title Tag</title></head><body><div class="container">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a>Trang chu</a></li>
    <li class="breadcrumb-item active">Ky thuat O to</li>
  </ol>
  <section><h2 class="sec-title">Tong quan</h2><p>Noi dung.</p></section>
</div></body></html>
"""

HTML_NO_BREADCRUMB = b"""
<html><head><title>Title Tag</title></head><body><div class="container">
  <section><h2 class="sec-title">Tong quan</h2><p>Noi dung.</p></section>
</div></body></html>
"""

HTML_NO_LABEL_SOURCES = b"""
<html><body><div class="container">
  <section><h2 class="sec-title">Tong quan</h2><p>Noi dung.</p></section>
</div></body></html>
"""


def test_content_label_from_breadcrumb_active():
    parsed = parse_html(HTML_WITH_BREADCRUMB, "https://x/ky-thuat-o-to")
    assert parsed.content_label == "Ky thuat O to"


def test_content_label_falls_back_to_title():
    parsed = parse_html(HTML_NO_BREADCRUMB, "https://x/ky-thuat-o-to")
    assert parsed.content_label == "Title Tag"


def test_content_label_falls_back_to_slug():
    parsed = parse_html(HTML_NO_LABEL_SOURCES, "https://x/ky-thuat-o-to")
    assert parsed.content_label == "ky thuat o to"
