"""The knowledge taxonomy must be a single source of truth: ingestion seed
validation and the chat intent router both bind to the same canonical set, so a
topic can never diverge between ingest time and query time."""

from ingestion.knowledge.registry.models import KNOWLEDGE_TOPICS as INGEST_TOPICS
from services.chat.intent_router import KNOWLEDGE_TOPICS as ROUTER_TOPICS
from services.knowledge.taxonomy import (
    KNOWLEDGE_SCHOOLS,
    KNOWLEDGE_TOPICS,
    SCHOOL_SYNONYMS,
    TOPIC_SYNONYMS,
    normalize_school,
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


# --- school normalization (single source of truth for the corpus codes) ---

def test_canonical_schools_are_the_four_corpus_codes():
    assert KNOWLEDGE_SCHOOLS == {"HUST", "NEU", "VNU-UET", "MOET"}


def test_school_synonyms_all_resolve_into_the_canonical_set():
    for canonical in SCHOOL_SYNONYMS.values():
        assert canonical in KNOWLEDGE_SCHOOLS


def test_normalize_school_maps_full_vietnamese_name_to_code():
    # The exact bug: the intent LLM emits the spelled-out school name instead of
    # the corpus code, so retrieval (WHERE school = %s) matches zero chunks.
    assert normalize_school("đại học bách khoa hà nội") == "HUST"
    assert normalize_school("Đại học Bách khoa Hà Nội") == "HUST"
    assert normalize_school("bách khoa") == "HUST"
    assert normalize_school("đại học kinh tế quốc dân") == "NEU"
    assert normalize_school("đại học công nghệ") == "VNU-UET"


def test_normalize_school_canonical_codes_passthrough_case_insensitive():
    assert normalize_school("HUST") == "HUST"
    assert normalize_school("hust") == "HUST"
    assert normalize_school("vnu-uet") == "VNU-UET"


def test_normalize_school_unknown_passes_through_and_none_stays_none():
    # Unknown school must NOT be dropped to None — that would silently change the
    # route. Keep the raw value so retrieval misses gracefully instead.
    assert normalize_school("Đại học FPT") == "Đại học FPT"
    assert normalize_school(None) is None
