import logging

from pydantic import ValidationError

from agents.models import StudentProfile
from services.inference.models import InferenceError, InferenceRequest
from services.profile.major_resolver import resolve_majors
from services.profile.slots import missing_critical_slots
from services.profile_service import build_profile

logger = logging.getLogger(__name__)


PROFILE_SYSTEM_PROMPT = """
Trích xuất hồ sơ tư vấn tuyển sinh từ tin nhắn của học sinh Việt Nam.
Trả JSON với các khóa (dùng null cho vô hướng chưa biết, [] cho list chưa biết):
- total_score: số hoặc null
- subject_combination: mã tổ hợp như "A00", "A01", "D01" hoặc null
- preferred_schools: danh sách trường học sinh nhắc tới
- location_preference: tỉnh/khu vực muốn học (vd "Ha Noi", "Mien Bac") hoặc null
- tuition_budget: chuỗi mô tả ngân sách học phí hoặc null
- constraints: list ràng buộc khác (gia đình, học bổng, công việc) hoặc []
KHÔNG cần trả preferred_majors — hệ thống tự suy ngành từ sở thích.
"""


def build_profile_with_gateway(user_query: str, gateway) -> StudentProfile:
    if hasattr(gateway, "is_available") and not gateway.is_available():
        profile = build_profile(user_query)
    else:
        try:
            result = gateway.run(
                InferenceRequest(
                    agent_name="profile_agent",
                    task_type="profile_extraction",
                    system_prompt=PROFILE_SYSTEM_PROMPT.strip(),
                    user_prompt=user_query,
                    output_mode="json",
                    temperature=0.0,
                )
            )
        except InferenceError as exc:
            logger.warning("profile extraction gateway failed, using rule-based: %r", exc)
            profile = build_profile(user_query)
        else:
            try:
                data = dict(result.parsed_data or {})
                data.pop("preferred_majors", None)  # majors do resolver lo
                data.pop("missing_slots", None)
                profile = StudentProfile(**data)
            except ValidationError as exc:
                logger.warning("profile JSON failed schema validation, using rule-based: %r", exc)
                profile = build_profile(user_query)

    # preferred_majors: tiered resolver (alias -> embedding -> LLM). Degrade -> [].
    try:
        majors = resolve_majors(user_query, known_state=profile)
    except Exception as exc:  # an toàn tuyệt đối: không bao giờ raise lên caller
        logger.warning("resolve_majors failed: %r", exc)
        majors = []
    if majors:
        profile.preferred_majors = majors
    elif not profile.preferred_majors:
        # giữ alias-hit từ build_profile (rule path) nếu có; else rỗng
        profile.preferred_majors = profile.preferred_majors

    profile.missing_slots = missing_critical_slots(profile)
    return profile
