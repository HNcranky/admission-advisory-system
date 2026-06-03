from ingestion.parsers.vnu_uet_proposal_pdf_parser import VnuUetProposalPdfParser


def _patch_pdf_text(monkeypatch, text: str) -> None:
    monkeypatch.setattr(
        "ingestion.parsers.vnu_uet_proposal_pdf_parser._extract_pdf_text",
        lambda content: text,
    )


def test_parser_extracts_each_row_quota_from_main_table(monkeypatch):
    parser = VnuUetProposalPdfParser()
    pdf_text = (
        "Tổng số lượng tuyển sinh: 4020 Mã trường: QHI\n"
        "Mã Số lượng\n"
        "Mã Phương thức tuyển\n"
        "TT xét Tên ngành xét tuyển Tên nhóm ngành tuyển\n"
        "ngành sinh\n"
        "1. CN1 Công nghệ thông tin 7480201 Công nghệ thông tin 460\n"
        "2. CN2 Kỹ thuật máy tính 7480106 Máy tính 400\n"
        "3. CN3 Vật lý kỹ thuật 7520401 Vật lý kỹ thuật 160 1.Phương thức: xét\n"
        "tuyển thẳng.\n"
        "(-) * Chương trình đào tạo thí điểm.\n"
    )
    _patch_pdf_text(monkeypatch, pdf_text)

    facts = parser.parse(
        content=b"%PDF-1.4",
        source_url="https://tuyensinh.uet.vnu.edu.vn/proposal.pdf",
        school_id="vnu_uet",
        school_name="Truong Dai hoc Cong nghe - DHQGHN",
    )

    facts_by_code = {fact.program_code: fact for fact in facts}
    assert len(facts) == 3
    assert facts_by_code["CN1"].program_name == "Công nghệ thông tin"
    assert facts_by_code["CN1"].quota_raw == "460"
    assert facts_by_code["CN2"].program_name == "Kỹ thuật máy tính"
    assert facts_by_code["CN2"].quota_raw == "400"
    # Row 3 trails into "1.Phương thức: xét" — the single digit "1" must not
    # be picked up instead of the actual quota 160.
    assert facts_by_code["CN3"].quota_raw == "160"
    assert facts_by_code["CN1"].source_reference.source_id == "vnuhn_proposal_pdf_2026"
    assert facts_by_code["CN1"].source_reference.trust_level == 5


def test_parser_assigns_quota_per_row_without_swap_for_cn12_cn13(monkeypatch):
    parser = VnuUetProposalPdfParser()
    pdf_text = (
        "Tổng số lượng tuyển sinh: 4020 Mã trường: QHI\n"
        "12. CN12 Trí tuệ nhân tạo 7480107 Máy tính 320\n"
        "13. CN13 Kỹ thuật năng lượng* 7520406 Vật lý kỹ thuật 60\n"
        "(-) * Chương trình đào tạo thí điểm.\n"
    )
    _patch_pdf_text(monkeypatch, pdf_text)

    facts = parser.parse(
        content=b"%PDF-1.4",
        source_url="https://tuyensinh.uet.vnu.edu.vn/proposal.pdf",
        school_id="vnu_uet",
        school_name="Truong Dai hoc Cong nghe - DHQGHN",
    )

    assert [(fact.program_code, fact.quota_raw) for fact in facts] == [
        ("CN12", "320"),
        ("CN13", "60"),
    ]


def test_parser_augments_program_name_when_row_starts_with_parenthesis(monkeypatch):
    parser = VnuUetProposalPdfParser()
    pdf_text = (
        "Tổng số lượng tuyển sinh: 4020\n"
        "Khoa học dữ liệu\n"
        "19. CN20 (Chương trình Khoa học và Kỹ thuật dữ 7460108 Toán học 120\n"
        "liệu)\n"
        "(-) * Chương trình đào tạo thí điểm.\n"
    )
    _patch_pdf_text(monkeypatch, pdf_text)

    facts = parser.parse(
        content=b"%PDF-1.4",
        source_url="https://tuyensinh.uet.vnu.edu.vn/proposal.pdf",
        school_id="vnu_uet",
        school_name="Truong Dai hoc Cong nghe - DHQGHN",
    )

    assert len(facts) == 1
    fact = facts[0]
    assert fact.program_code == "CN20"
    assert fact.program_name.startswith("Khoa học dữ liệu")
    assert "Chương trình Khoa học và Kỹ thuật dữ" in fact.program_name
    assert fact.quota_raw == "120"


def test_parser_returns_empty_when_main_section_missing(monkeypatch):
    parser = VnuUetProposalPdfParser()
    _patch_pdf_text(monkeypatch, "Just some other PDF text without the marker.")

    facts = parser.parse(
        content=b"%PDF-1.4",
        source_url="https://tuyensinh.uet.vnu.edu.vn/proposal.pdf",
        school_id="vnu_uet",
        school_name="Truong Dai hoc Cong nghe - DHQGHN",
    )

    assert facts == []


def test_parser_stops_at_footnote_marker(monkeypatch):
    parser = VnuUetProposalPdfParser()
    pdf_text = (
        "Tổng số lượng tuyển sinh: 4020\n"
        "1. CN1 Công nghệ thông tin 7480201 Công nghệ thông tin 460\n"
        "(-) * Chương trình đào tạo thí điểm.\n"
        "99. CN99 Chương trình bịa 9999999 Không tồn tại 999\n"
    )
    _patch_pdf_text(monkeypatch, pdf_text)

    facts = parser.parse(
        content=b"%PDF-1.4",
        source_url="https://tuyensinh.uet.vnu.edu.vn/proposal.pdf",
        school_id="vnu_uet",
        school_name="Truong Dai hoc Cong nghe - DHQGHN",
    )

    codes = [fact.program_code for fact in facts]
    assert codes == ["CN1"]
