from pathlib import Path

from ingestion.parsers.tuyensinh247_cutoff_parser import Tuyensinh247CutoffParser

_URL = "https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html"

_SYNTHETIC = """
<html><body>
<h3>Điểm chuẩn theo phương thức <b>Điểm thi THPT</b> năm <b>2025</b></h3>
<table>
  <tr><th>Tên ngành</th><th>Tổ hợp môn</th><th>Điểm chuẩn</th><th>Ghi chú</th></tr>
  <tr><td colspan="4">Tra cứu tại: Tuyensinh247.com - Học trực tuyến</td></tr>
  <tr><td>Khoa học máy tính</td><td>A00; A01</td><td>28,25</td><td>Môn chính: Toán</td></tr>
  <tr><td>Kỹ thuật máy tính</td><td>A00; A01</td><td>27.5</td><td></td></tr>
</table>
<h3>Điểm chuẩn theo phương thức Điểm Đánh giá Tư duy năm 2025</h3>
<table>
  <tr><th>Tên ngành</th><th>Tổ hợp môn</th><th>Điểm chuẩn</th><th>Ghi chú</th></tr>
  <tr><td>Khoa học máy tính</td><td></td><td>83.9</td><td></td></tr>
</table>
<h3>Bài viết liên quan</h3>
<table><tr><th>Tiêu đề</th></tr><tr><td>Tin tức 1000</td></tr></table>
</body></html>
"""


def test_parses_synthetic_sections():
    facts = Tuyensinh247CutoffParser().parse(_SYNTHETIC.encode("utf-8"), _URL)
    assert len(facts) == 3  # row rác + bảng không khớp heading bị loại
    f = facts[0]
    assert f.program_name == "Khoa học máy tính"
    assert f.program_code is None
    assert f.admission_method_raw == "Điểm thi THPT"
    assert f.cutoff_year == 2025
    assert f.cutoff_score_raw == "28,25"
    assert f.subject_combinations_raw == ["A00", "A01"]
    assert f.note_raw == "Môn chính: Toán"
    assert f.source_reference.trust_level == 3
    assert facts[1].cutoff_score_raw == "27.5"
    assert facts[2].admission_method_raw == "Điểm Đánh giá Tư duy"
    assert facts[2].cutoff_score_raw == "83.9"


def test_year_filter_excludes_other_years():
    facts = Tuyensinh247CutoffParser().parse(
        _SYNTHETIC.encode("utf-8"), _URL, cutoff_year=2024,
    )
    assert facts == []


def test_returns_empty_when_no_matching_heading():
    facts = Tuyensinh247CutoffParser().parse(
        "<html><h3>Tin tuyển sinh</h3><table><tr><th>Tiêu đề</th></tr></table></html>".encode("utf-8"),
        _URL,
    )
    assert facts == []


def test_parses_real_fixture_snapshot():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "tsn247_bka_cutoff_2025.html"
    facts = Tuyensinh247CutoffParser().parse(fixture.read_bytes(), _URL)
    # Snapshot 2026-06-05: 130 ngành THPT + 3 bảng 65 row = 325 facts.
    assert len(facts) >= 100
    assert {f.admission_method_raw for f in facts} == {
        "Điểm thi THPT", "Điểm Đánh giá Tư duy", "Điểm xét tuyển kết hợp", "Chứng chỉ quốc tế",
    }
    assert {f.cutoff_year for f in facts} == {2025}
    assert any("máy tính" in (f.program_name or "").lower() for f in facts)
