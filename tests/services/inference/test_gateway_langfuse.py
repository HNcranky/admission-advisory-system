from services.inference import gateway as gw
from services.inference.gateway import LLMGateway
from services.inference.models import InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry


class _FlakyProvider:
    """First call STRUCTURE_FAILURE, second succeeds."""

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def generate(self, request, policy):
        self.calls += 1
        failure = "STRUCTURE_FAILURE" if self.calls == 1 else None
        return InferenceResult(
            agent_name=request.agent_name, model=policy.primary_model, provider="fake",
            content="{}", parsed_data={} if failure is None else None, failure_type=failure,
            usage={"input": 1, "output": 2, "total": 3},
        )


def _gateway(provider, telemetry):
    registry = ModelRegistry(
        default_model="m",
        agent_overrides={"profile_agent": {"output_mode": "json", "max_retries": 1}},
    )
    return LLMGateway(registry=registry, providers={"gemini": provider}, telemetry=telemetry)


def _request():
    return InferenceRequest(
        agent_name="profile_agent", task_type="profile_extraction",
        system_prompt="s", user_prompt="u", output_mode="json",
    )


def test_gateway_emits_one_generation_per_attempt(monkeypatch):
    calls = []
    monkeypatch.setattr(gw, "record_generation", lambda **kw: calls.append(kw))

    _gateway(_FlakyProvider(), InferenceTelemetry()).run(_request())

    assert [c["attempt"] for c in calls] == [0, 1]
    assert all(c["used_fallback"] is False for c in calls)
    assert all(c["usage"] == {"input": 1, "output": 2, "total": 3} for c in calls)
    assert all(isinstance(c["latency_ms"], (int, float)) for c in calls)
    assert calls[-1]["model"] == "m"
