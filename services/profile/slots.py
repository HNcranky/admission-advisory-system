import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from services.profile.admission_methods import parse_admission_method, method_display
from services.profile_service import extract_subject_combination, normalize_text


def parse_score(raw_message: str) -> Optional[float]:
    """Bare-answer parser cho total_score: một số trong [0, 150].

    Lookaround chặn token 4 chữ số ("2026" là năm, không phải điểm); trần 150
    là sanity chung — trần theo phương thức do validate_profile_delta xử lý."""
    match = re.search(r"(?<!\d)\d{1,3}(?:[.,]\d+)?(?!\d)", raw_message or "")
    if not match:
        return None
    value = float(match.group(0).replace(",", "."))
    return value if 0 <= value <= 150 else None


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
    # Vị từ "đã có giá trị" tuỳ biến (mặc định: getattr theo name khác rỗng).
    present: Callable[[Any], bool] | None = None


def _major_present(state) -> bool:
    """Slot ngành thoả mãn nếu có explicit HOẶC inferred (AC4); fallback
    preferred_majors để duck-type cho StudentProfile và row profile cũ."""
    return bool(
        getattr(state, "explicit_preferred_majors", None)
        or getattr(state, "inferred_interest_tags", None)
        or getattr(state, "preferred_majors", None)
    )


# Nguồn DUY NHẤT cho định nghĩa slot. critical=True nghĩa là phải có trước khi
# chạy advisory. subject_combination là critical (retrieval_agent lọc theo nó).
# location_preference KHÔNG bắt buộc (spec mục 8) — chỉ dùng để xếp hạng/lọc.
SLOTS: List[Slot] = [
    Slot("admission_year", True, 0, "Bạn đang xét tuyển cho năm nào?", parse_admission_year),
    Slot("total_score", True, 1, "Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?", parse_score),
    Slot("admission_method", True, 2,
         "Bạn dự định xét tuyển bằng phương thức nào nhỉ? Ví dụ: điểm thi tốt nghiệp THPT, "
         "xét học bạ, đánh giá năng lực, hoặc xét tuyển kết hợp.",
         parse_admission_method),
    Slot("preferred_majors", True, 3, "Bạn quan tâm nhất đến ngành nào?", None, present=_major_present),
    Slot("subject_combination", True, 4, "Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?", parse_subject_combination),
    Slot("location_preference", False, 5, "Bạn muốn học ở khu vực hoặc thành phố nào?", None),
    Slot("tuition_budget", False, 6, "Mức học phí bạn mong muốn khoảng bao nhiêu?", None),
]

_BY_NAME = {s.name: s for s in SLOTS}
_ORDERED = sorted(SLOTS, key=lambda s: s.order)


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or value == ""


def _slot_present(slot: Slot, state) -> bool:
    if slot.present is not None:
        return bool(slot.present(state))
    return not _is_empty(getattr(state, slot.name, None))


def missing_critical_slots(state) -> List[str]:
    """Slot critical chưa điền, theo thứ tự. Duck-typed: dùng getattr nên chạy
    cho cả ChatProfileState lẫn StudentProfile."""
    return [s.name for s in _ORDERED if s.critical and not _slot_present(s, state)]


def next_follow_up_question(state):
    missing = missing_critical_slots(state)
    if not missing:
        return None
    return _BY_NAME[missing[0]].follow_up


def parse_slot(name: str, raw_message: str):
    slot = _BY_NAME.get(name)
    return slot.parser(raw_message) if slot and slot.parser else None


def follow_up_for(slot_name: str):
    slot = _BY_NAME.get(slot_name)
    return slot.follow_up if slot else None


# Nhãn slot hiển thị cho ack/recap (3c). Nguồn nhãn dùng chung với
# explanation_service (_SLOT_LABELS) nhưng dạng ngắn cho câu xác nhận.
SLOT_LABELS = {
    "admission_year": "năm xét tuyển",
    "total_score": "mức điểm",
    "admission_method": "phương thức xét tuyển",
    "preferred_majors": "ngành quan tâm",
    "subject_combination": "tổ hợp xét tuyển",
    "location_preference": "khu vực",
    "tuition_budget": "mức học phí",
}

# Các key delta cùng trỏ về slot ngành (AC4): gộp về một nhãn duy nhất.
_MAJOR_KEYS = {"preferred_majors", "explicit_preferred_majors", "inferred_interest_tags"}


def _slot_label(key: str):
    if key in _MAJOR_KEYS:
        return SLOT_LABELS["preferred_majors"]
    return SLOT_LABELS.get(key)


def _fmt_slot_value(name: str, value) -> str:
    if name == "admission_method" and value:
        return method_display(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _state_slot_value(state, name: str) -> str:
    if name == "preferred_majors":
        value = (
            getattr(state, "preferred_majors", None)
            or getattr(state, "explicit_preferred_majors", None)
            or getattr(state, "inferred_interest_tags", None)
        )
    else:
        value = getattr(state, name, None)
    return _fmt_slot_value(name, value)


def _captured_pairs(delta):
    """[(label, formatted_value)] cho các slot critical vừa được set, dedupe theo nhãn."""
    pairs = []
    seen = set()
    for key, value in delta.items():
        label = _slot_label(key)
        if label is None or label in seen or _is_empty(value):
            continue
        seen.add(label)
        pairs.append((label, _fmt_slot_value(key, value)))
    return pairs


def build_slot_acknowledgement(delta, state):
    """Câu xác nhận giá trị vừa nhận (3c). Trả None khi không bắt được slot nào.

    <2 slot critical đã điền → echo riêng giá trị vừa nhận.
    ≥2 slot critical đã điền → recap: đã nắm gì + còn thiếu gì."""
    captured = _captured_pairs(delta or {})
    if not captured:
        return None

    filled = [s for s in _ORDERED if s.critical and _slot_present(s, state)]
    if len(filled) >= 2:
        filled_text = ", ".join(
            f"{_slot_label(s.name)} {_state_slot_value(state, s.name)}" for s in filled
        )
        recap = f"Mình đã nắm: {filled_text}."
        missing_text = ", ".join(
            _slot_label(m) for m in missing_critical_slots(state) if _slot_label(m)
        )
        if missing_text:
            recap += f" Còn thiếu: {missing_text}."
        return recap

    echo = ", ".join(f"{label} {value}" for label, value in captured)
    return f"Mình ghi nhận {echo}."
