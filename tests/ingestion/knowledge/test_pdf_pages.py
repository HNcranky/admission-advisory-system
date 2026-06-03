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
