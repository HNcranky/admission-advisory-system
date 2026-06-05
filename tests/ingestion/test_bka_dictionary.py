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
