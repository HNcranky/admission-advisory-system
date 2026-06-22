from services.inference.factory import build_default_gateway


def test_agent_token_budgets_are_set():
    registry = build_default_gateway().registry
    assert registry.resolve("knowledge_qa_agent").max_tokens == 2048
    assert registry.resolve("synthesis_agent").max_tokens == 1200
    assert registry.resolve("intent_router").max_tokens == 256
    assert registry.resolve("profile_extractor").max_tokens == 300


def test_unbudgeted_agent_stays_none():
    registry = build_default_gateway().registry
    assert registry.resolve("explanation_agent").max_tokens is None
