from services.inference.gateway import LLMGateway
from services.inference.models import InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry


class _FlakyProvider:
    """First call returns STRUCTURE_FAILURE, second call succeeds."""

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def generate(self, request, policy):
        self.calls += 1
        failure = "STRUCTURE_FAILURE" if self.calls == 1 else None
        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider="fake",
            content="{}",
            parsed_data={} if failure is None else None,
            failure_type=failure,
        )


def _gateway(provider, telemetry):
    registry = ModelRegistry(
        default_model="m",
        agent_overrides={"profile_agent": {"output_mode": "json", "max_retries": 1}},
    )
    return LLMGateway(registry=registry, providers={"gemini": provider}, telemetry=telemetry)


def test_gateway_records_one_event_per_attempt():
    telemetry = InferenceTelemetry()
    provider = _FlakyProvider()
    gateway = _gateway(provider, telemetry)

    gateway.run(
        InferenceRequest(
            agent_name="profile_agent",
            task_type="profile_extraction",
            system_prompt="s",
            user_prompt="u",
            output_mode="json",
        )
    )

    assert len(telemetry.events) == 2
    assert telemetry.events[0]["failure_type"] == "STRUCTURE_FAILURE"
    assert telemetry.events[0]["attempt"] == 0
    assert telemetry.events[1]["failure_type"] is None
    assert telemetry.events[1]["attempt"] == 1
    assert all(event["agent_name"] == "profile_agent" for event in telemetry.events)
