from services.inference.gateway import LLMGateway
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry


def build_default_gateway() -> LLMGateway:
    registry = ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={
            "profile_agent": {"output_mode": "json", "max_retries": 1},
            "reasoning_agent": {
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
            },
            "policy_agent": {
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
            },
            "explanation_agent": {"output_mode": "free_text", "max_retries": 1},
            "knowledge_qa_agent": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
                "max_tokens": 800,
                "thinking_budget": 0,
            },
            "synthesis_agent": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "free_text",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
                "max_tokens": 1200,
            },
            "knowledge_ocr": {
                "output_mode": "free_text",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash",
            },
            "knowledge_classify": {"output_mode": "json", "max_retries": 1},
            "intent_router": {"output_mode": "json", "max_retries": 1, "max_tokens": 256},
            "profile_extractor": {"output_mode": "json", "max_retries": 1, "max_tokens": 300},
            "major_resolver": {"output_mode": "json", "max_retries": 1, "max_tokens": 100},
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())
