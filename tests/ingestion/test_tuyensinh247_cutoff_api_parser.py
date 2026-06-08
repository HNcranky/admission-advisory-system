import json
from pathlib import Path

from ingestion.parsers.tuyensinh247_cutoff_api_parser import Tuyensinh247CutoffApiParser

_URL = ("https://diemthi.tuyensinh247.com/api/common/cutoff-score"
        "?school_id=302&method_id=1&year=2024")

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _payload(rows, success=True):
    return json.dumps({"success": success, "data": rows}, ensure_ascii=False).encode("utf-8")


_ROWS = [
    {"code": "IT1", "name": "CNTT: Khoa học Máy tính", "block": "A00;A01",
     "mark": 28.53, "year": 2024, "admission_name": "Điểm thi THPT"},
    # quirk 2022: hậu tố y (THPT) + newline nhúng trong tên + block rỗng
    {"code": "EE-E18y", "name": "Hệ thống điện và năng lượng tái tạo\n(CT tiên tiến)",
     "block": "", "mark": 55, "year": 2022, "admission_name": "Điểm xét tuyển kết hợp"},
    # quirk 2022: hậu tố x (ĐGTD)
    {"code": "BF1x", "name": "Kỹ thuật Sinh học", "block": "K00;K01",
     "mark": 14.5, "year": 2022, "admission_name": "Điểm thi ĐGTD"},
    {"code": "XX1", "name": "Thiếu điểm", "block": "A00",
     "mark": None, "year": 2024, "admission_name": "Điểm thi THPT"},      # bỏ qua
    {"code": "XX2", "name": "", "block": "A00",
     "mark": 25.0, "year": 2024, "admission_name": "Điểm thi THPT"},      # bỏ qua
]


def test_parses_rows_with_code_block_and_year_from_row():
    facts = Tuyensinh247CutoffApiParser().parse(_payload(_ROWS), _URL)
    assert len(facts) == 3                       # 3 row hợp lệ, 2 row thiếu bị bỏ
    f = facts[0]
    assert f.program_code == "IT1"
    assert f.program_name == "CNTT: Khoa học Máy tính"
    assert f.subject_combinations_raw == ["A00", "A01"]
    assert f.cutoff_score_raw == "28.53"
    assert f.cutoff_year == 2024                 # đọc từ row, không tin URL
    assert f.admission_method_raw == "Điểm thi THPT"
    assert f.source_reference.trust_level == 3
    assert f.extraction_method == "tuyensinh247_cutoff_api"
    g = facts[1]
    assert g.program_code == "EE-E18"            # strip hậu tố y
    assert g.program_name == "Hệ thống điện và năng lượng tái tạo (CT tiên tiến)"  # \s+ → " "
    assert g.subject_combinations_raw is None    # block rỗng
    assert g.cutoff_score_raw == "55"
    assert g.cutoff_year == 2022
    h = facts[2]
    assert h.program_code == "BF1"               # strip hậu tố x
    assert h.subject_combinations_raw == ["K00", "K01"]


def test_year_filter():
    facts = Tuyensinh247CutoffApiParser().parse(_payload(_ROWS), _URL, cutoff_year=2022)
    assert [f.cutoff_year for f in facts] == [2022, 2022]


def test_success_false_or_bad_json_returns_empty():
    parser = Tuyensinh247CutoffApiParser()
    assert parser.parse(_payload([], success=False), _URL) == []
    assert parser.parse(b"<html>not json</html>", _URL) == []
    assert parser.parse(json.dumps({"success": True, "data": "oops"}).encode(), _URL) == []


def test_real_fixture_thpt_2024():
    content = (_FIXTURES / "tsn247_bka_api_thpt_2024.json").read_bytes()
    facts = Tuyensinh247CutoffApiParser().parse(content, _URL)
    assert len(facts) >= 60
    assert {f.cutoff_year for f in facts} == {2024}
    it1 = [f for f in facts if f.program_code == "IT1"]
    assert it1 and it1[0].cutoff_score_raw == "28.53"


def test_real_fixture_dgtd_2022_strips_method_suffix():
    content = (_FIXTURES / "tsn247_bka_api_dgtd_2022.json").read_bytes()
    facts = Tuyensinh247CutoffApiParser().parse(content, _URL)
    assert len(facts) >= 50
    assert {f.cutoff_year for f in facts} == {2022}
    # quirk 2022: mã mang hậu tố method (x=ĐGTD, y=THPT) — phải bị strip
    assert all(not (f.program_code or "").lower().endswith(("x", "y"))
               or len(f.program_code) <= 1 for f in facts)
