"""Tests for HustAnnouncementHtmlParser against the captured fixture HTML."""
from pathlib import Path
import pytest

from ingestion.parsers.hust_announcement_html_parser import HustAnnouncementHtmlParser


FIXTURE = (
    Path(__file__).parent.parent.parent
    / "ingestion" / "parsers" / "_fixtures" / "hust_announcement_2026.html"
)


@pytest.mark.skipif(not FIXTURE.exists(), reason="Fixture HTML not snapshotted")
def test_parses_full_program_table():
    parser = HustAnnouncementHtmlParser()
    facts = parser.parse(
        content=FIXTURE.read_bytes(),
        source_url="https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026",
    )
    assert len(facts) >= 60, (
        f"Expected >=60 facts from HUST announcement HTML (pre-flight saw 68), got {len(facts)}"
    )
    for f in facts[:3]:
        assert f.program_name, "program_name must be non-empty"
        assert f.quota_raw and f.quota_raw.isdigit(), \
            f"quota_raw should be digit string, got {f.quota_raw!r}"


@pytest.mark.skipif(not FIXTURE.exists(), reason="Fixture HTML not snapshotted")
def test_method_flags_decoded():
    parser = HustAnnouncementHtmlParser()
    facts = parser.parse(
        content=FIXTURE.read_bytes(),
        source_url="https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026",
    )
    method_set = [f for f in facts if f.admission_method_raw]
    assert method_set, (
        "No facts have admission_method_raw — flag decoding from the Ö-glyph columns "
        "failed. Inspect the fixture's method-column glyphs."
    )
