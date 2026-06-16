from services.inference.gateway import LLMGateway
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry


def build_model_gateway(model: str) -> LLMGateway:
    """Gateway that forces `knowledge_qa_agent` onto `model` with NO fallback, so
    the eval measures the model in isolation."""
    registry = ModelRegistry(
        default_model=model,
        agent_overrides={
            "knowledge_qa_agent": {
                "primary_model": model,
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": False,
                "max_tokens": 800,
                "thinking_budget": 0,
            },
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())


def build_judge_gateway() -> LLMGateway:
    """A fixed `flash` judge, so the judge never confounds the flash-vs-flash-lite
    comparison."""
    registry = ModelRegistry(
        default_model="gemini-2.5-flash",
        agent_overrides={
            "qa_eval_judge": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": False,
                "max_tokens": 300,
                "thinking_budget": 0,
            },
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())
