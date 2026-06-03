import json
import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

_PROGRAMS_CACHE: Optional[Dict[str, Any]] = None


def _load_all() -> Dict[str, Any]:
    """Load the full programs dictionary (all schools + shared)."""
    global _PROGRAMS_CACHE
    if _PROGRAMS_CACHE is None:
        dict_path = (
            Path(__file__).parent / "dictionaries" / "programs.json"
        )
        with open(dict_path, "r", encoding="utf-8") as f:
            _PROGRAMS_CACHE = json.load(f)
    return _PROGRAMS_CACHE


def _load_dict(school_id: str = "") -> dict:
    """
    Build a merged dictionary for a specific school.
    School-specific entries override shared entries with the same key.
    """
    all_data = _load_all()
    shared = all_data.get("_shared", {})
    school = all_data.get(school_id, {}) if school_id else {}

                                                  
    merged = {}
    merged.update(shared)
    merged.update(school)
    return merged


def map_program(
    program_name: Optional[str],
    program_code: Optional[str] = None,
    school_id: str = "",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Map raw program name/code to canonical (program_id, canonical_name).

    Args:
        program_name: Raw program name
        program_code: Raw program code (e.g. "IT1")
        school_id: School identifier for school-specific lookup

    Returns:
        (program_id, canonical_name) tuple.
        program_id is None if no match found.
    """
    if not program_name:
        return (program_code, program_name)

    programs = _load_dict(school_id)
    name_lower = program_name.lower().strip()

                                                                  
    for prog_id, info in programs.items():
        canonical = info["canonical_name"]
        aliases = info.get("aliases", [])

        if name_lower == canonical.lower():
            return (prog_id, canonical)

        for alias in aliases:
            if name_lower == alias.lower():
                return (prog_id, canonical)

                                                                  
    for prog_id, info in programs.items():
        canonical = info["canonical_name"]
        aliases = info.get("aliases", [])

        all_names = [canonical] + aliases
        for name in all_names:
            if (
                name.lower() in name_lower
                or name_lower in name.lower()
            ):
                return (prog_id, canonical)

                                                                  
    try:
        from thefuzz import fuzz

        best_score = 0
        best_id = None
        best_name = None

        for prog_id, info in programs.items():
            canonical = info["canonical_name"]
            aliases = info.get("aliases", [])

            for name in [canonical] + aliases:
                score = fuzz.ratio(name_lower, name.lower())
                if score > best_score and score >= 85:
                    best_score = score
                    best_id = prog_id
                    best_name = info["canonical_name"]

        if best_id:
            logger.debug(
                f"Fuzzy matched '{program_name}' → "
                f"'{best_name}' (score={best_score})"
            )
            return (best_id, best_name)

    except ImportError:
        logger.debug("thefuzz not available, skipping fuzzy match")

                                                                  
    logger.debug(f"No canonical match for program: '{program_name}'")
    return (program_code, program_name)
