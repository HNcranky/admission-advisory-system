import re
import json
import logging
from pathlib import Path
from typing import List, Optional

from ingestion.models.pipeline_models import SubjectCombination

logger = logging.getLogger(__name__)

_SUBJECTS_DICT = None


def _load_dict() -> dict:
    global _SUBJECTS_DICT
    if _SUBJECTS_DICT is None:
        dict_path = (
            Path(__file__).parent / "dictionaries" / "subjects.json"
        )
        with open(dict_path, "r", encoding="utf-8") as f:
            _SUBJECTS_DICT = json.load(f)
    return _SUBJECTS_DICT


def map_combinations(
    raw_combos: Optional[List[str]],
) -> List[SubjectCombination]:
    """
    Map raw subject combination codes to structured objects.

    Args:
        raw_combos: List of raw combo strings
                    (e.g. ["A00", "B00", "Toán, Lý, Hóa (A01)"])

    Returns:
        List of SubjectCombination objects
    """
    if not raw_combos:
        return []

    subjects_dict = _load_dict()
    result = []
    seen = set()

    for raw in raw_combos:
                                    
        codes = re.findall(r"\b([A-Z]{1,2}\d{2})\b", raw)

        if codes:
            for code in codes:
                if code in seen:
                    continue
                seen.add(code)

                if code in subjects_dict:
                    info = subjects_dict[code]
                    result.append(SubjectCombination(
                        code=code,
                        subjects=info["subjects"],
                        description=info.get("description"),
                    ))
                else:
                    result.append(SubjectCombination(
                        code=code,
                        description=f"Unknown combination {code}",
                    ))
        else:
                                                    
            combo = _match_from_text(raw, subjects_dict)
            if combo and combo.code not in seen:
                seen.add(combo.code)
                result.append(combo)

    return result


def _match_from_text(
    text: str, subjects_dict: dict
) -> Optional[SubjectCombination]:
    """Try to match raw subject text to a known combination."""
    text_lower = text.lower().strip()

    for code, info in subjects_dict.items():
        desc = info.get("description", "").lower()
        if desc and desc in text_lower:
            return SubjectCombination(
                code=code,
                subjects=info["subjects"],
                description=info.get("description"),
            )

    return None
