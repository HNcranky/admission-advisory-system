from pathlib import Path

from bs4 import BeautifulSoup

from ingestion.parsers.vnu_uet_admission_parser import (
    _SELECTOR_PRIORITY,
    VnuUetAdmissionParser,
    _is_program_quota_table,
    _table_rows,
)


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "ingestion"
    / "parsers"
    / "_fixtures"
    / "vnu_uet_admission_page.html"
)


def test_vnu_uet_parser_skips_du_bi_allocation_table_from_fixture():
    parser = VnuUetAdmissionParser()

    facts = parser.parse(
        content=FIXTURE.read_bytes(),
        source_url="https://uet.vnu.edu.vn/tuyen-sinh/",
        school_id="vnu_uet",
        school_name="Truong Dai hoc Cong nghe - DHQGHN",
    )

    # The homepage's only per-program quota table is the dự bị 1% allocation,
    # which is intentionally excluded to avoid fabricating quota conflicts
    # against the proposal PDF's full-method totals.
    assert facts == []


def test_is_program_quota_table_rejects_du_bi_allocation_table():
    soup = BeautifulSoup(FIXTURE.read_bytes(), "html.parser")
    du_bi_tables = [
        table
        for table in soup.select("table")
        if any(
            "Ngưỡng ĐBCL" in cell.get_text(" ", strip=True)
            for cell in table.find_all(["th", "td"])
        )
    ]
    assert du_bi_tables, "Fixture must still contain the dự bị allocation table"

    for table in du_bi_tables:
        assert _is_program_quota_table(_table_rows(table)) is False


def test_vnu_uet_parser_prefers_fixture_confirmed_selector():
    assert _SELECTOR_PRIORITY[0] == "div.dev-faq-content table"
