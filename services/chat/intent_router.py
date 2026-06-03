import logging
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Canonical knowledge topics. Synonyms the LLM commonly emits are normalized to
# these; anything unrecognized degrades to None rather than failing the whole
# classification (a secondary field must never invalidate the route).
KNOWLEDGE_TOPICS = frozenset({
    "tuition", "curriculum", "scholarship", "dormitory",
    "career", "admission_policy", "program_overview",
})
_TOPIC_SYNONYMS = {
    "admission_method": "admission_policy",
    "admission_methods": "admission_policy",
    "admission": "admission_policy",
    "admissions": "admission_policy",
    "admission_regulation": "admission_policy",
    "quota": "admission_policy",
}


def _normalize_topic(value):
    if value is None:
        return None
    key = str(value).strip().lower()
    if key in KNOWLEDGE_TOPICS:
        return key
    return _TOPIC_SYNONYMS.get(key)  # None if unrecognized

from services import build_default_gateway
from services.chat.models import ChatProfileState
from services.inference.models import InferenceRequest

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """
Bạn là bộ phân loại intent cho hệ thống tư vấn tuyển sinh đại học Việt Nam.

Phân loại tin nhắn của user vào đúng 1 trong 6 route:

CONVERSATIONAL — chào hỏi, hỏi năng lực trợ lý, cảm ơn, tạm biệt, hỏi danh tính,
  hoặc bộc lộ cảm xúc/lo lắng về tuyển sinh. Trả thêm "subtype":
  GREETING | CAPABILITY | THANKS | GOODBYE | IDENTITY | EMOTIONAL_SUPPORT
  Ví dụ: "xin chào", "bạn giúp được gì", "cảm ơn nhé", "tạm biệt", "bạn là ai",
         "mình lo không đỗ đại học"

ADVISORY_FLOW — câu hỏi tư vấn chọn ngành/trường dựa trên điểm số, nguyện vọng, khả năng đậu
  Ví dụ: "25 điểm A00 nên chọn trường nào", "em có đậu NEU không", "tư vấn ngành CNTT"

KNOWLEDGE_QA — câu hỏi thực tế về thông tin cụ thể của trường/ngành
  Ví dụ: "học phí UET bao nhiêu", "chương trình CNTT gồm gì", "có học bổng không", "ký túc xá thế nào"
  Trường "topic" CHỈ được nhận đúng 1 trong các giá trị:
    tuition | curriculum | scholarship | dormitory | career | admission_policy | program_overview
  Ánh xạ chủ đề về đúng giá trị trên, KHÔNG tự bịa giá trị mới:
    - phương thức xét tuyển / quy chế tuyển sinh / chỉ tiêu / điều kiện xét tuyển → admission_policy
    - học phí → tuition; học bổng → scholarship; chương trình/môn học → curriculum
    - ký túc xá → dormitory; việc làm/ra trường → career; giới thiệu ngành → program_overview
  Nếu không khớp chủ đề nào ở trên, để topic là null (vẫn giữ route KNOWLEDGE_QA).
  Ví dụ: "có bao nhiêu phương thức xét tuyển của HUST"
       → {"route":"KNOWLEDGE_QA","topic":"admission_policy","school":"HUST"}

CLARIFICATION — câu quá mơ hồ, thiếu context để phân loại chính xác
  Ví dụ: "thế còn cái đó thì sao" (không rõ đối tượng), "ý bạn là gì"

OUT_OF_SCOPE — hoàn toàn ngoài lĩnh vực tuyển sinh đại học
  Ví dụ: "thời tiết hôm nay", "kể chuyện cười", "1+1 bằng mấy", "giúp tôi viết code"

HYBRID — cần cả dữ liệu tư vấn (điểm chuẩn, xác suất đậu) lẫn thông tin thực tế (học phí, chương trình)
  Ví dụ: "so sánh UET và HUST về điểm chuẩn lẫn học phí"
  Chỉ dùng HYBRID khi câu hỏi thực sự cần cả hai loại dữ liệu.

Quy tắc resolve đại từ:
- "trường này", "ở đó", "trường đó" → dùng preferred_schools trong profile (nếu có)
- "ngành này", "chuyên ngành đó" → dùng preferred_majors trong profile (nếu có)
- Không thể resolve → để school/topic là null, route về CLARIFICATION

Quy tắc ưu tiên CONVERSATIONAL vs CLARIFICATION:
- KHÔNG ép lời chào / cảm ơn / câu hỏi năng lực vào CLARIFICATION.
- CLARIFICATION chỉ khi đã hiểu user muốn gì nhưng thiếu entity bắt buộc;
  khi đó trả thêm "missing_fields", ví dụ ["school"].
- Nếu message vừa chào vừa có nhu cầu rõ ("Chào bạn, học phí UET?") → ưu tiên
  KNOWLEDGE_QA/ADVISORY_FLOW, KHÔNG dừng ở greeting.

Few-shot CONVERSATIONAL & CLARIFICATION:
"Xin chào"            → {"route":"CONVERSATIONAL","subtype":"GREETING"}
"Bạn giúp được gì?"   → {"route":"CONVERSATIONAL","subtype":"CAPABILITY"}
"Cảm ơn nhé"          → {"route":"CONVERSATIONAL","subtype":"THANKS"}
"Tạm biệt"            → {"route":"CONVERSATIONAL","subtype":"GOODBYE"}
"Bạn là ai?"          → {"route":"CONVERSATIONAL","subtype":"IDENTITY"}
"Mình lo không đỗ"    → {"route":"CONVERSATIONAL","subtype":"EMOTIONAL_SUPPORT"}
"Học phí trường này?" (không có school trong profile)
                      → {"route":"CLARIFICATION","missing_fields":["school"]}

Chuẩn hóa tên trường thành viết tắt phổ biến nếu nhận ra: VNU-UET, HUST, NEU, VNU-HCMUS, UEH, FTU, ...

Với route HYBRID, trả thêm các trường:
- "schools": danh sách trường cần so sánh, ví dụ ["VNU-UET", "HUST"]
- "topics": danh sách chủ đề knowledge cần tra cứu, ví dụ ["tuition", "curriculum"]
- "needs_advisory": true nếu câu hỏi cần dữ liệu điểm chuẩn / khả năng đậu;
  false nếu chỉ so sánh thông tin thực tế (ví dụ chỉ học phí giữa các trường)

Ví dụ HYBRID:
"So sánh UET và HUST về điểm chuẩn lẫn học phí"
→ {"route":"HYBRID","schools":["VNU-UET","HUST"],"topics":["tuition"],"needs_advisory":true}
"So sánh học phí UET và HUST"
→ {"route":"HYBRID","schools":["VNU-UET","HUST"],"topics":["tuition"],"needs_advisory":false}

Trả về JSON hợp lệ, không giải thích thêm.
Với các route khác (không phải HYBRID và CONVERSATIONAL) chỉ cần:
{"route": "...", "topic": "...", "school": "..."}
""".strip()


