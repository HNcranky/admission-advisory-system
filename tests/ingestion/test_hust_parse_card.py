"""Characterization tests for HustProgramParser._parse_card.

Locks the CURRENT behavior on the committed fixture before _parse_card is
decomposed (audit §3 / plan PR9). Detail-page fetching is disabled via
source_metadata so no network I/O happens.
"""
import json
from pathlib import Path

from ingestion.parsers.hust_program_parser import HustProgramParser

FIXTURE = Path("ingestion/parsers/_fixtures/hust_program_card.html").read_bytes()


def _parse():
    parser = HustProgramParser()
    return parser.parse(
        FIXTURE,
        "https://ts.hust.edu.vn/",
        source_metadata={"fetch_detail_pages": False},  # no network
    )


def test_parse_card_extracts_single_fact():
    assert len(_parse()) == 1


def test_parse_card_extracts_code_and_name():
    f = _parse()[0]
    assert f.program_code == "BF-E12"
    assert f.program_name == "Kỹ thuật thực phẩm (Chương trình tiên tiến)"


def test_parse_card_extracts_combos_deduped():
    f = _parse()[0]
    assert f.subject_combinations_raw == ["K00", "A00", "B00", "D07", "K01"]


def test_parse_card_quota_defaults_to_zero_without_quota_line():
    f = _parse()[0]
    assert f.quota_raw == "0"


def test_parse_card_tuition_sentinel_when_detail_fetch_disabled():
    f = _parse()[0]
    assert f.tuition_raw == "Không thông tin"


def test_parse_card_extracts_language_and_faculty_in_conditions():
    f = _parse()[0]
    cond = json.loads(f.additional_conditions_raw)
    assert cond["language"] == "Tiếng Anh"
    assert cond["faculty"] == "Trường Hóa và Khoa học sự sống"
    assert cond["detail_url"] == "https://ts.hust.edu.vn/programs/bf-e12"


# --- per-field helpers (PR9 decomposition) -----------------------------------

def test_extract_program_header_from_h3():
    from bs4 import BeautifulSoup
    card = BeautifulSoup(
        "<div><h3>01 - ( BF-E12 ) Kỹ thuật thực phẩm</h3></div>", "html.parser"
    ).div
    parser = HustProgramParser()
    name, code = parser._extract_program_header(card, card.get_text("\n", strip=True))
    assert code == "BF-E12"
    assert "Kỹ thuật thực phẩm" in name


def test_extract_quota_defaults_to_zero_without_label():
    from bs4 import BeautifulSoup
    card = BeautifulSoup("<div><p>Không có chỉ tiêu</p></div>", "html.parser").div
    parser = HustProgramParser()
    assert parser._extract_quota(card) == "0"
