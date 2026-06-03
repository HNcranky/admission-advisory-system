import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from services.profile_service import extract_subject_combination, normalize_text


def parse_score(raw_message: str) -> Optional[float]:
    """Bare-answer parser cho total_score: một số trong [0, 40]."""
    match = re.search(r"\d{1,2}(?:[.,]\d+)?", raw_message or "")
    if not match:
        return None
    value = float(match.group(0).replace(",", "."))
    return value if 0 <= value <= 40 else None


def parse_admission_year(raw_message: str) -> Optional[int]:
    match = re.search(r"\b20\d{2}\b", raw_message or "")
    return int(match.group(0)) if match else None


def parse_subject_combination(raw_message: str) -> Optional[str]:
    # extract_subject_combination kỳ vọng text đã normalize (đối chiếu subjects.json).
    return extract_subject_combination(normalize_text(raw_message or ""))


@dataclass(frozen=True)
class Slot:
    name: str
    critical: bool
    order: int
    follow_up: str
    parser: Callable[[str], Any] | None = None


# Nguồn DUY NHẤT cho định nghĩa slot. critical=True nghĩa là phải có trước khi
# chạy advisory. subject_combination là critical (retrieval_agent lọc theo nó).
SLOTS: List[Slot] = [
    Slot("admission_year", True, 0, "Bạn đang xét tuyển cho năm nào?", parse_admission_year),
    Slot("total_score", True, 1, "Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?", parse_score),
    Slot("preferred_majors", True, 2, "Bạn quan tâm nhất đến ngành nào?", None),
    Slot("subject_combination", True, 3, "Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?", parse_subject_combination),
    Slot("location_preference", True, 4, "Bạn muốn học ở khu vực hoặc thành phố nào?", None),
    Slot("tuition_budget", False, 5, "Mức học phí bạn mong muốn khoảng bao nhiêu?", None),
]

_BY_NAME = {s.name: s for s in SLOTS}
_ORDERED = sorted(SLOTS, key=lambda s: s.order)


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or value == ""


def missing_critical_slots(state) -> List[str]:
    """Slot critical chưa điền, theo thứ tự. Duck-typed: dùng getattr nên chạy
    cho cả ChatProfileState lẫn StudentProfile."""
    return [s.name for s in _ORDERED if s.critical and _is_empty(getattr(state, s.name, None))]


def next_follow_up_question(state):
    missing = missing_critical_slots(state)
    if not missing:
        return None
    return _BY_NAME[missing[0]].follow_up


def parse_slot(name: str, raw_message: str):
    slot = _BY_NAME.get(name)
    return slot.parser(raw_message) if slot and slot.parser else None
