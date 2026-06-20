import logging
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from observability.prompts import get_prompt_service
from services import build_default_gateway
from services.chat.models import ChatProfileState
from services.inference.models import InferenceRequest
from services.knowledge.taxonomy import (
    KNOWLEDGE_TOPICS,
    TOPIC_SYNONYMS,
    normalize_school as _normalize_school,
    normalize_topic as _normalize_topic,
)
from services.profile_service import normalize_text

# Canonical topics + synonym normalization live in services.knowledge.taxonomy
# (single source of truth shared with ingestion seed validation). Re-exported
# names above keep this module's public surface unchanged.

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """
Bạn là bộ phân loại intent cho hệ thống tư vấn tuyển sinh đại học Việt Nam.

Phân loại tin nhắn của user vào đúng 1 trong 7 route:

CONVERSATIONAL — chào hỏi, hỏi năng lực trợ lý, cảm ơn, tạm biệt, hỏi danh tính,
  hoặc bộc lộ cảm xúc/lo lắng về tuyển sinh. Trả thêm "subtype":
  GREETING | CAPABILITY | THANKS | GOODBYE | IDENTITY | EMOTIONAL_SUPPORT
  Ví dụ: "xin chào", "bạn giúp được gì", "cảm ơn nhé", "tạm biệt", "bạn là ai",
         "mình lo không đỗ đại học"

RESET_PROFILE — yêu cầu xoá hồ sơ tư vấn hiện tại, bắt đầu lại từ đầu, hoặc
  tư vấn cho người khác (hồ sơ mới).
  Ví dụ: "xoá thông tin cũ đi", "bắt đầu lại từ đầu", "tư vấn lại cho em gái em",
         "làm hồ sơ khác cho bạn em", "giờ tư vấn cho đứa em mình nhé"

ADVISORY_FLOW — câu hỏi tư vấn chọn ngành/trường dựa trên điểm số, nguyện vọng, khả năng đậu
  Ví dụ: "25 điểm A00 nên chọn trường nào", "em có đậu NEU không", "tư vấn ngành CNTT"

KNOWLEDGE_QA — câu hỏi thực tế về thông tin cụ thể của trường/ngành
  Ví dụ: "học phí UET bao nhiêu", "chương trình CNTT gồm gì", "có học bổng không", "ký túc xá thế nào"
  Trường "topic" CHỈ được nhận đúng 1 trong các giá trị:
    tuition | curriculum | scholarship | dormitory | admission_policy | program_overview
  Ánh xạ chủ đề về đúng giá trị trên, KHÔNG tự bịa giá trị mới:
    - phương thức xét tuyển / quy chế tuyển sinh / chỉ tiêu / điều kiện xét tuyển → admission_policy
    - học phí → tuition; học bổng → scholarship; chương trình/môn học → curriculum
    - ký túc xá → dormitory; việc làm/ra trường/cơ hội nghề nghiệp/giới thiệu ngành → program_overview
  Nếu không khớp chủ đề nào ở trên, để topic là null (vẫn giữ route KNOWLEDGE_QA).
  Ví dụ: "có bao nhiêu phương thức xét tuyển của HUST"
       → {"route":"KNOWLEDGE_QA","topic":"admission_policy","school":"HUST"}

FOLLOWUP — câu hỏi nối tiếp chỉ cần SUY LUẬN / TÍNH TOÁN / LÀM RÕ dựa trên
  thông tin ĐÃ có trong lịch sử hội thoại, KHÔNG cần tra cứu dữ liệu/tài liệu mới.
  Chỉ dùng khi câu trả lời nằm ngay trong lịch sử hội thoại ở trên; nếu cần dữ
  kiện mới (mà lịch sử chưa nêu) → KNOWLEDGE_QA.
  Ví dụ (sau khi trợ lý vừa trả lời học phí theo tháng):
    "vậy một năm đóng bao nhiêu?", "thế tổng 4 năm là bao nhiêu?",
    "ý bạn là mỗi kỳ đúng không?", "quy ra mỗi tháng thì sao?"

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
        "FOLLOWUP",
        "CLARIFICATION",
        "OUT_OF_SCOPE",
        "CONVERSATIONAL",
        "RESET_PROFILE",
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

    @field_validator("school", mode="before")
    @classmethod
    def _coerce_school(cls, v):
        # The LLM is asked to emit a corpus code but sometimes returns the full
        # name ("đại học bách khoa hà nội"); retrieval matches `school` exactly,
        # so canonicalize here or the lookup finds zero chunks. Unknown → raw.
        return _normalize_school(v)

    @field_validator("schools", mode="before")
    @classmethod
    def _coerce_schools(cls, v):
        if not v:
            return []
        seen, out = set(), []
        for s in v:
            canonical = _normalize_school(s)
            if canonical and canonical not in seen:
                seen.add(canonical)
                out.append(canonical)
        return out

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


# Deterministic keyword fallback for when the LLM gateway is unavailable or its
# response is unusable. Phrases are normalize_text()-normalized substrings.
# Knowledge topics are checked BEFORE advisory phrases so a factual question
# never re-runs the advisory pipeline while the Gemini keys are cooling down
# (session 131, 2026-05-31: "có bao nhiêu phương thức xét tuyển..." was
# blanket-routed to ADVISORY_FLOW three turns in a row).
_FALLBACK_KNOWLEDGE_TOPICS = (
    ("hoc phi", "tuition"),
    ("hoc bong", "scholarship"),
    ("ky tuc xa", "dormitory"),
    ("phuong thuc xet tuyen", "admission_policy"),
    ("quy che tuyen sinh", "admission_policy"),
    ("chi tieu", "admission_policy"),
    ("chuong trinh hoc", "curriculum"),
    ("mon hoc", "curriculum"),
    ("viec lam", "program_overview"),
    ("ra truong lam", "program_overview"),
    ("co hoi nghe nghiep", "program_overview"),
)
_FALLBACK_ADVISORY_PHRASES = (
    "tu van", "nen chon", "nen hoc", "nen nop",
    "muon hoc", "muon theo hoc", "muon vao",
    "co dau", "do dau", "kha nang dau", "co hoi dau", "diem chuan",
)
_FALLBACK_CONVERSATIONAL = (
    ("cam on", "THANKS"),
    ("tam biet", "GOODBYE"),
    ("ban la ai", "IDENTITY"),
    ("giup duoc gi", "CAPABILITY"),
    ("chao", "GREETING"),
)


class IntentRouter:
    def __init__(self, gateway=None):
        self._gateway = gateway or build_default_gateway()

    def classify(self, message: str, profile_state: ChatProfileState, history: str = "") -> IntentResult:
        try:
            if hasattr(self._gateway, "is_available") and not self._gateway.is_available():
                return self._fallback_classify(message)
            cp = get_prompt_service().get("intent-router", fallback=INTENT_SYSTEM_PROMPT)
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="intent_router",
                    task_type="intent_classification",
                    system_prompt=cp.text,
                    prompt=cp.handle,
                    user_prompt=self._build_user_prompt(message, profile_state, history),
                    output_mode="json",
                    response_schema=IntentResult,
                    temperature=0.0,
                )
            )
            if not result.parsed_data:
                return self._fallback_classify(message)
            return IntentResult.model_validate(result.parsed_data)
        except Exception as exc:
            logger.warning("intent classification failed, using fallback route: %r", exc)
            return self._fallback_classify(message)

    @staticmethod
    def _fallback_classify(message: str) -> IntentResult:
        """Deterministic keyword router used when the LLM cannot classify.

        Mirrors the prompt's priority rules (concrete need beats greeting).
        Unrecognized messages become CLARIFICATION so the assistant asks again
        instead of silently re-running the advisory pipeline. Bare slot answers
        ("năm 2026", "29 điểm") never reach the router — ConversationService
        handles them deterministically via _maybe_continue_advisory first.
        """
        normalized = normalize_text(message or "")
        for phrase, topic in _FALLBACK_KNOWLEDGE_TOPICS:
            if phrase in normalized:
                return IntentResult(route="KNOWLEDGE_QA", topic=topic)
        for phrase in _FALLBACK_ADVISORY_PHRASES:
            if phrase in normalized:
                return IntentResult(route="ADVISORY_FLOW")
        for phrase, subtype in _FALLBACK_CONVERSATIONAL:
            if phrase in normalized:
                return IntentResult(route="CONVERSATIONAL", subtype=subtype)
        return IntentResult(route="CLARIFICATION")

    def _build_user_prompt(self, message: str, profile_state: ChatProfileState, history: str = "") -> str:
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
        prefix = (
            f"Lịch sử hội thoại gần đây:\n{history}\n\n" if history else ""
        )
        return (
            f"{prefix}"
            f'Tin nhắn: "{message}"\n\n'
            f"Profile hiện tại:\n"
            f"- Trường quan tâm: {schools}\n"
            f"- Ngành quan tâm: {majors}\n"
            f"- Điểm số: {profile_state.total_score or 'chưa có'}\n"
            f"- Khối thi: {profile_state.subject_combination or 'chưa có'}"
        )
