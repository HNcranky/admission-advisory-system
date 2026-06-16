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


def test_knowledge_qa_agent_disables_thinking():
    gateway = build_default_gateway()
    assert gateway.registry.resolve("knowledge_qa_agent").thinking_budget == 0


def test_synthesis_agent_keeps_default_thinking():
    gateway = build_default_gateway()
    # Deferred to Slice 4 eval — must remain unset (default dynamic thinking).
    assert gateway.registry.resolve("synthesis_agent").thinking_budget is None


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


def test_major_resolver_has_bounded_token_override():
    policy = build_default_gateway().registry.resolve("major_resolver")
    assert policy.primary_model == "gemini-2.5-flash-lite"  # cheap model is intended
    assert policy.max_tokens == 100                          # bounded tiny output
    assert policy.output_mode == "json"
