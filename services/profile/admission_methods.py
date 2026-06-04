"""Nguồn sự thật phía profile cho phương thức xét tuyển (EC-04, EC-13).

Mã canonical khớp ingestion/normalization/dictionaries/methods.json.
Mọi hàm degrade graceful: không match/không đọc được dict → None, không raise.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional, Set

from services.profile_service import normalize_text

logger = logging.getLogger(__name__)

METHOD_CODES = {
    "thpt_score", "school_record", "competency_test", "combined", "talent_admission",
}

# Thang điểm tối đa theo phương thức; None = không validate trần (EC-04).
SCORE_SCALES = {
    "thpt_score": 30.0,
    "school_record": 30.0,
    "competency_test": 150.0,  # trần chung TSA(100)/HSA(150)
    "combined": 100.0,
    "talent_admission": None,
}

# Chỉ các phương thức thang 30 được áp score-fit bonus trong reasoning (EC-13).
THANG_30_METHODS = {"thpt_score", "school_record"}

_METHOD_DISPLAY = {
    "thpt_score": "điểm thi tốt nghiệp THPT",
    "school_record": "học bạ",
    "competency_test": "đánh giá năng lực / tư duy",
    "combined": "xét tuyển kết hợp",
    "talent_admission": "xét tuyển tài năng / tuyển thẳng",
}

# Alias hội thoại (đã normalize sẵn — normalize_text bỏ dấu, lowercase).
_EXTRA_ALIASES = {
    "thpt_score": ["diem thi", "thi thpt", "tot nghiep", "diem thi thpt"],
    "school_record": ["hoc ba"],
    "competency_test": ["dgnl", "danh gia nang luc", "dgtd", "tu duy", "tsa", "hsa"],
    "combined": ["ket hop", "xet tuyen ket hop"],
    "talent_admission": ["tuyen thang", "tai nang", "uu tien xet tuyen"],
}

_DICT_PATH = (
    Path(__file__).resolve().parents[2]
    / "ingestion" / "normalization" / "dictionaries" / "methods.json"
)


def _build_alias_index():
    """[(alias_normalized, code)] gộp _shared + mọi section trường, dài nhất trước."""
    pairs = set()
    try:
        data = json.loads(_DICT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # thiếu file/JSON hỏng → chỉ còn alias hội thoại
        logger.warning("admission_methods: không đọc được methods.json: %r", exc)
        data = {}
    for section in data.values():
        for code, info in section.items():
            if code not in METHOD_CODES:
                continue
            names = [info.get("canonical_name", "")] + list(info.get("aliases", []))
            for name in names:
                norm = normalize_text(name)
                if norm:
                    pairs.add((norm, code))
    for code, aliases in _EXTRA_ALIASES.items():
        for alias in aliases:
            pairs.add((alias, code))
    return sorted(pairs, key=lambda p: -len(p[0]))


_ALIAS_INDEX = _build_alias_index()


def _alias_hit(query_norm: str, alias: str) -> bool:
    if len(alias) <= 3:  # alias ngắn (tsa, hsa) → word boundary, tránh match trong từ
        return re.search(rf"\b{re.escape(alias)}\b", query_norm) is not None
    return alias in query_norm


def parse_admission_method(raw_message) -> Optional[str]:
    query = normalize_text(raw_message or "")
    if not query:
        return None
    for alias, code in _ALIAS_INDEX:
        if _alias_hit(query, alias):
            return code
    return None


def method_display(code) -> str:
    return _METHOD_DISPLAY.get(code, str(code))
