import json

import ingestion.ingest_cutoffs as ingest_cutoffs


def _entry(**overrides):
    base = dict(
        school_id="hust", program_name_raw="Khoa học máy tính", program_code_raw="IT1",
        cutoff_year=2025, admission_method="thpt_score", score_scale=30,
        cutoff_score=28.25, subject_combinations=["A00", "A01"],
        note=None, source_url="https://ts.hust.edu.vn/diem-chuan-2025",
        source_trust_level=5,
    )
    base.update(overrides)
    return base


def _fake_map_program(name, code=None, school_id=""):
    if name and "máy tính" in name.lower():
        return ("computer_science", "Khoa học Máy tính")
    return (None, name)


def test_validate_entries_happy_path(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    records, errors = ingest_cutoffs.validate_entries([_entry()])
    assert errors == []
    assert len(records) == 1
    assert records[0].program_id == "computer_science"
    assert records[0].admission_method == "thpt_score"
    assert records[0].cutoff_score == 28.25


def test_validate_entries_is_atomic_and_reports_all_errors(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    bad = [
        _entry(cutoff_score=35.0),                      # vượt thang 30
        _entry(admission_method="khong_ton_tai"),       # method lạ
        _entry(program_name_raw="Ngành Không Tồn Tại"), # không resolve được
        _entry(source_url="  "),                        # thiếu nguồn
        _entry(cutoff_year=1999),                       # năm ngoài range
    ]
    records, errors = ingest_cutoffs.validate_entries(bad)
    assert records == []      # entry hợp lệ duy nhất cũng không có ở đây — list toàn lỗi
    assert len(errors) == 5   # MỌI lỗi đều được liệt kê, không dừng ở lỗi đầu


def test_school_filter(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    records, errors = ingest_cutoffs.validate_entries(
        [_entry(), _entry(school_id="vnu_uet")], school_filter="hust",
    )
    assert errors == []
    assert len(records) == 1 and records[0].school_id == "hust"


def test_main_exits_nonzero_and_writes_nothing_on_any_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([_entry(), _entry(cutoff_score=99)]), encoding="utf-8")

    code = ingest_cutoffs._main(["--seed", str(seed)])

    assert code == 1
    assert saved == []                      # atomic: 1 entry lỗi → KHÔNG ghi gì
    assert "99" in capsys.readouterr().out  # lỗi được in ra


def test_main_dry_run_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([_entry()]), encoding="utf-8")

    assert ingest_cutoffs._main(["--seed", str(seed), "--dry-run"]) == 0
    assert saved == []


def test_main_writes_and_verifies_count(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: len(rs))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([_entry()]), encoding="utf-8")

    assert ingest_cutoffs._main(["--seed", str(seed)]) == 0


def test_main_exit_2_when_db_write_short(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: 0)  # DB lỗi → 0
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([_entry()]), encoding="utf-8")

    assert ingest_cutoffs._main(["--seed", str(seed)]) == 2
