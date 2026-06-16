"""Characterization tests for _extract_tuition_value.

Locks the CURRENT behavior of the 4 fallback strategies before the function is
split into per-fallback helpers (audit §3 / plan PR8).
"""
from bs4 import BeautifulSoup

from ingestion.parsers.hust_program_parser import _extract_tuition_value


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
