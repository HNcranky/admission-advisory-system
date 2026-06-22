import pytest

from services.chat.intent_router import IntentResult, IntentRouter


def test_intent_result_defaults():
    result = IntentResult(route="ADVISORY_FLOW")
    assert result.route == "ADVISORY_FLOW"
    assert result.topic is None
    assert result.school is None


def test_intent_result_full():
    result = IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET")
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "tuition"
    assert result.school == "VNU-UET"


def test_intent_result_has_no_return_to_flow_field():
    """return_to_flow was removed; it must not be a model field."""
    assert "return_to_flow" not in IntentResult.model_fields


def test_intent_result_rejects_invalid_route():
    with pytest.raises(Exception):
        IntentResult(route="INVALID_ROUTE")


def test_intent_result_coerces_unknown_topic_to_none():
    """An unknown topic is a secondary field — it must NOT invalidate the whole
    classification (which would dump a correct KNOWLEDGE_QA into the fallback)."""
    result = IntentResult(route="KNOWLEDGE_QA", topic="invalid_topic")
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic is None


def test_intent_result_normalizes_admission_methods_to_policy():
    """LLM commonly emits 'admission_methods' for 'phương thức xét tuyển';
    map it to the canonical admission_policy topic instead of dropping it."""
    assert IntentResult(route="KNOWLEDGE_QA", topic="admission_methods").topic == "admission_policy"
    assert IntentResult(route="KNOWLEDGE_QA", topic="admission_method").topic == "admission_policy"


def test_intent_result_normalizes_career_to_program_overview():
    """Career/job questions are answered from the 'Cơ hội việc làm' section of
    program-overview pages — there is no standalone career corpus — so 'career'
    must normalize to program_overview, not a dead topic that retrieves nothing."""
    assert IntentResult(route="KNOWLEDGE_QA", topic="career").topic == "program_overview"
    assert IntentResult(route="KNOWLEDGE_QA", topics=["career"]).topics == ["program_overview"]


def test_fallback_classify_career_question_routes_to_program_overview():
    """Regression: 'cơ hội việc làm ngành X' must reach the program_overview
    corpus where the career section lives (was routed to empty 'career')."""
    res = IntentRouter._fallback_classify("cơ hội việc làm của ngành kỹ thuật ô tô")
    assert res.route == "KNOWLEDGE_QA"
    assert res.topic == "program_overview"


def test_intent_result_model_validate_from_dict():
    result = IntentResult.model_validate({"route": "OUT_OF_SCOPE"})
    assert result.route == "OUT_OF_SCOPE"
    assert result.topic is None


from services.chat.models import ChatProfileState
from services.chat.intent_router import IntentRouter


def _prompt_router():
    """Router whose gateway is a dummy object — _build_user_prompt never touches it."""
    return IntentRouter(gateway=object())


def test_build_user_prompt_includes_message():
    prompt = _prompt_router()._build_user_prompt("học phí UET bao nhiêu", ChatProfileState())
    assert "học phí UET bao nhiêu" in prompt


def test_build_user_prompt_includes_preferred_schools():
    profile = ChatProfileState(preferred_schools=["VNU-UET", "HUST"])
    prompt = _prompt_router()._build_user_prompt("msg", profile)
    assert "VNU-UET" in prompt
    assert "HUST" in prompt


def test_build_user_prompt_shows_chua_co_when_empty():
    prompt = _prompt_router()._build_user_prompt("msg", ChatProfileState())
    assert "chưa có" in prompt


def test_build_user_prompt_includes_score_and_combination():
    profile = ChatProfileState(total_score=25.0, subject_combination="A00")
    prompt = _prompt_router()._build_user_prompt("msg", profile)
    assert "25.0" in prompt
    assert "A00" in prompt


def test_build_user_prompt_has_no_return_to_flow_line():
    """return_to_flow was removed from the prompt — the LLM must not be asked to compute it."""
    prompt = _prompt_router()._build_user_prompt("msg", ChatProfileState(total_score=25.0))
    assert "return_to_flow" not in prompt


def test_build_user_prompt_includes_history_block():
    history = "Người dùng: học phí UET?\nTrợ lý: 15 triệu/năm"
    prompt = _prompt_router()._build_user_prompt(
        "còn HUST thì sao", ChatProfileState(), history=history
    )
    assert "Lịch sử hội thoại gần đây" in prompt
    assert "15 triệu/năm" in prompt


def test_build_user_prompt_omits_history_block_when_empty():
    prompt = _prompt_router()._build_user_prompt("msg", ChatProfileState(), history="")
    assert "Lịch sử hội thoại" not in prompt


from services.inference.models import InferenceError, InferenceResult


