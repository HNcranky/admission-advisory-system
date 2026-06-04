from services.inference.factory import build_default_gateway


def test_build_default_gateway_has_expected_agent_defaults():
    gateway = build_default_gateway()

    profile_policy = gateway.registry.resolve("profile_agent")
    reasoning_policy = gateway.registry.resolve("reasoning_agent")
    explanation_policy = gateway.registry.resolve("explanation_agent")

    assert profile_policy.primary_model == "gemini-2.5-flash-lite"
    assert reasoning_policy.allow_fallback is True
    assert reasoning_policy.fallback_model == "gemini-2.5-flash-lite"
    assert explanation_policy.output_mode == "free_text"


def test_knowledge_qa_agent_policy_uses_flash_with_json_and_fallback():
    gateway = build_default_gateway()

    policy = gateway.registry.resolve("knowledge_qa_agent")

    assert policy.primary_model == "gemini-2.5-flash"
    assert policy.output_mode == "json"
    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash-lite"


def test_synthesis_agent_is_registered():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("synthesis_agent")
    assert policy.primary_model == "gemini-2.5-flash"
    assert policy.output_mode == "free_text"
    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash-lite"


def test_knowledge_ocr_agent_uses_default_model_with_fallback():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("knowledge_ocr")
    assert policy.primary_model == "gemini-2.5-flash-lite"   # default model (spec D1)
    assert policy.output_mode == "free_text"
    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash"


def test_knowledge_classify_agent_uses_json_mode():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("knowledge_classify")
    assert policy.primary_model == "gemini-2.5-flash-lite"
    assert policy.output_mode == "json"
    assert policy.max_retries == 1
