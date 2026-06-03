import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_METHODS_CACHE: Optional[Dict[str, Any]] = None


def _load_all() -> Dict[str, Any]:
    """Load the full methods dictionary."""
    global _METHODS_CACHE
    if _METHODS_CACHE is None:
        dict_path = (
            Path(__file__).parent / "dictionaries" / "methods.json"
        )
        with open(dict_path, "r", encoding="utf-8") as f:
            _METHODS_CACHE = json.load(f)
    return _METHODS_CACHE


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


def map_method(
    raw_method: Optional[str],
    school_id: str = "",
) -> Optional[str]:
    """
    Map raw admission method text to canonical code.

    Args:
        raw_method: Raw admission method string
        school_id: School identifier for school-specific lookup

    Returns:
        Canonical method code or the raw text if no match
    """
    if not raw_method:
        return None

    methods = _load_dict(school_id)
    raw_lower = raw_method.lower().strip()

                                                        
                                                                    
    found_methods = []
    for method_code, info in methods.items():
        candidates = [info["canonical_name"]] + info.get("aliases", [])
        matched = False
        for candidate in candidates:
            candidate_lower = candidate.lower().strip()
            if not candidate_lower:
                continue
            if raw_lower == candidate_lower or candidate_lower in raw_lower:
                matched = True
                break
        if matched and method_code not in found_methods:
            found_methods.append(method_code)

    if found_methods:
        return "; ".join(found_methods)

    logger.debug(f"No canonical match for method: '{raw_method}'")
    return raw_method
