import pytest

from services.inference.gateway import LLMGateway
from services.inference.models import InferenceError, InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry


def _registry_with_fallback():
    return ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={
            "reasoning_agent": {
                "primary_model": "gemini-2.5-flash-lite",
                "fallback_model": "gemini-2.5-flash",
                "allow_fallback": True,
                "max_retries": 1,
            }
        },
    )


def _request():
    return InferenceRequest(
        agent_name="reasoning_agent",
        task_type="recommendation_reasoning",
        system_prompt="test",
        user_prompt="test",
        output_mode="json",
    )


class RetryThenFallbackProvider:
    def __init__(self):
        self.calls = []

    def generate(self, request, policy):
        self.calls.append(policy.primary_model)
        if len(self.calls) == 1:
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider="fake",
                content="{bad json",
                failure_type="STRUCTURE_FAILURE",
            )
        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider="fake",
            content='{"decision":"fallback-success"}',
            parsed_data={"decision": "fallback-success"},
        )


def test_gateway_retries_structure_failure_then_succeeds():
    registry = ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={
            "reasoning_agent": {
                "primary_model": "gemini-2.5-flash-lite",
                "fallback_model": "gemini-2.5-flash",
                "allow_fallback": True,
                "max_retries": 1,
            }
        },
    )
    provider = RetryThenFallbackProvider()
    gateway = LLMGateway(registry=registry, providers={"gemini": provider})

    result = gateway.run(
        InferenceRequest(
            agent_name="reasoning_agent",
            task_type="recommendation_reasoning",
            system_prompt="test",
            user_prompt="test",
            output_mode="json",
        )
    )

    assert result.parsed_data == {"decision": "fallback-success"}
    assert provider.calls == ["gemini-2.5-flash-lite", "gemini-2.5-flash-lite"]


class HardErrorThenFallbackProvider:
    """Primary model raises a hard API error; fallback model succeeds."""

    def __init__(self):
        self.calls = []

    def generate(self, request, policy):
        self.calls.append(policy.primary_model)
        if policy.primary_model == "gemini-2.5-flash-lite":
            raise InferenceError("simulated 5xx")
        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider="fake",
            content='{"decision":"fallback-recovered"}',
            parsed_data={"decision": "fallback-recovered"},
        )


def test_gateway_falls_back_to_secondary_model_on_hard_api_error():
    provider = HardErrorThenFallbackProvider()
    gateway = LLMGateway(registry=_registry_with_fallback(), providers={"gemini": provider})

    result = gateway.run(_request())

    assert result.parsed_data == {"decision": "fallback-recovered"}
    # Primary attempted once (no point retrying the same dead model), then fallback.
    assert provider.calls == ["gemini-2.5-flash-lite", "gemini-2.5-flash"]


class AlwaysHardErrorProvider:
    def generate(self, request, policy):
        raise InferenceError("simulated total outage")


def test_gateway_raises_inference_error_when_primary_and_fallback_both_fail():
    gateway = LLMGateway(registry=_registry_with_fallback(), providers={"gemini": AlwaysHardErrorProvider()})

    with pytest.raises(InferenceError):
        gateway.run(_request())