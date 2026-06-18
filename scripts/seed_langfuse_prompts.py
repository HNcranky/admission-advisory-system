"""One-off: seed managed system prompts into Langfuse as the production version.

Run once after Langfuse is configured (ADVISORY_LANGFUSE_ENABLED=true + keys):

    .venv/bin/python -m scripts.seed_langfuse_prompts      # Linux
    .\\.venv\\Scripts\\python.exe -m scripts.seed_langfuse_prompts   # Windows

Idempotent: a prompt that already exists is skipped, so re-runs never create
spurious versions. Not part of the test suite (scripts/ convention).
"""
import logging

from observability.langfuse_client import flush_langfuse, get_langfuse
from services.chat.intent_router import INTENT_SYSTEM_PROMPT
from services.chat.synthesis_agent import SYNTHESIS_SYSTEM_PROMPT
from services.knowledge.qa_service import KNOWLEDGE_QA_SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed_langfuse_prompts")

# Langfuse prompt name -> in-code fallback constant (same names PromptService.get uses).
MANAGED_PROMPTS = {
    "intent-router": INTENT_SYSTEM_PROMPT,
    "knowledge-qa": KNOWLEDGE_QA_SYSTEM_PROMPT,
    "synthesis": SYNTHESIS_SYSTEM_PROMPT,
}


def _exists(client, name: str) -> bool:
    try:
        client.get_prompt(name, cache_ttl_seconds=0)
        return True
    except Exception:
        return False


def main() -> int:
    client = get_langfuse()
    if client is None:
        logger.error(
            "Langfuse disabled/misconfigured; set ADVISORY_LANGFUSE_ENABLED=true "
            "and LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY before seeding."
        )
        return 1
    for name, text in MANAGED_PROMPTS.items():
        if _exists(client, name):
            logger.info("skip %s (already exists)", name)
            continue
        client.create_prompt(name=name, prompt=text, labels=["production"], type="text")
        logger.info("created %s (labelled production)", name)
    flush_langfuse()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