class FakeGateway:
    def __init__(self, parsed_data=None, should_raise=False, available=True):
        self._parsed_data = parsed_data
        self._should_raise = should_raise
        self._available = available

    def is_available(self):
        return self._available

    def run(self, request):
        if self._should_raise:
            raise InferenceError("simulated failure")
        return InferenceResult(
            agent_name=request.agent_name,
            model="test-model",
            provider="test",
            content="{}",
            parsed_data=self._parsed_data,
        )


def _router(**kwargs):
    return IntentRouter(gateway=FakeGateway(**kwargs))


# --- ADVISORY_FLOW (5) ---

def test_classify_advisory_basic():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("25 điểm A00 nên chọn trường nào", ChatProfileState()).route == "ADVISORY_FLOW"


def test_classify_advisory_eligibility():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("em có đậu NEU không", ChatProfileState()).route == "ADVISORY_FLOW"


def test_classify_advisory_major_advice():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("tư vấn ngành CNTT cho mình", ChatProfileState()).route == "ADVISORY_FLOW"


def test_classify_advisory_score_combination():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("điểm 28 khối B00 nên nộp đâu", ChatProfileState()).route == "ADVISORY_FLOW"


def test_classify_advisory_chance_question():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("cơ hội đậu Bách Khoa của em là bao nhiêu", ChatProfileState()).route == "ADVISORY_FLOW"


# --- KNOWLEDGE_QA (5) ---

def test_classify_knowledge_tuition_with_school():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "tuition", "school": "VNU-UET"})
    result = r.classify("học phí UET bao nhiêu", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "tuition"
    assert result.school == "VNU-UET"


def test_classify_knowledge_curriculum():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "curriculum", "school": None})
    result = r.classify("chương trình CNTT gồm gì", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "curriculum"


def test_classify_knowledge_scholarship():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "scholarship"})
    result = r.classify("có học bổng không", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "scholarship"


def test_classify_knowledge_dormitory():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "dormitory"})
    result = r.classify("ký túc xá thế nào", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "dormitory"


def test_classify_admission_methods_question_stays_knowledge_qa():
    """Regression: LLM returns topic='admission_methods' (off the old enum).
    Previously this raised a ValidationError and fell back to ADVISORY_FLOW,
    misrouting a factual question into the advisory pipeline."""
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "admission_methods", "school": "HUST"})
    result = r.classify("có bao nhiêu phương thức xét tuyển của HUST", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "admission_policy"
    assert result.school == "HUST"


def test_classify_knowledge_pronoun_resolved_from_profile():
    """'trường này' resolved to preferred_schools by the LLM; router passes it through."""
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "tuition", "school": "VNU-UET"})
    profile = ChatProfileState(preferred_schools=["VNU-UET"])
    result = r.classify("trường này học phí bao nhiêu", profile)
    assert result.route == "KNOWLEDGE_QA"
    assert result.school == "VNU-UET"


# --- OUT_OF_SCOPE (4) ---

def test_classify_out_of_scope_weather():
    r = _router(parsed_data={"route": "OUT_OF_SCOPE"})
    assert r.classify("thời tiết hôm nay thế nào", ChatProfileState()).route == "OUT_OF_SCOPE"


def test_classify_out_of_scope_joke():
    r = _router(parsed_data={"route": "OUT_OF_SCOPE"})
    assert r.classify("kể cho tôi nghe một câu chuyện cười", ChatProfileState()).route == "OUT_OF_SCOPE"


def test_classify_out_of_scope_coding_help():
    r = _router(parsed_data={"route": "OUT_OF_SCOPE"})
    assert r.classify("giúp tôi viết code Python", ChatProfileState()).route == "OUT_OF_SCOPE"


def test_classify_out_of_scope_food():
    r = _router(parsed_data={"route": "OUT_OF_SCOPE"})
    assert r.classify("hôm nay ăn gì ngon", ChatProfileState()).route == "OUT_OF_SCOPE"


# --- CLARIFICATION (3) ---

def test_classify_clarification_ambiguous_pronoun():
    r = _router(parsed_data={"route": "CLARIFICATION"})
    assert r.classify("thế còn cái đó thì sao", ChatProfileState()).route == "CLARIFICATION"


def test_classify_clarification_vague():
    r = _router(parsed_data={"route": "CLARIFICATION"})
    assert r.classify("ý bạn là gì", ChatProfileState()).route == "CLARIFICATION"


def test_classify_clarification_no_context():
    r = _router(parsed_data={"route": "CLARIFICATION"})
    assert r.classify("còn nữa không", ChatProfileState()).route == "CLARIFICATION"


# --- FALLBACK / DEGRADED (deterministic keyword router) ---
# Blanket-falling back to ADVISORY_FLOW re-ran the advisory pipeline on factual
# questions whenever the Gemini keys were cooling down (session 131, 2026-05-31:
# "có bao nhiêu phương thức xét tuyển..." → 3× advisory re-run). The degraded
# path must classify by keywords instead, and ask for clarification when unsure.

