import logging
from typing import Optional

from services.chat.models import ChatProfileState, union_majors
from services.inference.models import InferenceError, InferenceRequest
from services.profile.admission_methods import METHOD_CODES, parse_admission_method
from services.profile.major_resolver import is_explicit_choice, resolve_majors
from services.profile.slots import SLOTS, missing_critical_slots, parse_slot

logger = logging.getLogger(__name__)

# Slot vô hướng LLM được phép trả (preferred_majors do resolver; preferred_schools/
# constraints trích cơ hội nhưng vẫn nằm trong allow-list bên dưới nếu LLM trả).
_LLM_SLOT_KEYS = {
    "admission_year", "total_score", "subject_combination", "admission_method",
    "location_preference", "tuition_budget", "preferred_schools", "constraints",
}

STATE_UPDATE_PROMPT = """
Bạn cập nhật hồ sơ tư vấn tuyển sinh của một học sinh Việt Nam qua hội thoại.
Bạn được cho HỒ SƠ ĐÃ BIẾT và TIN NHẮN MỚI. CHỈ trả về các trường THAY ĐỔI
hoặc MỚI xuất hiện trong tin nhắn mới (delta), KHÔNG lặp lại trường không đổi.

Trả JSON, chỉ gồm các khóa có giá trị mới (dùng đúng tên khóa):
- total_score: số (0..150 tuỳ phương thức; thang phổ biến là 30)
- admission_method: một trong "thpt_score" (điểm thi TN THPT) | "school_record" (học bạ)
  | "competency_test" (ĐGNL/ĐGTD) | "combined" (kết hợp) | "talent_admission" (tài năng/tuyển thẳng)
- subject_combination: mã tổ hợp "A00"/"A01"/"D01"...
- admission_year: năm (số)
- location_preference: tỉnh/khu vực
- tuition_budget: chuỗi ngân sách
- preferred_schools: list tên trường
- constraints: list ràng buộc
KHÔNG trả preferred_majors (hệ thống tự suy). Nếu tin nhắn không thêm gì, trả {}.
""".strip()


def _is_bare_answer(message: str) -> bool:
    """Câu trả lời cụt: ngắn (<= 4 token) — đủ để coi là chỉ trả lời slot đang hỏi."""
    return len((message or "").split()) <= 4


def _render_state_update(known_state, message: str) -> str:
    known = []
    for s in sorted(SLOTS, key=lambda s: s.order):
        val = getattr(known_state, s.name, None)
        known.append(f"- {s.name}: {val if val not in (None, [], '') else 'chưa có'}")
    missing = ", ".join(missing_critical_slots(known_state)) or "(đủ)"
    return (
        "HỒ SƠ ĐÃ BIẾT:\n" + "\n".join(known) +
        f"\nSlot còn thiếu: {missing}\n\nTIN NHẮN MỚI: \"{message}\""
    )


def _coerce_llm_delta(parsed) -> dict:
    data = dict(parsed or {})
    out = {}
    for key, value in data.items():
        if key not in _LLM_SLOT_KEYS:
            continue
        if value is None or value == [] or value == "":
            continue
        if key == "admission_method" and value not in METHOD_CODES:
            value = parse_admission_method(str(value))
            if value is None:
                continue
        out[key] = value
    return out


def extract_profile_update(message: str, *, known_state, active_slot: Optional[str] = None,
                           gateway=None, resolver=resolve_majors) -> dict:
    """Trả DELTA: chỉ slot thay đổi lượt này (DST update).

    Ngành tách theo AC4: sở thích suy luận -> inferred_interest_tags, ngành đã chọn
    rõ -> explicit_preferred_majors, phát op tích luỹ {"__add__": [...]} để
    apply_profile_delta UNION thay vì ghi đè (chống churn). Tier-2/3 (embedding/LLM)
    bị chặn khi message chỉ đang trả lời một slot non-major (cheap_only) để tránh nhiễu.

    NOTE: phủ định kiểu "không thích AI nữa" chưa xử lý — tags chỉ tích luỹ."""
    message = message or ""
    delta: dict = {}

    # Tier-0: parse câu trả lời cụt cho slot đang chờ (deterministic).
    if active_slot:
        val = parse_slot(active_slot, message)
        if val is not None:
            delta[active_slot] = val

    # Cổng chặn inference: nếu message vừa điền 1 slot non-major thì chỉ chạy Tier-1
    # rẻ — không để embedding suy ra ngành tiếp tuyến làm nhiễu inferred tags.
    cheap_only = bool(active_slot and active_slot != "preferred_majors" and active_slot in delta)

    # Ngành: resolver tiered trả list phẳng; phân loại explicit/inferred theo ngữ cảnh.
    try:
        majors = resolver(message, known_state=known_state, gateway=gateway, cheap_only=cheap_only)
    except Exception as exc:
        logger.warning("resolve_majors failed in extractor: %r", exc)
        majors = []
    if majors:
        majors = list(majors)
        if is_explicit_choice(message, active_slot):
            delta["explicit_preferred_majors"] = {"__add__": majors}
        else:
            delta["inferred_interest_tags"] = {"__add__": majors}

    has_major_delta = "explicit_preferred_majors" in delta or "inferred_interest_tags" in delta

    # Bare answer đã điền slot đang chờ và không thêm ngành → khỏi gọi LLM.
    if active_slot and active_slot in delta and _is_bare_answer(message) and not has_major_delta:
        return delta

    if gateway is None:
        from services import build_default_gateway
        gateway = build_default_gateway()
    if hasattr(gateway, "is_available") and not gateway.is_available():
        return delta

    # Một LLM call structured-output, state-update.
    try:
        result = gateway.run(InferenceRequest(
            agent_name="profile_extractor",
            task_type="profile_extraction",
            system_prompt=STATE_UPDATE_PROMPT,
            user_prompt=_render_state_update(known_state, message),
            output_mode="json",
            temperature=0.0,
        ))
        delta.update(_coerce_llm_delta(result.parsed_data))
    except InferenceError as exc:
        logger.warning("profile extractor LLM failed, dùng delta deterministic: %r", exc)

    return delta


def apply_profile_delta(current: ChatProfileState, delta: dict) -> ChatProfileState:
    """Áp delta, recompute missing_slots.

    Hỗ trợ op tích luỹ {"__add__": [...]} (union, dedupe, giữ thứ tự) cho list slot;
    slot vô hướng/list thường vẫn replace như cũ. Sau cùng tính lại view dẫn xuất
    preferred_majors = explicit ∪ inferred."""
    delta = dict(delta or {})
    add_ops: dict = {}
    scalar: dict = {}
    for key, value in delta.items():
        if isinstance(value, dict) and "__add__" in value:
            add_ops[key] = value["__add__"]
        else:
            scalar[key] = value

    merged = current.model_copy(update=scalar)

    # Seed legacy: row cũ chỉ có preferred_majors → coi là explicit (tránh union ghi rỗng đè mất).
    if (not merged.explicit_preferred_majors and not merged.inferred_interest_tags
            and merged.preferred_majors):
        merged.explicit_preferred_majors = list(merged.preferred_majors)

    for field, items in add_ops.items():
        existing = list(getattr(merged, field, []) or [])
        setattr(merged, field, list(dict.fromkeys([*existing, *items])))

    merged.preferred_majors = union_majors(
        merged.explicit_preferred_majors, merged.inferred_interest_tags
    )
    merged.missing_slots = missing_critical_slots(merged)
    return merged
