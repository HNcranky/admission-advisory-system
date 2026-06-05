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
    pid, _ = map_program(
        "Khoa học máy tính - hợp tác với ĐH Troy (Hoa Kỳ)", school_id="hust", exact_only=True,
    )
    assert pid is None
