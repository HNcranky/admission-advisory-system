# Cutoff Plan 6 — Dictionary BKA đủ 65 mã + map_program theo mã

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `programs.json` phủ đủ 65 mã tuyển sinh BKA (mỗi mã một `program_id` riêng) và `map_program` resolve theo MÃ trước khi so tên.

**Architecture:** Stage 0 mới trong `map_program` tra field `"codes"` của school scope (case-insensitive, return ngay khi hit) — đứng TRƯỚC cả guard `not program_name` và exact-name stage; `exact_only` không chặn stage này. Dữ liệu curated (73 entries section `hust`: 29 cũ + 17 override từ `_shared` + 27 mới) đã generate sẵn và freeze tại `docs/superpowers/plans/data/2026-06-05-hust-programs-section.json` — plan này chỉ APPLY, không generate lại. Spec: `docs/superpowers/specs/2026-06-05-cutoff-tsn247-api-dictionary-design.md`.

**Tech Stack:** Python, pytest, JSON dictionary.

**Phụ thuộc:** Plan 5 (exact_only). Plan 7/8 phụ thuộc plan này.

**Bake sẵn từ khảo sát 2026-06-05:**
- API tsn247 4 năm có **126 mã** (sau strip hậu tố "y" của 2022) — mã bị đánh số lại giữa các năm
  (CH3 2022 = "Kỹ thuật in", 2025 là MS5; EM1 đổi tên "Kinh tế công nghiệp"→"Quản lý năng lượng").
  Codes map = **65 mã hiện hành (2025)**; mã cũ không có trong map sẽ fallback exact-name —
  một số resolve theo tên, còn lại SKIP là chấp nhận được.
