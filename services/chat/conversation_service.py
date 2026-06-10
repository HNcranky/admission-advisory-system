import logging

from services import build_default_gateway
from services.chat.intent_router import IntentRouter
from services.chat.models import ChatProfileState, ConversationTurnResult
from services.chat.history import build_history_context
from services.chat.knowledge_fanout import format_knowledge_blocks, run_knowledge_fanout
from services.chat.repository import ChatSessionRepository
from services.knowledge.qa_service import KnowledgeQAService
from services.knowledge.retrieval_query import build_retrieval_query
from services.profile.slots import (
    SLOTS, build_slot_acknowledgement, follow_up_for, missing_critical_slots,
    next_follow_up_question, parse_slot,
)
from services.profile.extractor import apply_profile_delta, extract_profile_update
from services.profile.validation import validate_profile_delta
from services.profile_service import normalize_text

logger = logging.getLogger(__name__)

# Slot critical theo thứ tự — dùng để phát hiện correction (AC7).
_ORDERED_CRITICAL = [s.name for s in sorted(SLOTS, key=lambda s: s.order) if s.critical]

CLARIFICATION_PROMPTS = {
    "school": "Bạn đang muốn tìm hiểu thông tin của trường nào?",
    "programs": "Bạn muốn so sánh hoặc tìm hiểu (những) ngành nào?",
    "subject_combination": "Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?",
    "admission_year": "Bạn đang xét tuyển cho năm nào?",
}
CLARIFICATION_FIELD_ORDER = ["school", "programs", "subject_combination", "admission_year"]
GENERIC_CLARIFICATION = (
    "Bạn có thể nói rõ hơn câu hỏi của mình không? Mình muốn hiểu đúng để hỗ trợ tốt hơn."
)

# Cụm từ reset tường minh (đã normalize). CỐ Ý hẹp — cách nói mềm ("tư vấn cho
# em gái em") để LLM route RESET_PROFILE xử lý, tránh false positive.
_RESET_PHRASES = (
    "xoa thong tin", "xoa ho so", "xoa het",
    "bat dau lai", "lam lai tu dau", "tu van lai tu dau", "reset",
)


def _is_reset_request(content: str) -> bool:
    normalized = normalize_text(content or "")
    return any(phrase in normalized for phrase in _RESET_PHRASES)


