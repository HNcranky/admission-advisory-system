import services.inference.gateway as gw
from services.inference.gateway import LLMGateway
from services.inference.models import InferencePolicy, InferenceRequest, InferenceResult


class _OkProvider:
    def generate(self, request, policy):
        return InferenceResult(
            agent_name=request.agent_name, model=policy.primary_model,
            provider="fake", content="ok", failure_type=None,
        )


class _PrimaryFailsProvider:
    """Primary attempt structure-fails so the gateway uses the fallback model."""

    def __init__(self):
        self.calls = 0

    def generate(self, request, policy):
        self.calls += 1
        if self.calls == 1:
            return InferenceResult(
                agent_name=request.agent_name, model=policy.primary_model,
                provider="fake", content="", failure_type="STRUCTURE_FAILURE",
            )
        return InferenceResult(
            agent_name=request.agent_name, model=policy.primary_model,
            provider="fake", content="ok", failure_type=None,
        )


class _Registry:
    def __init__(self, policy):
        self._policy = policy

    def resolve(self, agent_name):
        return self._policy


def _request(prompt):
    return InferenceRequest(
        agent_name="intent_router", task_type="intent_classification",
        system_prompt="s", user_prompt="u", prompt=prompt,
    )


def test_primary_path_forwards_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(gw, "record_generation", lambda **kw: captured.append(kw))
    policy = InferencePolicy(agent_name="intent_router", primary_model="m", max_retries=0)
    gateway = LLMGateway(registry=_Registry(policy), providers={"gemini": _OkProvider()})
    sentinel = object()
    gateway.run(_request(sentinel))
    assert captured and captured[0]["prompt"] is sentinel


def test_fallback_path_forwards_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(gw, "record_generation", lambda **kw: captured.append(kw))
    policy = InferencePolicy(
        agent_name="intent_router", primary_model="m", fallback_model="m2",
        allow_fallback=True, max_retries=0,
    )
    gateway = LLMGateway(
        registry=_Registry(policy), providers={"gemini": _PrimaryFailsProvider()},
    )
    sentinel = object()
    gateway.run(_request(sentinel))
    # both the primary (structure-failure) and fallback generations carry the handle
    assert all(kw["prompt"] is sentinel for kw in captured)
    assert len(captured) == 2
