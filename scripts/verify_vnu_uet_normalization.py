"""
Verify that VNU-UET homepage program names from the 2026 crawl normalize.

Task 1 extracted facts only from the VNU-UET homepage. The PDF source returned
zero facts, so this check intentionally avoids source-pair assertions.
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, ".")

from ingestion.normalization.method_mapper import map_method
from ingestion.normalization.program_mapper import map_program


OBSERVED_HOMEPAGE_PROGRAMS = [
    "Công nghệ thông tin",
    "Kỹ thuật máy tính",
    "Khoa học máy tính",
    "Trí tuệ nhân tạo",
    "Hệ thống thông tin",
    "Mạng máy tính và truyền thông dữ liệu",
    "Vật lý kỹ thuật",
    "Cơ kỹ thuật",
    "Công nghệ kỹ thuật xây dựng",
    "Công nghệ kỹ thuật cơ điện tử",
    "Công nghệ hàng không vũ trụ",
    "Công nghệ kỹ thuật điện tử – viễn thông",
    "Công nghệ nông nghiệp",
    "Kỹ thuật điều khiển và tự động hóa",
    "Kỹ thuật năng lượng",
    "Kỹ thuật Robot",
    "Thiết kế công nghiệp và đồ họa",
    "Công nghệ vật liệu",
    "Khoa học dữ liệu",
    "Công nghệ sinh học",
]

EXPECTED_HOMEPAGE_PROGRAM_IDS = {
    "Công nghệ thông tin": "information_technology_uet",
    "Kỹ thuật máy tính": "computer_engineering",
    "Khoa học máy tính": "computer_science",
    "Trí tuệ nhân tạo": "artificial_intelligence_uet",
    "Hệ thống thông tin": "information_systems",
    "Mạng máy tính và truyền thông dữ liệu": "computer_networks_data_communication",
    "Vật lý kỹ thuật": "technical_physics",
    "Cơ kỹ thuật": "engineering_mechanics",
    "Công nghệ kỹ thuật xây dựng": "civil_engineering",
    "Công nghệ kỹ thuật cơ điện tử": "mechatronics",
    "Công nghệ hàng không vũ trụ": "aerospace_technology",
    "Công nghệ kỹ thuật điện tử – viễn thông": "electronics_telecom",
    "Công nghệ nông nghiệp": "agricultural_technology",
    "Kỹ thuật điều khiển và tự động hóa": "control_automation",
    "Kỹ thuật năng lượng": "energy_engineering",
    "Kỹ thuật Robot": "robotics",
    "Thiết kế công nghiệp và đồ họa": "industrial_design_graphics",
    "Công nghệ vật liệu": "materials_technology",
    "Khoa học dữ liệu": "data_science",
    "Công nghệ sinh học": "bioengineering",
}

KNOWN_METHOD_CODES = {
    "thpt_score",
    "school_record",
    "talent_admission",
    "combined",
    "competency_test",
}

OBSERVED_METHOD_SAMPLES = [
    "Xét tuyển tài năng",
]


def is_known_method_mapping(result: str | None) -> bool:
    if not result:
        return False
    method_codes = [
        method_code.strip()
        for method_code in result.split(";")
        if method_code.strip()
    ]
    return bool(method_codes) and all(
        method_code in KNOWN_METHOD_CODES for method_code in method_codes
    )


def main() -> int:
    all_ok = True

    print("=== Program mapping ===")
    for raw_name in OBSERVED_HOMEPAGE_PROGRAMS:
        program_id, canonical_name = map_program(raw_name, school_id="vnu_uet")
        expected_id = EXPECTED_HOMEPAGE_PROGRAM_IDS[raw_name]
        mapped = program_id == expected_id
        status = "OK" if mapped else "WRONG"
        if not mapped:
            all_ok = False
        print(
            f"  [{status}] {raw_name!r} -> "
            f"pid={program_id!r}, expected={expected_id!r}, "
            f"canonical={canonical_name!r}"
        )

    print("\n=== Method mapping ===")
    for raw_method in OBSERVED_METHOD_SAMPLES:
        result = map_method(raw_method, school_id="vnu_uet")
        mapped = is_known_method_mapping(result)
        status = "OK" if mapped else "UNMAPPED"
        if not mapped:
            all_ok = False
        print(f"  [{status}] {raw_method!r} -> {result!r}")

    if all_ok:
        print("\nPASS")
        return 0

    print("\nFAIL - fix the dictionaries above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
