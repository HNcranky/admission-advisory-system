import os

from services.inference.gateway import LLMGateway
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry

# Matches the production knowledge_qa_agent budget in factory.py: 800 truncates a
# grounded answer mid-JSON → MAX_TOKENS → STRUCTURE_FAILURE, which would unfairly
# penalize a candidate for a budget artifact rather than a quality gap.
_QA_MAX_TOKENS = 2048


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
                "max_tokens": _QA_MAX_TOKENS,
                "thinking_budget": 0,
            },
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())


def build_judge_gateway() -> LLMGateway:
    """A fixed judge, so the judge never confounds the candidate comparison. The
    model is env-configurable (EVAL_JUDGE_MODEL) because the historical default
    `gemini-2.5-flash` is capped at 20 requests/day on the free tier, which a
    multi-candidate run exhausts; set it to a higher-quota model (e.g.
    `gemini-3.5-flash`) before a multi-candidate run."""
    judge_model = os.getenv("EVAL_JUDGE_MODEL", "gemini-2.5-flash")
    registry = ModelRegistry(
        default_model=judge_model,
        agent_overrides={
            "qa_eval_judge": {
                "primary_model": judge_model,
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": False,
                "max_tokens": 300,
                "thinking_budget": 0,
            },
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())
