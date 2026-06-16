from eval.knowledge_qa.gateways import build_judge_gateway, build_model_gateway


def test_model_gateway_forces_qa_agent_onto_model():
    gw = build_model_gateway("gemini-2.5-flash-lite")
    policy = gw.registry.resolve("knowledge_qa_agent")

    assert policy.primary_model == "gemini-2.5-flash-lite"
    assert policy.allow_fallback is False  # measure the model alone
    assert policy.thinking_budget == 0


def test_judge_gateway_is_fixed_flash():
    gw = build_judge_gateway()
    policy = gw.registry.resolve("qa_eval_judge")

    assert policy.primary_model == "gemini-2.5-flash"
    assert policy.allow_fallback is False
