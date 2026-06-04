"""Validate chéo delta hồ sơ trước khi áp (EC-04).

Pure function — không I/O, không LLM. Trả (clean_delta, rejections);
mỗi rejection: {"slot", "value", "message"} với message tiếng Việt dùng được ngay.
"""
from typing import Dict, List, Tuple

from services.profile.admission_methods import SCORE_SCALES, method_display


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def validate_profile_delta(delta: dict, current) -> Tuple[dict, List[Dict]]:
    clean = dict(delta or {})
    rejections: List[Dict] = []

    delta_method = clean.get("admission_method")
    effective_method = delta_method or getattr(current, "admission_method", None)
    scale = SCORE_SCALES.get(effective_method) if effective_method else None

    # R1 — điểm mới vượt thang của phương thức hiệu lực.
    score = clean.get("total_score")
    score_value = _as_float(score) if not isinstance(score, dict) else None
    if scale is not None and score_value is not None and score_value > scale:
        clean.pop("total_score", None)
        rejections.append({
            "slot": "total_score",
            "value": score_value,
            "message": (
                f"Với phương thức {method_display(effective_method)} (thang {_fmt(scale)}), "
                f"tổng điểm {_fmt(score_value)} chưa hợp lệ. Em kiểm tra lại điểm hoặc cho mình "
                "biết em đang dùng phương thức xét tuyển nào nhé."
            ),
        })
        return clean, rejections

    # R2 — phương thức mới làm điểm ĐÃ LƯU thành vô lệ → xoá điểm, hỏi lại.
    existing_score = _as_float(getattr(current, "total_score", None))
    if (delta_method and scale is not None and existing_score is not None
            and existing_score > scale and "total_score" not in clean):
        clean["total_score"] = None  # apply_profile_delta sẽ set None → slot hỏi lại
        rejections.append({
            "slot": "total_score",
            "value": existing_score,
            "message": (
                f"Em chọn phương thức {method_display(delta_method)} (thang {_fmt(scale)}) "
                f"nhưng điểm {_fmt(existing_score)} đã ghi trước đó vượt thang này, nên mình "
                "xoá điểm cũ. Điểm của em theo phương thức này là bao nhiêu?"
            ),
        })

    return clean, rejections
