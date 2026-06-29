import os

from services.inference.gateway import LLMGateway
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry

# Runtime models are resolved from the environment so a model swap (e.g. moving
# to a gemini-3.x tier) needs only a `.env` change, not a code edit. Two tiers
# cover every agent: LITE is the cheap default + every graceful-degradation
# fallback; STRONG is the primary for the reasoning-heavy agents (knowledge QA,
# follow-up, synthesis, fact extraction, OCR fallback). Defaults preserve the
# previously hard-coded gemini-2.5 behavior, so an unset environment is a no-op.
# To switch everything: set ADVISORY_MODEL_STRONG / ADVISORY_MODEL_LITE in .env
# (e.g. gemini-3.5-flash / gemini-3.1-flash-lite). Validate any swap with the
# eval/knowledge_qa harness before relying on it.
LITE_MODEL = os.getenv("ADVISORY_MODEL_LITE", "gemini-2.5-flash-lite")
STRONG_MODEL = os.getenv("ADVISORY_MODEL_STRONG", "gemini-2.5-flash")


def build_default_gateway() -> LLMGateway:
    registry = ModelRegistry(
        default_model=LITE_MODEL,
        agent_overrides={
            "profile_agent": {"output_mode": "json", "max_retries": 1},
            "reasoning_agent": {
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": LITE_MODEL,
            },
            "policy_agent": {
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": LITE_MODEL,
            },
            "explanation_agent": {"output_mode": "free_text", "max_retries": 1},
            "knowledge_qa_agent": {
                "primary_model": STRONG_MODEL,
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": LITE_MODEL,
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
                "primary_model": STRONG_MODEL,
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": LITE_MODEL,
                "max_tokens": 1024,
                "thinking_budget": 0,
            },
            "synthesis_agent": {
                "primary_model": STRONG_MODEL,
                "output_mode": "free_text",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": LITE_MODEL,
                "max_tokens": 1200,
            },
            "knowledge_ocr": {
                "output_mode": "free_text",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": STRONG_MODEL,
            },
            "knowledge_classify": {"output_mode": "json", "max_retries": 1},
            "fact_extractor": {
                "primary_model": STRONG_MODEL,
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": LITE_MODEL,
            },
            "intent_router": {"output_mode": "json", "max_retries": 1, "max_tokens": 256},
            "profile_extractor": {"output_mode": "json", "max_retries": 1, "max_tokens": 300},
            "major_resolver": {"output_mode": "json", "max_retries": 1, "max_tokens": 100},
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())
