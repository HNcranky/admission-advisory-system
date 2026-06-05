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


def _fake_map_program(name, code=None, school_id="", exact_only=False):
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


def test_validate_entries_skips_notes_entry(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    records, errors = ingest_cutoffs.validate_entries(
        [_entry(), {"_notes": ["nguồn thứ hai cho HUST chưa có"]}],
    )
    assert errors == []
    assert len(records) == 1


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


# --- Đường parser --source-url (Plan 5) ---

from ingestion.models.pipeline_models import ExtractedCutoffFact, SourceReference


def _fact(name="Khoa học máy tính", score_raw="28,25", method_raw="Điểm thi THPT"):
    return ExtractedCutoffFact(
        school_name="Đại học Bách khoa Hà Nội", cutoff_year=2025, program_name=name,
        program_code=None, admission_method_raw=method_raw,
        subject_combinations_raw=["A00", "A01"], cutoff_score_raw=score_raw,
        source_reference=SourceReference(
            source_id="tsn247_cutoff_hust_2025",
            source_url="https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html",
            school_id="hust", trust_level=3,
        ),
    )


def test_normalize_cutoff_facts_maps_and_skips(monkeypatch):
    seen_exact_only = []

    def _spy_map_program(name, code=None, school_id="", exact_only=False):
        seen_exact_only.append(exact_only)
        return _fake_map_program(name, code, school_id=school_id, exact_only=exact_only)

    monkeypatch.setattr(ingest_cutoffs, "map_program", _spy_map_program)
    facts = [
        _fact(),                                            # OK — thpt_score thang 30
        _fact(method_raw="Điểm Đánh giá Tư duy", score_raw="83.9"),  # OK — thang 100
        _fact(name="Ngành Lạ"),                             # không resolve ngành → skip
        _fact(score_raw="ba mươi"),                         # điểm rác → skip
        _fact(score_raw="35"),                              # 35 > thang 30 của thpt_score → skip
        _fact(method_raw="Phương thức bí ẩn"),              # method không map được → skip
        _fact(score_raw="27.5"),                            # trùng key với fact đầu → skip, giữ row đầu
    ]
    records, skipped = ingest_cutoffs.normalize_cutoff_facts(facts)

    assert len(records) == 2
    assert records[0].program_id == "computer_science"
    assert records[0].cutoff_score == 28.25        # "28,25" → 28.25; row trùng sau KHÔNG đè
    assert records[0].admission_method == "thpt_score"
    assert records[0].score_scale == 30.0
    assert records[0].subject_combinations == ["A00", "A01"]
    assert records[1].admission_method == "competency_test"
    assert records[1].score_scale == 100.0
    assert len(skipped) == 5
    assert any("trùng" in s for s in skipped)
    # Đường parser phải dùng exact-only — fuzzy/substring over-match trên trang aggregator.
    assert seen_exact_only and all(seen_exact_only)


def test_main_source_url_runs_fetch_parse_save(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)

    class _FakeFetch:
        raw_content = b"<html>fixture</html>"
        http_status = 200

    monkeypatch.setattr(ingest_cutoffs, "http_fetch", lambda url, **kw: _FakeFetch())
    monkeypatch.setattr(
        type(ingest_cutoffs.CUTOFF_PARSERS["tuyensinh247_cutoff_html"]), "parse",
        lambda self, content, source_url, cutoff_year=None, **kw: [_fact()],
    )
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))

    code = ingest_cutoffs._main([
        "--source-url",
        "https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html",
        "--parser", "tuyensinh247_cutoff_html",
    ])

    assert code == 0
    assert len(saved[0]) == 1
    assert saved[0][0].source_trust_level == 3


def test_cutoff_parsers_registry_has_both_tsn247_parsers():
    assert set(ingest_cutoffs.CUTOFF_PARSERS) >= {
        "tuyensinh247_cutoff_html", "tuyensinh247_cutoff_api",
    }


def test_main_source_url_api_parser_choice(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)

    class _FakeFetch:
        raw_content = b'{"success": true, "data": []}'
        http_status = 200

    monkeypatch.setattr(ingest_cutoffs, "http_fetch", lambda url, **kw: _FakeFetch())
    monkeypatch.setattr(
        type(ingest_cutoffs.CUTOFF_PARSERS["tuyensinh247_cutoff_api"]), "parse",
        lambda self, content, source_url, cutoff_year=None, **kw: [_fact()],
    )
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))

    code = ingest_cutoffs._main([
        "--source-url", "https://diemthi.tuyensinh247.com/api/common/cutoff-score?school_id=302&method_id=1&year=2024",
        "--parser", "tuyensinh247_cutoff_api",
    ])
    assert code == 0
    assert len(saved[0]) == 1


def test_main_source_url_exit_1_when_nothing_saved(monkeypatch):
    class _FakeFetch:
        raw_content = b"<html>no table</html>"
        http_status = 200

    monkeypatch.setattr(ingest_cutoffs, "http_fetch", lambda url, **kw: _FakeFetch())
    monkeypatch.setattr(
        type(ingest_cutoffs.CUTOFF_PARSERS["tuyensinh247_cutoff_html"]), "parse",
        lambda self, content, source_url, cutoff_year=None, **kw: [],
    )

    code = ingest_cutoffs._main([
        "--source-url", "https://x", "--parser", "tuyensinh247_cutoff_html",
    ])
    assert code == 1