def test_fallback_admission_methods_question_is_not_advisory():
    """Session-131 regression: LLM down → factual question must NOT re-run advisory."""
    result = _router(available=False).classify(
        "có bao nhiêu phương thức xét tuyển của đại học bách khoa hà nội",
        ChatProfileState(),
    )
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "admission_policy"


def test_fallback_on_inference_error_routes_tuition_by_keyword():
    result = _router(should_raise=True).classify("học phí HUST bao nhiêu", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "tuition"


def test_fallback_on_invalid_route_routes_dormitory_by_keyword():
    """LLM returns a route outside the Literal → validation error → keyword fallback."""
    result = _router(parsed_data={"route": "MADE_UP_ROUTE"}).classify(
        "ký túc xá thế nào", ChatProfileState()
    )
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "dormitory"


def test_fallback_greeting_routes_conversational():
    result = _router(parsed_data=None).classify("chào bạn", ChatProfileState())
    assert result.route == "CONVERSATIONAL"
    assert result.subtype == "GREETING"


# --- school canonicalization (LLM emits free-form names, corpus stores codes) ---
# Without this the LLM returning "đại học bách khoa hà nội" reaches retrieval as
# WHERE school = 'đại học bách khoa hà nội' → zero chunks → KnowledgeQA no-data.

def test_intent_result_canonicalizes_full_school_name_to_corpus_code():
    result = IntentResult.model_validate(
        {"route": "KNOWLEDGE_QA", "topic": "admission_policy",
         "school": "đại học bách khoa hà nội"}
    )
    assert result.school == "HUST"


def test_classify_canonicalizes_school_from_llm_output():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "admission_policy",
                             "school": "Đại học Bách khoa Hà Nội"})
    result = r.classify("bách khoa có mấy phương thức xét tuyển", ChatProfileState())
    assert result.school == "HUST"


def test_intent_result_canonicalizes_hybrid_schools_list():
    result = IntentResult.model_validate(
        {"route": "HYBRID", "schools": ["đại học công nghệ", "HUST"],
         "topics": ["tuition"]}
    )
    assert result.schools == ["VNU-UET", "HUST"]


def test_intent_result_unknown_school_passes_through():
    result = IntentResult.model_validate(
        {"route": "KNOWLEDGE_QA", "school": "Đại học FPT"}
    )
    assert result.school == "Đại học FPT"


def test_fallback_thanks_routes_conversational():
    result = _router(should_raise=True).classify("cảm ơn nhé", ChatProfileState())
    assert result.route == "CONVERSATIONAL"
    assert result.subtype == "THANKS"


def test_fallback_advisory_request_stays_advisory():
    result = _router(should_raise=True).classify("tư vấn ngành CNTT cho mình", ChatProfileState())
    assert result.route == "ADVISORY_FLOW"


def test_fallback_study_wish_opener_stays_advisory():
    """An advisory opener like 'em muốn học X' must keep collecting the profile
    in degraded mode (asserted end-to-end by the web fallback-extractor test)."""
    result = _router(available=False).classify(
        "Em muon hoc CNTT tai HUST nam 2026", ChatProfileState()
    )
    assert result.route == "ADVISORY_FLOW"


def test_fallback_unrecognized_message_asks_clarification():
    """No keyword match → ask the user again instead of guessing ADVISORY_FLOW."""
    result = _router(should_raise=True).classify("bất kỳ câu gì", ChatProfileState())
    assert result.route == "CLARIFICATION"


def test_fallback_mixed_greeting_and_knowledge_prefers_knowledge():
    """Mirror of the LLM prompt rule: greeting + concrete need → answer the need."""
    result = _router(available=False).classify("chào bạn, học phí UET bao nhiêu?", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "tuition"


# --- HYBRID schema (Phase 5a) ---

def test_intent_result_hybrid_fields_default_empty():
    result = IntentResult(route="ADVISORY_FLOW")
    assert result.schools == []
    assert result.topics == []
    assert result.needs_advisory is False


def test_intent_result_hybrid_full_payload():
    result = IntentResult.model_validate({
        "route": "HYBRID",
        "schools": ["VNU-UET", "HUST"],
        "topics": ["tuition", "curriculum"],
        "needs_advisory": True,
    })
    assert result.route == "HYBRID"
    assert result.schools == ["VNU-UET", "HUST"]
    assert result.topics == ["tuition", "curriculum"]
    assert result.needs_advisory is True


def test_intent_result_hybrid_filters_unknown_topics_in_list():
    """Unknown topics are dropped from the list; known ones (incl. normalized
    synonyms) are kept, so a HYBRID classification is never invalidated."""
    result = IntentResult.model_validate(
        {"route": "HYBRID", "topics": ["not_a_topic", "tuition", "admission_methods"]}
    )
    assert result.topics == ["tuition", "admission_policy"]


def test_intent_result_singular_fields_still_work():
    result = IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="NEU")
    assert result.topic == "tuition"
    assert result.school == "NEU"
    assert result.schools == []
    assert result.topics == []


