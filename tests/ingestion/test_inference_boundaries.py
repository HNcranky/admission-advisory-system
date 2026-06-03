from services.inference.factory import build_default_gateway


def test_gateway_registry_has_no_retrieval_agent_override():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("retrieval_agent")

    assert policy.primary_model == "gemini-2.5-flash-lite"
    assert policy.allow_fallback is False


def test_gateway_registry_enables_resolution_agent_fallback():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("resolution_agent")

    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash"