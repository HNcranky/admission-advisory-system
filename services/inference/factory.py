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
                # Grounded answers over ~10k chars of retrieved chunks run ~1.9k
                # output tokens; 800 truncated them mid-JSON → MAX_TOKENS finish →
                # json.loads failure → STRUCTURE_FAILURE on every retry → no-data.
                "max_tokens": 2048,
                "thinking_budget": 0,
            },
            "followup_reasoner": {
                # Answers context-only follow-ups (reason/compute over what was
                # already said) — no RAG. JSON carries a `sufficient` flag so the
                # caller can fall back to retrieval when history lacks the facts.
                "primary_model": "gemini-2.5-flash",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
                "max_tokens": 1024,
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
            "fact_extractor": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
            },
            "intent_router": {"output_mode": "json", "max_retries": 1, "max_tokens": 256},
            "profile_extractor": {"output_mode": "json", "max_retries": 1, "max_tokens": 300},
            "major_resolver": {"output_mode": "json", "max_retries": 1, "max_tokens": 100},
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())
