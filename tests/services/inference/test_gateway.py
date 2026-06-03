from services.inference.gateway import LLMGateway
from services.inference.models import InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry


class FakeProvider:
    def generate(self, request, policy):
        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider="fake",
            content='{"summary":"ok"}',
            parsed_data={"summary": "ok"},
        )


def test_gateway_uses_registry_and_provider():
    registry = ModelRegistry(default_model="gemini-2.5-flash-lite")
    gateway = LLMGateway(registry=registry, providers={"gemini": FakeProvider()})

    result = gateway.run(
        InferenceRequest(
            agent_name="profile_agent",
            task_type="profile_extraction",
            system_prompt="Extract profile",
            user_prompt="Em duoc 27 diem A00",
            output_mode="json",
        )
    )

    assert result.provider == "fake"
    assert result.model == "gemini-2.5-flash-lite"
    assert result.parsed_data == {"summary": "ok"}