class ConversationService:
    def __init__(self, repository=None, extract_profile=None, intent_router=None, knowledge_qa=None):
        self.repository = repository or ChatSessionRepository()
        self.extract_profile = extract_profile or self._extract_profile
        self.intent_router = intent_router or IntentRouter()
        self.knowledge_qa = knowledge_qa or KnowledgeQAService()

    def _extract_profile(self, text: str, known_state=None, active_slot=None):
        gateway = build_default_gateway()
        return extract_profile_update(text, known_state=known_state,
                                      active_slot=active_slot, gateway=gateway)

    _TOPIC_LABELS = {
        "tuition": "học phí",
        "curriculum": "chương trình học",
        "scholarship": "học bổng",
        "dormitory": "ký túc xá",
        "career": "định hướng nghề nghiệp",
        "admission_policy": "chính sách tuyển sinh",
        "program_overview": "tổng quan chương trình",
    }

    def handle_user_message(self, session_token: str, content: str) -> ConversationTurnResult:
        # Build history from turns BEFORE this one — fetch prior to appending so
        # the message being processed is excluded. The last user turn in that
        # history is the referent for an elided follow-up (used by retrieval).
        prior_messages = self.repository.list_message(session_token)
        history_ctx = build_history_context(prior_messages)
        prev_user = next(
            (m.content for m in reversed(prior_messages) if m.role == "user"), ""
        )
        self.repository.append_message(session_token, "user", content, "user_message")
        session = self.repository.get_session_by_token(session_token)
        profile_state = self.repository.get_profile_state(session_token)
        flow_state = self.repository.get_flow_state(session_token)

        # Trích xuất ĐÚNG MỘT LẦN/lượt; cả nhánh continue lẫn advisory dùng chung delta.
        active_slot = (missing_critical_slots(profile_state) or [None])[0]
        delta = self.extract_profile(content, profile_state, active_slot)
        delta = self._deterministic_safety_net(delta, content, active_slot)

        # EC-22: reset tường minh phải thắng mọi nhánh khác — kể cả
        # _maybe_continue_advisory (tránh "xoá hết..., năm 2026" bị nuốt vào hồ sơ cũ).
        if _is_reset_request(content):
            return self._handle_reset(session_token, delta, flow_state)

        delta, rejections = validate_profile_delta(delta, profile_state)
        if rejections:
            return self._handle_rejection(
                session_token, profile_state, flow_state, delta, rejections
            )

        # A reply to a pending advisory follow-up is an *answer*, not a fresh
        # intent. Route it back into the advisory flow when it actually fills the
        # slot we just asked about — the stateless intent classifier otherwise
        # misreads a bare answer like "năm 2026" as small talk and silently drops
        # the value. See docs/admission-advisory-conversational-architecture.md §4, §9.
        continued = self._maybe_continue_advisory(session_token, content, profile_state, flow_state, delta)
        if continued is not None:
            return continued

        # A value-changing correction after a run already produced recommendations
        # must deterministically re-rank (the stateless router would mis-handle a
        # phrasing like "à em tính lại 25.75, không phải 27"). See AC7.
        corrected = self._maybe_correction_rerun(session_token, profile_state, flow_state, delta, session)
        if corrected is not None:
            return corrected

        intent = self.intent_router.classify(content, profile_state, history=history_ctx)
        session_status = session.status if session else "collecting_profile"

        if intent.route == "ADVISORY_FLOW":
            return self._handle_advisory(session_token, profile_state, flow_state, delta)
        if intent.route == "KNOWLEDGE_QA":
            return self._handle_knowledge_qa(session_token, content, intent, profile_state, flow_state, session_status, history_ctx, prev_user)
        if intent.route == "HYBRID":
            return self._handle_hybrid(session_token, content, intent, profile_state, flow_state, session_status, history_ctx, prev_user)
        if intent.route == "OUT_OF_SCOPE":
            return self._handle_out_of_scope(session_token, profile_state, flow_state, session_status)
        if intent.route == "CONVERSATIONAL":
            return self._handle_conversational(
                session_token, content, intent, profile_state, flow_state, session_status
            )
        if intent.route == "RESET_PROFILE":
            return self._handle_reset(session_token, delta, flow_state)
        return self._handle_clarification(
            session_token, intent, profile_state, flow_state, session_status
        )

    @staticmethod
    def _deterministic_safety_net(delta: dict, content: str, active_slot) -> dict:
        """Parse năm (luôn) và slot đang chờ (nếu có parser) độc lập với extractor.

        Giữ hành vi cũ: admission_year luôn được nhận từ raw; câu trả lời cụt
        cho slot đang chờ (vd "29" -> total_score) vẫn được điền."""
        delta = dict(delta)
        if "admission_year" not in delta:
            year = parse_slot("admission_year", content)
            if year is not None:
                delta["admission_year"] = year
        if active_slot and active_slot != "admission_year" and active_slot not in delta:
            val = parse_slot(active_slot, content)
            if val is not None:
                delta[active_slot] = val
        return delta

    def _handle_rejection(self, session_token, profile_state, flow_state, clean_delta, rejections):
        """Giá trị vô lệ theo thang phương thức (EC-04): áp phần hợp lệ, trả lời
        từ chối kèm hướng dẫn, và trỏ pending_question về slot bị từ chối để câu
        trả lời cụt lượt sau vẫn được safety-net nhận."""
        merged = apply_profile_delta(profile_state, clean_delta)
        self.repository.update_profile_state(session_token, merged, "collecting_profile")

        rejected_slot = rejections[0]["slot"]
        pending = follow_up_for(rejected_slot) or next_follow_up_question(merged)
        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": pending,
            }),
        )
        message = rejections[0]["message"]
        self.repository.append_message(session_token, "assistant", message, "assistant_validation")
        return ConversationTurnResult(
            session_status="collecting_profile",
            assistant_message=message,
            should_start_run=False,
            profile_state=merged,
        )

    def _maybe_continue_advisory(self, session_token, content, profile_state, flow_state, delta):
        """Treat a reply as the answer to a pending advisory follow-up.

        Returns a ``ConversationTurnResult`` when the message actually fills the
        slot we last asked about (so the advisory flow continues), otherwise
        ``None`` so the caller falls through to normal intent routing — that path
        still handles genuine mid-flow interruptions (e.g. a tuition question).
        """
        if flow_state.active_flow != "ADVISORY_FLOW" or not flow_state.pending_question:
            return None
        pending = missing_critical_slots(profile_state)
        if not pending:
            return None
        pending_slot = pending[0]

        merged = apply_profile_delta(profile_state, delta)
        answered = bool(getattr(merged, pending_slot)) and (
            getattr(merged, pending_slot) != getattr(profile_state, pending_slot)
        )
        if not answered:
            return None
        return self._advance_advisory(session_token, merged, flow_state)

    def _maybe_correction_rerun(self, session_token, profile_state, flow_state, delta, session):
        """Treat a value-changing edit to an already-set critical slot as a correction.

        Only fires when a prior run exists (profile was complete / ran before), so an
        ordinary first-fill during collection still flows through normal routing.
        Returns a ``ConversationTurnResult`` (re-run) or ``None`` to fall through.
        """
        if session is None:
            return None
        prior_run = (getattr(session, "status", None) in ("completed", "ready")) or bool(
            getattr(session, "latest_run_id", None)
        )
        if not prior_run:
            return None

        correction = None
        for slot_name in _ORDERED_CRITICAL:
            if slot_name not in delta:
                continue
            new_value = delta[slot_name]
            if isinstance(new_value, dict) and "__add__" in new_value:
                continue  # accumulation op (majors), not a scalar correction
            previous = getattr(profile_state, slot_name, None)
            if previous in (None, [], ""):
                continue  # first-fill, not a correction
            if new_value != previous:
                correction = {"slot": slot_name, "previous_value": previous, "new_value": new_value}
                break
        if correction is None:
            return None

        merged = apply_profile_delta(profile_state, delta)
        self.repository.update_profile_state(session_token, merged, "ready")
        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": None,
            }),
        )
        ack = "Mình sẽ tính lại với thông tin bạn vừa cập nhật."
        self.repository.append_message(session_token, "assistant", ack, "assistant_ready")
        return ConversationTurnResult(
            session_status="ready",
            assistant_message=ack,
            should_start_run=True,
            profile_state=merged,
            correction_note=correction,
        )

    def _handle_reset(self, session_token, delta, flow_state):
        """EC-22: bắt đầu hồ sơ trắng; delta của CHÍNH lượt này áp lên hồ sơ mới
        (user kèm "năm 2026" thì khỏi hỏi lại năm). Không xoá lịch sử chat."""
        fresh = ChatProfileState()
        clean_delta, _ = validate_profile_delta(delta, fresh)
        merged = apply_profile_delta(fresh, clean_delta)

        follow_up = next_follow_up_question(merged)
        if follow_up is None:
            # Hiếm: delta một lượt điền đủ slot critical → vào thẳng phân tích.
            return self._advance_advisory(session_token, merged, flow_state)

        self.repository.update_profile_state(session_token, merged, "collecting_profile")
        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": follow_up,
            }),
        )
        message = f"Mình đã bắt đầu hồ sơ tư vấn mới. {follow_up}"
        self.repository.append_message(session_token, "assistant", message, "assistant_follow_up")
        return ConversationTurnResult(
            session_status="collecting_profile",
            assistant_message=message,
            should_start_run=False,
            profile_state=merged,
        )

    def _handle_advisory(self, session_token, profile_state, flow_state, delta):
        merged = apply_profile_delta(profile_state, delta)
        return self._advance_advisory(session_token, merged, flow_state, delta)

    def _advance_advisory(self, session_token, merged, flow_state, delta=None):
        follow_up = next_follow_up_question(merged)
        if follow_up:
            ack = build_slot_acknowledgement(delta, merged)
            message = f"{ack}\n\n{follow_up}" if ack else follow_up
            self.repository.update_profile_state(session_token, merged, "collecting_profile")
            self.repository.update_flow_state(
                session_token,
                flow_state.model_copy(update={
                    "active_flow": "ADVISORY_FLOW",
                    "pending_question": follow_up,  # stays bare; ack is message-only
                }),
            )
            self.repository.append_message(session_token, "assistant", message, "assistant_follow_up")
            return ConversationTurnResult(
                session_status="collecting_profile",
                assistant_message=message,
                should_start_run=False,
                profile_state=merged,
            )

        ready_message = "Cảm ơn bạn. Mình đã có đủ thông tin và sẽ bắt đầu phân tích."
        self.repository.update_profile_state(session_token, merged, "ready")
        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": None,  # clear: no question is pending once we run
            }),
        )
        self.repository.append_message(session_token, "assistant", ready_message, "assistant_ready")
        return ConversationTurnResult(
            session_status="ready",
            assistant_message=ready_message,
            should_start_run=True,
            profile_state=merged,
        )

    def _handle_knowledge_qa(self, session_token, content, intent, profile_state, flow_state, session_status, history_ctx="", prev_user=""):
        # Resolve school: router value first, else the student's top preferred school.
        school = intent.school or (
            profile_state.preferred_schools[0] if profile_state.preferred_schools else None
        )

        result = None
        try:
            result = self.knowledge_qa.answer(
                question=content,
                school=school,
                topic=intent.topic,
                conversation_context=history_ctx,
                retrieval_query=build_retrieval_query(content, prev_user),
            )
        except Exception as exc:
            # any embed/LLM/DB failure → graceful fallback below
            logger.warning("knowledge QA path failed for school=%r topic=%r: %r", school, intent.topic, exc)
            result = None

        if result is not None and result.has_data and result.answer:
            body = self._format_answer_with_sources(result.answer, result.citations)
            citations = result.citations
        else:
            topic_label = self._TOPIC_LABELS.get(intent.topic or "", "thông tin này")
            school_label = school or "trường bạn hỏi"
            body = (
                f"Mình hiện chưa có dữ liệu về {topic_label} của {school_label}. "
                f"Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
            )
            citations = []

        response = self._maybe_offer_resume(body, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
            citations=citations,
        )

    def _handle_hybrid(self, session_token, content, intent, profile_state, flow_state, session_status, history_ctx="", prev_user=""):
        missing = missing_critical_slots(profile_state)

        if not missing:
            # Profile complete → dispatch an async hybrid run (advisory ∥ knowledge → synthesis).
            placeholder = (
                "Câu hỏi này cần đối chiếu cả dữ liệu tuyển sinh lẫn thông tin trường, "
                "mình đang tổng hợp, bạn chờ một chút nhé."
            )
            self.repository.append_message(session_token, "assistant", placeholder, "assistant_hybrid_pending")
            return ConversationTurnResult(
                session_status=session_status,
                assistant_message=placeholder,
                should_start_run=True,
                run_kind="hybrid",
                hybrid_intent=intent.model_dump(),
                profile_state=profile_state,
            )

        # Profile incomplete → answer the knowledge half inline, ask the next advisory follow-up.
        school_fallback = profile_state.preferred_schools[0] if profile_state.preferred_schools else None
        blocks = run_knowledge_fanout(self.knowledge_qa, intent, content, school_fallback, conversation_context=history_ctx, prev_user=prev_user)
        body = format_knowledge_blocks(blocks)

        follow_up = next_follow_up_question(profile_state.model_copy(update={"missing_slots": missing}))
        response = f"{body}\n\nNhân tiện, {follow_up}" if follow_up else body

        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": follow_up,
            }),
        )
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    @staticmethod
    def _format_answer_with_sources(answer, citations):
        urls = []
        for citation in citations:
            if citation.source_url and citation.source_url not in urls:
                urls.append(citation.source_url)
        if not urls:
            return answer
        sources = "\n".join(f"- {url}" for url in urls)
        return f"{answer}\n\nNguồn:\n{sources}"

    def _handle_conversational(
        self, session_token, content, intent, profile_state, flow_state, session_status
    ):
        from services.chat.conversational_handler import build_conversational_response

        body = build_conversational_response(intent.subtype, seed=len(content))
        # _maybe_offer_resume only fires when an advisory flow is active,
        # so a greeting with no active flow won't include the resume offer.
        response = self._maybe_offer_resume(body, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    def _handle_out_of_scope(self, session_token, profile_state, flow_state, session_status):
        msg = (
            "Xin lỗi, câu hỏi này nằm ngoài phạm vi tư vấn tuyển sinh của mình. "
            "Mình chỉ có thể hỗ trợ các vấn đề liên quan đến tuyển sinh đại học."
        )
        response = self._maybe_offer_resume(msg, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    def _handle_clarification(self, session_token, intent, profile_state, flow_state, session_status):
        msg = self._clarification_question(intent.missing_fields)
        response = self._maybe_offer_resume(msg, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    @staticmethod
    def _clarification_question(missing_fields) -> str:
        for field in CLARIFICATION_FIELD_ORDER:
            if field in (missing_fields or []):
                return CLARIFICATION_PROMPTS[field]
        return GENERIC_CLARIFICATION

    RESUME_OFFER = "Bạn có muốn tiếp tục phần tư vấn lúc nãy không?"

    def _maybe_offer_resume(self, message: str, flow_state) -> str:
        """Offer quay lại advisory flow một cách tự nhiên khi user rẽ ngang.

        Chỉ kích hoạt khi đang giữa advisory flow (active_flow set và còn
        pending_question). KHÔNG lặp lại nguyên câu hỏi cũ — tránh cảm giác máy móc.
        """
        if flow_state.active_flow == "ADVISORY_FLOW" and flow_state.pending_question:
            return f"{message}\n\n{self.RESUME_OFFER}"
        return message