class IntentResult(BaseModel):
    route: Literal[
        "ADVISORY_FLOW",
        "KNOWLEDGE_QA",
        "HYBRID",
        "CLARIFICATION",
        "OUT_OF_SCOPE",
        "CONVERSATIONAL",
    ]
    subtype: Optional[
        Literal[
            "GREETING",
            "CAPABILITY",
            "THANKS",
            "GOODBYE",
            "IDENTITY",
            "EMOTIONAL_SUPPORT",
        ]
    ] = None
    topic: Optional[str] = None
    school: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    # HYBRID-only; default empty/false → no behavior change for other routes.
    schools: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    needs_advisory: bool = False

    @field_validator("topic", mode="before")
    @classmethod
    def _coerce_topic(cls, v):
        # Unknown topic → None (keeps the route); known synonym → canonical.
        return _normalize_topic(v)

    @field_validator("topics", mode="before")
    @classmethod
    def _coerce_topics(cls, v):
        if not v:
            return []
        normalized = [_normalize_topic(t) for t in v]
        # Drop unrecognized entries, dedupe while preserving order.
        seen, out = set(), []
        for t in normalized:
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out


_FALLBACK = IntentResult(route="ADVISORY_FLOW")


class IntentRouter:
    def __init__(self, gateway=None):
        self._gateway = gateway or build_default_gateway()

    def classify(self, message: str, profile_state: ChatProfileState) -> IntentResult:
        try:
            if hasattr(self._gateway, "is_available") and not self._gateway.is_available():
                return _FALLBACK
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="intent_router",
                    task_type="intent_classification",
                    system_prompt=INTENT_SYSTEM_PROMPT,
                    user_prompt=self._build_user_prompt(message, profile_state),
                    output_mode="json",
                    temperature=0.0,
                )
            )
            if not result.parsed_data:
                return _FALLBACK
            return IntentResult.model_validate(result.parsed_data)
        except Exception as exc:
            logger.warning("intent classification failed, using fallback route: %r", exc)
            return _FALLBACK

    def _build_user_prompt(self, message: str, profile_state: ChatProfileState) -> str:
        schools = (
            ", ".join(profile_state.preferred_schools)
            if profile_state.preferred_schools
            else "chưa có"
        )
        majors = (
            ", ".join(profile_state.preferred_majors)
            if profile_state.preferred_majors
            else "chưa có"
        )
        return (
            f'Tin nhắn: "{message}"\n\n'
            f"Profile hiện tại:\n"
            f"- Trường quan tâm: {schools}\n"
            f"- Ngành quan tâm: {majors}\n"
            f"- Điểm số: {profile_state.total_score or 'chưa có'}\n"
            f"- Khối thi: {profile_state.subject_combination or 'chưa có'}"
        )
