from services.inference.models import InferenceRequest


def test_prompt_defaults_to_none():
    req = InferenceRequest(
        agent_name="x", task_type="t", system_prompt="s", user_prompt="u",
    )
    assert req.prompt is None


def test_prompt_accepts_arbitrary_handle():
    sentinel = object()  # stands in for a Langfuse prompt client
    req = InferenceRequest(
        agent_name="x", task_type="t", system_prompt="s", user_prompt="u",
        prompt=sentinel,
    )
    assert req.prompt is sentinel
