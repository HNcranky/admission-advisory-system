"""Characterization tests for _extract_tuition_value.

Locks the CURRENT behavior of the 4 fallback strategies before the function is
split into per-fallback helpers (audit §3 / plan PR8).
"""
from bs4 import BeautifulSoup

from ingestion.parsers.hust_program_parser import (
    _extract_tuition_value,
    _tuition_from_lines,
    _tuition_from_segment,
)


def test_tuition_from_strong_in_tab1_li():
    html = (
        '<div id="tab_1"><div><div class="wrap_view"><ul>'
        "<li>Học phí: <strong>55 - 65</strong></li></ul></div></div></div>"
    )
    soup = BeautifulSoup(html, "html.parser")
    assert _extract_tuition_value(soup, []) == "55-65"


def test_tuition_fallback_to_lines_range():
    soup = BeautifulSoup("<html></html>", "html.parser")
    lines = ["Học phí dự kiến: 24 - 30 triệu/năm"]
    assert _extract_tuition_value(soup, lines) == "24-30"


def test_tuition_fallback_to_lines_colon_value():
    soup = BeautifulSoup("<html></html>", "html.parser")
    assert _extract_tuition_value(soup, ["Học phí: 30 triệu"]) == "30 triệu"


def test_tuition_fallback_to_keyword_segment():
    soup = BeautifulSoup("<html></html>", "html.parser")
    lines = ["Học phí năm học 2026 áp dụng mức thu theo quy định"]
    assert _extract_tuition_value(soup, lines) == (
        "Học phí năm học 2026 áp dụng mức thu theo quy định"
    )


def test_tuition_returns_sentinel_when_absent():
    soup = BeautifulSoup("<html></html>", "html.parser")
    assert _extract_tuition_value(soup, []) == "Không thông tin"


# --- per-fallback helpers (PR8 split) ----------------------------------------

def test_tuition_from_lines_handles_colon_value():
    assert _tuition_from_lines(["Học phí: 30 triệu"]) == "30 triệu"


def test_tuition_from_lines_returns_none_without_keyword():
    assert _tuition_from_lines(["Không liên quan"]) is None


def test_tuition_from_segment_returns_none_when_no_keyword():
    assert _tuition_from_segment(["Không liên quan"]) is None


def test_tuition_from_segment_returns_keyword_segment():
    lines = ["Học phí năm học 2026 áp dụng mức thu theo quy định"]
    assert _tuition_from_segment(lines) == (
        "Học phí năm học 2026 áp dụng mức thu theo quy định"
    )
