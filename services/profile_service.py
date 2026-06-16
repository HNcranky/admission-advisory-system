import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set

from domain.models import StudentProfile
from services.text_utils import vietnamese_fold

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DICTIONARIES_DIR = PROJECT_ROOT / "ingestion" / "normalization" / "dictionaries"

SCHOOL_ALIASES = {
    "hust": [
        "hust",
        "bach khoa ha noi",
        "dai hoc bach khoa ha noi",
        "ha noi university of science and technology",
    ],
    "uet": [
        "uet",
        "dai hoc cong nghe",
        "dh cong nghe",
        "university of engineering and technology",
    ],
    "neu": [
        "neu",
        "dai hoc kinh te quoc dan",
        "kinh te quoc dan",
        "national economics university",
    ],
    "ftu": [
        "ftu",
        "dai hoc ngoai thuong",
        "ngoai thuong",
        "foreign trade university",
    ],
}


def normalize_text(text: str) -> str:
    return vietnamese_fold(text)


@lru_cache(maxsize=1)
def load_subject_combinations() -> Set[str]:
    with open(DICTIONARIES_DIR / "subjects.json", "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {key.upper() for key in data.keys()}


@lru_cache(maxsize=1)
def load_program_aliases() -> Dict[str, Dict[str, object]]:
    with open(DICTIONARIES_DIR / "programs.json", "r", encoding="utf-8") as handle:
        data = json.load(handle)

    alias_map: Dict[str, Dict[str, object]] = {}
    for scope in data.values():
        for program_id, program in scope.items():
            canonical_name = program.get("canonical_name")
            aliases = program.get("aliases", [])
            if not canonical_name:
                continue
            normalized_aliases = [normalize_text(canonical_name)] + [
                normalize_text(alias) for alias in aliases
            ]
            alias_map[program_id] = {
                "canonical_name": canonical_name,
                "aliases": list(dict.fromkeys(normalized_aliases)),
            }
    return alias_map


def extract_score(query: str):
    patterns = [
        r"\b(\d{1,2}(?:[.,]\d+)?)\s*diem\b",
        r"\bdiem\s*(\d{1,2}(?:[.,]\d+)?)\b",
        r"\bduoc\s*(\d{1,2}(?:[.,]\d+)?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, query)
        if not match:
            continue
        value = float(match.group(1).replace(",", "."))
        if 0 <= value <= 40:
            return value
    return None


def extract_subject_combination(query: str):
    combinations = load_subject_combinations()
    matches = re.findall(r"\b[a-z]{1,2}\d{2}\b", query, flags=re.IGNORECASE)
    for candidate in matches:
        normalized = candidate.upper()
        if normalized in combinations:
            return normalized
    return None


def _contains_alias(query: str, alias: str) -> bool:
    # Lookaround thay vì substring thuần: "hoa hoc" KHÔNG được match bên trong
    # "k|hoa hoc may tinh". \b không dùng được vì alias có thể kết thúc bằng
    # ký tự non-word như ")" — vd "... dh troy (hoa ky)".
    if not alias:
        return False
    return bool(
        re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", query)
    )


def extract_preferred_majors(query: str) -> List[str]:
    alias_map = load_program_aliases()
    # Longest-match: ghi nhận alias dài nhất khớp cho từng program, rồi loại
    # program mà alias khớp của nó nằm TRONG alias khớp của program khác —
    # "khoa hoc may tinh" phải nhường "khoa hoc may tinh hop tac dh troy".
    matched: Dict[str, str] = {}
    for program_id, payload in alias_map.items():
        hits = [a for a in payload["aliases"] if _contains_alias(query, a)]
        if hits:
            matched[program_id] = max(hits, key=len)
    return [
        program_id
        for program_id, alias in matched.items()
        if not any(
            other_id != program_id and len(other) > len(alias) and alias in other
            for other_id, other in matched.items()
        )
    ]


def extract_preferred_schools(query: str) -> List[str]:
    schools: List[str] = []
    for school_id, aliases in SCHOOL_ALIASES.items():
        if any(alias in query for alias in aliases):
            schools.append(school_id)
    return schools


def build_profile(user_query: str) -> StudentProfile:
    normalized_query = normalize_text(user_query)

    score = extract_score(normalized_query)
    subject_combination = extract_subject_combination(normalized_query)
    preferred_majors = extract_preferred_majors(normalized_query)
    preferred_schools = extract_preferred_schools(normalized_query)
    if "hust" in preferred_schools and "information_technology_uet" in preferred_majors:
        preferred_majors = [
            major for major in preferred_majors if major != "information_technology_uet"
        ]
        if "computer_science" not in preferred_majors:
            preferred_majors.insert(0, "computer_science")

    profile = StudentProfile(
        total_score=score,
        subject_combination=subject_combination,
        preferred_majors=preferred_majors,
        preferred_schools=preferred_schools,
    )
    from services.profile.slots import missing_critical_slots
    profile.missing_slots = missing_critical_slots(profile)
    return profile
