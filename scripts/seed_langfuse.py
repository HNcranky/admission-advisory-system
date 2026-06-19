"""Seed Langfuse prompt management + score configs for this project.

Idempotent-ish: prompts are skipped when the production version already holds
identical text; score configs are skipped when a config of the same name exists.

Run (needs the Langfuse stack up + ADVISORY_LANGFUSE_ENABLED=true with keys in
.env):

    .venv/bin/python -m scripts.seed_langfuse

NOT part of the test suite (scripts/ is probe/seed drivers only).
"""
import logging

from observability.langfuse_client import get_langfuse
from observability.prompts import _label  # production label the app fetches with

# Prompts the app fetches by name (observability/prompts.py call sites).
# Seed from the in-code fallback constants so Langfuse never drifts from code.
from services.chat.intent_router import INTENT_SYSTEM_PROMPT
from services.chat.synthesis_agent import SYNTHESIS_SYSTEM_PROMPT
from services.knowledge.qa_service import KNOWLEDGE_QA_SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed_langfuse")

PROMPTS = [
    ("intent-router", INTENT_SYSTEM_PROMPT),
    ("synthesis", SYNTHESIS_SYSTEM_PROMPT),
    ("knowledge-qa", KNOWLEDGE_QA_SYSTEM_PROMPT),
]


def seed_prompts(client) -> None:
    label = _label()
    for name, text in PROMPTS:
        try:
            existing = client.get_prompt(name, label=label, cache_ttl_seconds=0)
            if not getattr(existing, "is_fallback", False) and existing.prompt == text:
                logger.info("prompt %-14s up-to-date (skip)", name)
                continue
        except Exception:
            pass  # not found yet -> create below
        client.create_prompt(
            name=name,
            prompt=text,
            type="text",
            labels=[label],
            commit_message="seed from in-code fallback constant",
        )
        logger.info("prompt %-14s seeded -> label=%s", name, label)


# (name, data_type, kwargs) — annotation schemas for evaluating traces.
SCORE_CONFIGS = [
    ("faithfulness", "NUMERIC",
     dict(min_value=0, max_value=1,
          description="Knowledge-QA answer grounded in retrieved docs (0=hallucinated, 1=fully grounded)")),
    ("answer_relevance", "NUMERIC",
     dict(min_value=0, max_value=1,
          description="Answer addresses the user's question (0=off-topic, 1=fully on-point)")),
    ("intent_correct", "BOOLEAN",
     dict(description="Intent router selected the correct route")),
    ("helpfulness", "CATEGORICAL",
     dict(description="Overall advisory quality",
          categories=[("poor", 0), ("ok", 1), ("good", 2), ("excellent", 3)])),
]


def seed_score_configs(client) -> None:
    from langfuse.api import CreateScoreConfigRequest, ConfigCategory

    existing = {c.name for c in client.api.score_configs.get(limit=100).data}
    for name, data_type, kwargs in SCORE_CONFIGS:
        if name in existing:
            logger.info("score  %-16s exists (skip)", name)
            continue
        cats = kwargs.pop("categories", None)
        if cats is not None:
            kwargs["categories"] = [ConfigCategory(value=v, label=l) for l, v in cats]
        client.api.score_configs.create(
            request=CreateScoreConfigRequest(name=name, data_type=data_type, **kwargs)
        )
        logger.info("score  %-16s created (%s)", name, data_type)


def main() -> None:
    client = get_langfuse()
    if client is None:
        raise SystemExit(
            "Langfuse client is None: set ADVISORY_LANGFUSE_ENABLED=true and "
            "LANGFUSE_PUBLIC_KEY/SECRET_KEY in .env, and make sure the stack is up."
        )
    seed_prompts(client)
    seed_score_configs(client)
    client.flush()
    logger.info("done")


if __name__ == "__main__":
    main()
