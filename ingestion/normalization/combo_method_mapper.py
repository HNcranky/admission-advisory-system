import re
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

_RULES_CACHE: Optional[Dict[str, Any]] = None


def _load_rules() -> Dict[str, Any]:
    """Load combo → method mapping rules."""
    global _RULES_CACHE
    if _RULES_CACHE is None:
        rules_path = (
            Path(__file__).parent / "dictionaries" / "combo_method_rules.json"
        )
        with open(rules_path, "r", encoding="utf-8") as f:
            _RULES_CACHE = json.load(f)
    return _RULES_CACHE


def _get_rules_for_school(school_id: str) -> List[dict]:
    """
    Get the ordered rules for a specific school.
    School-specific rules take precedence, then shared rules.
    """
    all_rules = _load_rules()

                                 
    school_rules = (
        all_rules.get(school_id, {}).get("rules", [])
        if school_id
        else []
    )

                                                                         
    shared_rules = all_rules.get("_shared", {}).get("rules", [])

                                                                    
    school_patterns = {r["combo_pattern"] for r in school_rules}
    merged = list(school_rules)
    for rule in shared_rules:
        if rule["combo_pattern"] not in school_patterns:
            merged.append(rule)

    return merged


def infer_methods_from_combos(
    combos: Optional[List[str]],
    school_id: str = "",
) -> List[str]:
    """
    Infer admission method codes from subject combination codes.

    Args:
        combos: List of subject combination codes (e.g. ["A00", "K00"])
        school_id: School identifier for school-specific rules

    Returns:
        List of unique method_code strings (e.g. ["competency_test", "thpt_score"])
    """
    if not combos:
        return []

    rules = _get_rules_for_school(school_id)
    found_methods = []
    seen = set()

    for combo in combos:
        for rule in rules:
            pattern = rule["combo_pattern"]
            method_code = rule["method_code"]

            if re.match(pattern, combo) and method_code not in seen:
                found_methods.append(method_code)
                seen.add(method_code)
                break                                           

    return found_methods


def get_method_display_name(
    method_code: str,
    school_id: str = "",
) -> str:
    """
    Get the human-readable display name for a method code,
    looking up from methods.json with school-aware resolution.

    Args:
        method_code: Method code (e.g. "competency_test")
        school_id: School identifier

    Returns:
        Display name (e.g. "Đánh giá tư duy (TSA)" for HUST)
    """
    from ingestion.normalization.method_mapper import _load_dict

    methods = _load_dict(school_id)

    if method_code in methods:
        return methods[method_code]["canonical_name"]

    return method_code
