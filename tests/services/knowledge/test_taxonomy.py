"""The knowledge taxonomy must be a single source of truth: ingestion seed
validation and the chat intent router both bind to the same canonical set, so a
topic can never diverge between ingest time and query time."""

from ingestion.knowledge.registry.models import KNOWLEDGE_TOPICS as INGEST_TOPICS
from services.chat.intent_router import KNOWLEDGE_TOPICS as ROUTER_TOPICS
from services.knowledge.taxonomy import (
    KNOWLEDGE_TOPICS,
    TOPIC_SYNONYMS,
    normalize_topic,
)


def test_canonical_set_is_the_six_topics():
    assert KNOWLEDGE_TOPICS == {
        "tuition", "curriculum", "scholarship", "dormitory",
        "admission_policy", "program_overview",
    }


def test_both_sides_bind_the_same_canonical_object():
    assert INGEST_TOPICS is KNOWLEDGE_TOPICS
    assert ROUTER_TOPICS is KNOWLEDGE_TOPICS


def test_career_is_a_synonym_not_a_canonical_topic():
    assert "career" not in KNOWLEDGE_TOPICS
    assert normalize_topic("career") == "program_overview"


def test_synonyms_all_resolve_into_the_canonical_set():
    for canonical in TOPIC_SYNONYMS.values():
        assert canonical in KNOWLEDGE_TOPICS


def test_normalize_passthrough_and_unknown():
    assert normalize_topic("tuition") == "tuition"
    assert normalize_topic("admission_methods") == "admission_policy"
    assert normalize_topic("nonsense") is None
    assert normalize_topic(None) is None
