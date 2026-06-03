import logging
from typing import Optional

from services.chat.models import ChatProfileState
from services.inference.models import InferenceError, InferenceRequest
from services.profile.major_resolver import resolve_majors
from services.profile.slots import SLOTS, missing_critical_slots, parse_slot

logger = logging.getLogger(__name__)

# Slot vô hướng LLM được phép trả (preferred_majors do resolver; preferred_schools/
# constraints trích cơ hội nhưng vẫn nằm trong allow-list bên dưới nếu LLM trả).
_LLM_SLOT_KEYS = {
    "admission_year", "total_score", "subject_combination",
    "location_preference", "tuition_budget", "preferred_schools", "constraints",
}

STATE_UPDATE_PROMPT = """
Bạn cập nhật hồ sơ tư vấn tuyển sinh của một học sinh Việt Nam qua hội thoại.
Bạn được cho HỒ SƠ ĐÃ BIẾT và TIN NHẮN MỚI. CHỈ trả về các trường THAY ĐỔI
hoặc MỚI xuất hiện trong tin nhắn mới (delta), KHÔNG lặp lại trường không đổi.

Trả JSON, chỉ gồm các khóa có giá trị mới (dùng đúng tên khóa):
- total_score: số (0..40)
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
        out[key] = value
    return out


def extract_profile_update(message: str, *, known_state, active_slot: Optional[str] = None,
                           gateway=None, resolver=resolve_majors) -> dict:
    """Trả DELTA: chỉ slot thay đổi lượt này (DST update)."""
    message = message or ""
    delta: dict = {}

    # Tier-0: parse câu trả lời cụt cho slot đang chờ (deterministic).
    if active_slot:
        val = parse_slot(active_slot, message)
        if val is not None:
            delta[active_slot] = val

    # preferred_majors: ủy thác resolver tiered (Slice 2). Không bao giờ raise lên.
    try:
        majors = resolver(message, known_state=known_state, gateway=gateway)
    except Exception as exc:
        logger.warning("resolve_majors failed in extractor: %r", exc)
        majors = []
    if majors:
        delta["preferred_majors"] = majors

    # Bare answer đã điền slot đang chờ → khỏi gọi LLM (minimize_num_calls).
    if active_slot and active_slot in delta and _is_bare_answer(message):
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
    """Áp delta (override slot có trong delta), recompute missing_slots."""
    merged = current.model_copy(update=delta)
    merged.missing_slots = missing_critical_slots(merged)
    return merged