- `_shared.electronics_telecom` đang chứa 3 alias variant đặt NHẦM chỗ (2 Leibniz + 1 "Chương
  trình tiên tiến") — chính là nguyên nhân ET-LUH/ET-E4 bị gộp vào ngành gốc. Plan gỡ cả ở
  `_shared` (entry riêng `electronics_telecom_leibniz`/`_advanced` nhận thay).
- `load_program_aliases()` (services/profile_service.py:58) flatten MỌI scope theo program_id,
  scope sau đè scope trước → override hust phải là SUPERSET alias của `_shared` cùng id.
  Alias entry variant chỉ là tên đầy đủ → không phá `extract_preferred_majors`.

---

### Task 1: `map_program` stage 0 — match theo mã

**Files:**
- Modify: `ingestion/normalization/program_mapper.py` (hàm `map_program`)
- Test: `tests/ingestion/test_program_mapper.py` (append)

- [ ] **Step 1: Viết test fail** — append vào `tests/ingestion/test_program_mapper.py`:

```python
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
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_program_mapper.py -q`
Expected: 5 test mới FAIL (stage code chưa tồn tại — `map_program` trả theo tên/fallback).

- [ ] **Step 3: Implement** — sửa `ingestion/normalization/program_mapper.py::map_program`.
Thay đoạn đầu hàm (từ `if not program_name:` đến `name_lower = ...`) thành:

```python
    programs = _load_dict(school_id)

    # Stage 0: match theo MÃ tuyển sinh (codes — per-school). Ưu tiên tuyệt đối:
    # mã là định danh chính thức, tên có thể trùng/lệch giữa các năm.
    # Cần school_id vì mã chỉ có nghĩa trong ngữ cảnh một trường.
    if program_code and school_id:
        code_norm = str(program_code).strip().upper()
        for prog_id, info in programs.items():
            if any(code_norm == str(c).strip().upper() for c in info.get("codes", [])):
                return (prog_id, info["canonical_name"])

    if not program_name:
        return (program_code, program_name)

    name_lower = program_name.lower().strip()
```

(`_load_dict` được gọi sớm hơn trước — có cache module nên không tốn thêm IO.)

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/ingestion/test_program_mapper.py tests/ingestion/test_cutoff_seed_loader.py -q`
Expected: PASS toàn bộ (test cũ không đổi hành vi — caller không truyền code giữ nguyên).

- [ ] **Step 5: Commit**

```bash
git add ingestion/normalization/program_mapper.py tests/ingestion/test_program_mapper.py
git commit -m "feat: program code matching stage in map_program (codes field, per-school)"
```

---

### Task 2: Apply dictionary BKA 65 mã + dọn alias variant ở `_shared`

**Files:**
- Modify: `ingestion/normalization/dictionaries/programs.json` (thay section `hust`, sửa `_shared.electronics_telecom`)
- Data: `docs/superpowers/plans/data/2026-06-05-hust-programs-section.json` (đã commit sẵn — KHÔNG sửa)
- Test: `tests/ingestion/test_bka_dictionary.py` (mới)

- [ ] **Step 1: Viết test fail** — create `tests/ingestion/test_bka_dictionary.py`:

```python
"""Integrity dictionary BKA: 65 mã hiện hành resolve theo code, không trùng chéo.

Bảng mã→id khớp spec 2026-06-05-cutoff-tsn247-api-dictionary-design.md.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from ingestion.normalization.program_mapper import map_program
from services.profile_service import extract_preferred_majors, normalize_text

_DICT = Path("ingestion/normalization/dictionaries/programs.json")

# 65 mã 2025 → program_id (30 sẵn có + 8 reuse + 27 mới)
EXPECTED_CODES = {
    "BF1": "bioengineering", "BF2": "food_technology", "ED2": "education_technology",
    "ED3": "education_management", "EE1": "electrical_engineering", "EM1": "energy_management",
    "EM2": "industrial_management", "EM3": "business_administration", "EM4": "accounting",
    "EM5": "finance_banking", "ET1": "electronics_telecom", "ET2": "biomedical_engineering",
    "EV1": "environmental_engineering", "FL1": "english_science_tech",
    "FL2": "english_professional", "HE1": "heat_engineering", "IT-E10": "data_science",
    "IT-E15": "cyber_security", "IT1": "computer_science", "ME1": "mechatronics",
    "ME2": "mechanical_engineering", "MI1": "math_informatics", "MS1": "materials_science",
    "MS2": "microelectronics_nano", "MS5": "printing_technology", "PH1": "physics",
    "PH2": "nuclear_engineering", "PH3": "medical_physics", "TE1": "automotive_engineering",
    "TE3": "aerospace_engineering",
    "CH1": "chemical_engineering", "EE2": "control_automation",
    "CH-E11": "pharmaceutical_chemistry", "EE-E18": "power_renewable_energy",
    "EM-E14": "logistics", "ET-E9": "embedded_systems", "FL3": "chinese_science_tech",
    "TX1": "textile_technology",
    "BF-E12": "food_technology_advanced", "BF-E19": "bioengineering_advanced",
    "CH2": "chemistry", "EE-E8": "control_automation_advanced",
    "EE-EP": "industrial_informatics_pfiev", "EM-E13": "business_analytics",
    "ET-E16": "digital_media_engineering", "ET-E4": "electronics_telecom_advanced",
    "ET-E5": "biomedical_engineering_advanced", "ET-LUH": "electronics_telecom_leibniz",
    "EV2": "resource_environment_management", "IT-E6": "information_technology_viet_nhat",
    "IT-E7": "information_technology_global_ict", "IT-EP": "information_technology_viet_phap",
    "IT2": "computer_engineering", "ME-E1": "mechatronics_advanced",
    "ME-GU": "mechanical_engineering_griffith", "ME-LUH": "mechatronics_leibniz",
    "ME-NUT": "mechatronics_nagaoka", "MI2": "management_information_systems",
    "MS-E3": "materials_science_advanced", "MS3": "polymer_composite_materials",
    "TE-E2": "automotive_engineering_advanced", "TE-EP": "aerospace_mechanics_pfiev",
    "TE2": "vehicle_engineering", "TROY-BA": "business_administration_troy",
    "TROY-IT": "computer_science_troy",
}


def _hust_section():
    return json.loads(_DICT.read_text(encoding="utf-8"))["hust"]


@pytest.mark.parametrize("code,expected_id", sorted(EXPECTED_CODES.items()))
def test_all_65_codes_resolve(code, expected_id):
    pid, canonical = map_program(None, code, school_id="hust")
    assert pid == expected_id
    assert canonical


def test_no_duplicate_codes_in_hust_scope():
    codes = [c for e in _hust_section().values() for c in e.get("codes", [])]
    dup = [c for c, n in Counter(codes).items() if n > 1]
    assert dup == []
    assert len(codes) == 65


def test_no_cross_entry_name_collision_in_hust_scope():
    name2ids = defaultdict(set)
    for pid, e in _hust_section().items():
        for n in [e["canonical_name"]] + e.get("aliases", []):
            name2ids[n.lower().strip()].add(pid)
    cross = {n: ids for n, ids in name2ids.items() if len(ids) > 1}
    assert cross == {}


def test_shared_electronics_telecom_has_no_variant_aliases():
    data = json.loads(_DICT.read_text(encoding="utf-8"))
    aliases = data["_shared"]["electronics_telecom"]["aliases"]
    assert not any("leibniz" in a.lower() or "tiên tiến" in a.lower() for a in aliases)


def test_variant_entries_do_not_pollute_profile_extraction():
    # Câu chat phổ biến KHÔNG được bắt nhầm sang variant
    majors = extract_preferred_majors(
        normalize_text("Em muốn học công nghệ thông tin ở Bách khoa")
    )
    assert "information_technology_viet_nhat" not in majors
    assert "information_technology_global_ict" not in majors
    assert "computer_science_troy" not in majors
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_bka_dictionary.py -q`
Expected: FAIL hàng loạt (mã mới chưa có trong dictionary). LƯU Ý: nếu fail vì
`map_program` chưa có stage code → quay lại Task 1.

- [ ] **Step 3: Apply data** — thay section `hust` bằng artifact đã freeze + gỡ 3 alias variant
khỏi `_shared.electronics_telecom`:

```bash
python - <<'EOF'
import json
from pathlib import Path

dict_path = Path("ingestion/normalization/dictionaries/programs.json")
data = json.loads(dict_path.read_text(encoding="utf-8"))

new_hust = json.loads(
    Path("docs/superpowers/plans/data/2026-06-05-hust-programs-section.json")
    .read_text(encoding="utf-8")
)
assert len(new_hust) == 73, len(new_hust)
data["hust"] = new_hust

et = data["_shared"]["electronics_telecom"]
et["aliases"] = [
    a for a in et["aliases"]
    if "leibniz" not in a.lower() and "tiên tiến" not in a.lower()
]

dict_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("OK: hust =", len(data["hust"]), "entries")
EOF
```

(Script này reformat toàn file theo `indent=2` — kiểm tra `git diff --stat` để chắc các scope
khác chỉ đổi format, không đổi nội dung.)

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/ingestion/test_bka_dictionary.py tests/ingestion/ -q`
Expected: PASS toàn bộ — gồm cả test cũ của seed loader/parser (dictionary mở rộng không phá
exact-match cũ; nếu `test_parses_real_fixture_snapshot` hay seed test fail → alias bị đổi sai,
xem lại Step 3).

- [ ] **Step 5: Sanity scale toàn cục** — chạy nhanh xem coverage parser HTML 2025 tăng:

Run: `python -m ingestion.ingest_cutoffs --source-url https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html --dry-run 2>/dev/null | tail -3`
Expected: số record vọt từ ~120 lên ~250+ (65 ngành × 4 bảng, trừ row trùng tổ hợp);
SKIP list ngắn hẳn (chỉ còn row rác). KHÔNG ghi DB ở bước này (--dry-run).

- [ ] **Step 6: Commit**

```bash
git add ingestion/normalization/dictionaries/programs.json tests/ingestion/test_bka_dictionary.py
git commit -m "feat: full BKA dictionary coverage (65 admission codes, variant programs split)"
```

---

### Task 3: Khép plan — toàn suite

- [ ] **Step 1:** `python -m pytest -q` → toàn xanh (không cần DB).
- [ ] **Step 2:** Tick checkbox plan này + cập nhật bảng index `2026-06-05-cutoff-0-index.md` (dòng plan 6 → xong) + commit docs.