# --- HYBRID classification + prompt wording (Phase 5a) ---

def test_classify_hybrid_compare_scores_and_tuition():
    r = _router(parsed_data={
        "route": "HYBRID",
        "schools": ["VNU-UET", "HUST"],
        "topics": ["tuition"],
        "needs_advisory": True,
    })
    result = r.classify("so sánh UET và HUST về điểm chuẩn lẫn học phí", ChatProfileState())
    assert result.route == "HYBRID"
    assert result.schools == ["VNU-UET", "HUST"]
    assert result.topics == ["tuition"]
    assert result.needs_advisory is True


def test_classify_hybrid_pure_knowledge_comparison_sets_needs_advisory_false():
    r = _router(parsed_data={
        "route": "HYBRID",
        "schools": ["VNU-UET", "HUST"],
        "topics": ["tuition"],
        "needs_advisory": False,
    })
    result = r.classify("so sánh học phí UET và HUST", ChatProfileState())
    assert result.route == "HYBRID"
    assert result.needs_advisory is False


def test_intent_prompt_documents_hybrid_payload():
    from services.chat.intent_router import INTENT_SYSTEM_PROMPT
    assert "needs_advisory" in INTENT_SYSTEM_PROMPT
    assert "schools" in INTENT_SYSTEM_PROMPT
    assert "topics" in INTENT_SYSTEM_PROMPT


def test_classify_passes_through_conversational_subtype():
    r = _router(parsed_data={"route": "CONVERSATIONAL", "subtype": "GREETING"})
    result = r.classify("xin chào", ChatProfileState())
    assert result.route == "CONVERSATIONAL"
    assert result.subtype == "GREETING"


def test_classify_passes_through_missing_fields():
    r = _router(parsed_data={"route": "CLARIFICATION", "missing_fields": ["school"]})
    result = r.classify("học phí trường này", ChatProfileState())
    assert result.route == "CLARIFICATION"
    assert result.missing_fields == ["school"]


def test_classify_missing_fields_defaults_empty():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    result = r.classify("25 điểm nên chọn ngành nào", ChatProfileState())
    assert result.missing_fields == []


def test_intent_prompt_documents_conversational_route():
    from services.chat.intent_router import INTENT_SYSTEM_PROMPT
    assert "CONVERSATIONAL" in INTENT_SYSTEM_PROMPT
    assert "GREETING" in INTENT_SYSTEM_PROMPT
    assert "missing_fields" in INTENT_SYSTEM_PROMPT


def test_intent_prompt_enumerates_topics_and_maps_admission_methods():
    from services.chat.intent_router import INTENT_SYSTEM_PROMPT
    assert "admission_policy" in INTENT_SYSTEM_PROMPT
    assert "phương thức xét tuyển" in INTENT_SYSTEM_PROMPT


# --- RESET_PROFILE (reasoning-integrity plan 4) ---

def test_intent_result_accepts_reset_profile_route():
    assert IntentResult(route="RESET_PROFILE").route == "RESET_PROFILE"


def test_classify_reset_profile_passthrough():
    r = _router(parsed_data={"route": "RESET_PROFILE"})
    result = r.classify("xoá thông tin cũ đi, tư vấn lại cho em gái em", ChatProfileState())
    assert result.route == "RESET_PROFILE"


def test_intent_prompt_documents_reset_profile_route():
    from services.chat.intent_router import INTENT_SYSTEM_PROMPT
    assert "RESET_PROFILE" in INTENT_SYSTEM_PROMPT
    assert "tư vấn cho người khác" in INTENT_SYSTEM_PROMPT


# --- response schema (slice1e) ---

def test_classify_sends_response_schema():
    from services.chat.intent_router import IntentRouter, IntentResult
    from services.chat.models import ChatProfileState

    captured = {}

    class _CapturingGateway:
        def is_available(self):
            return True
        def run(self, request):
            captured["request"] = request
            from services.inference.models import InferenceResult
            return InferenceResult(
                agent_name=request.agent_name, model="m", provider="p",
                content='{"route": "ADVISORY_FLOW"}',
                parsed_data={"route": "ADVISORY_FLOW"},
            )

    router = IntentRouter(gateway=_CapturingGateway())
    router.classify("25 điểm A00 nên chọn trường nào", ChatProfileState())
    assert captured["request"].response_schema is IntentResult
