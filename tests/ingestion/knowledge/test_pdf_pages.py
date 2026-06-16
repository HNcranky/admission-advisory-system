import pytest

from ingestion.knowledge import pdf_pages


def test_pages_to_marked_text_inserts_trang_markers():
    pages = [(1, "Học phí năm 2026."), (2, "Học bổng KKHT.")]
    text = pdf_pages.pages_to_marked_text(pages)
    assert text.startswith("[Trang 1]\n")
    assert "[Trang 2]\n" in text
    assert "Học phí năm 2026." in text
    assert "Học bổng KKHT." in text


def test_pages_to_marked_text_separates_pages_with_blank_line():
    pages = [(1, "A"), (2, "B")]
    text = pdf_pages.pages_to_marked_text(pages)
    # blank line between pages so the chunker treats each page as a block
    assert "\n\n[Trang 2]" in text


def test_pages_to_marked_text_skips_empty_pages():
    pages = [(1, "A"), (2, "   "), (3, "C")]
    text = pdf_pages.pages_to_marked_text(pages)
    assert "[Trang 2]" not in text
    assert "[Trang 3]" in text


def test_extract_pages_reads_real_pdf():
    # Minimal valid one-page PDF generated inline so the test needs no fixture file.
    pdf_bytes = _one_page_pdf("Hello Trang")
    pages = pdf_pages.extract_pages(pdf_bytes)
    assert len(pages) == 1
    assert pages[0][0] == 1
    assert "Hello" in pages[0][1]


def test_extract_pages_renders_pdf_table_as_markdown():
    pdf_bytes = _one_page_pdf_with_table()
    pages = pdf_pages.extract_pages(pdf_bytes)
    assert len(pages) == 1
    text = pages[0][1]
    # separator line proves markdown table format, not plain dump
    assert "| --- |" in text
    # header row
    assert "| Nganh |" in text
    # data rows
    assert "| CNTT |" in text
    assert "| Dien tu |" in text


def _one_page_pdf_with_table() -> bytes:
    pytest.importorskip("reportlab")
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    data = [
        ["Nganh", "Chi tieu", "Diem chuan"],
        ["CNTT", "200", "28.5"],
        ["Dien tu", "150", "27.0"],
    ]
    tbl = Table(data)
    tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    doc.build([tbl])
    return buf.getvalue()


def _one_page_pdf(text: str) -> bytes:
    # Build a tiny PDF with pdfplumber's dependency (pdfminer) round-trippable
    # text using reportlab if available; otherwise skip cleanly.
    import pytest
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    from io import BytesIO

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, text)
    c.showPage()
    c.save()
    return buf.getvalue()
