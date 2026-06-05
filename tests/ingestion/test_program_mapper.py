"""Test map_program exact_only — đường parser cutoff cần match exact để tránh
over-match substring (alias 'CS' match 'Logisti-cs-...') và variant clobbering
('KHMT - hợp tác ĐH Troy' chứa nguyên 'Khoa học máy tính')."""
from ingestion.normalization.program_mapper import map_program


def test_default_mode_exact_match_unchanged():
    pid, canonical = map_program("Khoa học máy tính", school_id="hust")
    assert pid == "computer_science"
    assert canonical == "Khoa học Máy tính"


def test_exact_only_resolves_curated_page_aliases():
    # Tên y nguyên trên trang diemthi.tuyensinh247.com (BKA) — alias curated.
    pid, _ = map_program("CNTT: Khoa học Máy tính", school_id="hust", exact_only=True)
    assert pid == "computer_science"
    pid, _ = map_program(
        "Khoa học dữ liệu và Trí tuệ nhân tạo (CT tiên tiến)", school_id="hust", exact_only=True,
    )
    assert pid == "data_science"


def test_exact_only_rejects_substring_overmatch():
    # Mode mặc định: alias 'CS' match nhầm "Logisti-cs-..." → computer_science.
    pid, _ = map_program(
        "Logistics và Quản lý chuỗi cung ứng (CT tiên tiến)", school_id="hust", exact_only=True,
    )
    assert pid != "computer_science"


def test_exact_only_rejects_variant_programs():
    # Chương trình hợp tác là ngành KHÁC (điểm chuẩn khác hẳn) — không được gộp vào ngành gốc.
    # Từ plan 6 (dictionary BKA đủ 65 mã): variant có entry riêng → resolve về id riêng.
    pid, _ = map_program(
        "Khoa học máy tính - hợp tác với ĐH Troy (Hoa Kỳ)", school_id="hust", exact_only=True,
    )
    assert pid == "computer_science_troy"


import ingestion.normalization.program_mapper as program_mapper

_FAKE_DICT = {
    "computer_science": {
        "canonical_name": "Khoa học Máy tính", "aliases": [], "codes": ["IT1"],
    },
    # bẫy: alias trùng tên ngành khác — code phải thắng trước khi so tên
    "logistics": {
        "canonical_name": "Logistics", "aliases": ["Khoa học Máy tính"], "codes": ["EM-E14"],
    },
    "no_codes_entry": {"canonical_name": "Ngành Không Mã", "aliases": []},
}


def _patch_dict(monkeypatch):
    monkeypatch.setattr(program_mapper, "_load_dict", lambda school_id="": _FAKE_DICT)


def test_code_match_wins_over_name(monkeypatch):
    _patch_dict(monkeypatch)
    pid, canonical = program_mapper.map_program(
        "Khoa học Máy tính", "EM-E14", school_id="hust",
    )
    assert pid == "logistics"          # mã thắng, dù tên khớp computer_science
    assert canonical == "Logistics"


def test_code_match_case_insensitive_and_no_name(monkeypatch):
    _patch_dict(monkeypatch)
    pid, _ = program_mapper.map_program(None, "it1", school_id="hust")
    assert pid == "computer_science"   # hit cả khi name=None


def test_code_match_respected_with_exact_only(monkeypatch):
    _patch_dict(monkeypatch)
    pid, _ = program_mapper.map_program(
        "Tên Lạ Hoắc", "IT1", school_id="hust", exact_only=True,
    )
    assert pid == "computer_science"


def test_code_miss_falls_back_to_name(monkeypatch):
    _patch_dict(monkeypatch)
    pid, _ = program_mapper.map_program(
        "Ngành Không Mã", "XX9", school_id="hust", exact_only=True,
    )
    assert pid == "no_codes_entry"


def test_no_school_id_disables_code_stage(monkeypatch):
    _patch_dict(monkeypatch)
    # school_id rỗng → mã tuyển sinh không có ngữ cảnh trường, KHÔNG tra codes
    pid, _ = program_mapper.map_program(None, "IT1", school_id="")
    assert pid == "IT1"                # fallback (program_code, program_name) như cũ
