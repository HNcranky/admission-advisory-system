import pytest
from pydantic import ValidationError

from ingestion.knowledge.registry.models import (
    KnowledgeSource,
    KNOWLEDGE_TOPICS,
    KNOWLEDGE_DOCUMENT_TYPES,
)


def test_taxonomy_sets_match_spec():
    assert KNOWLEDGE_TOPICS == {
        "tuition", "curriculum", "scholarship", "dormitory",
        "career", "admission_policy", "program_overview",
    }
    assert "tuition_page" in KNOWLEDGE_DOCUMENT_TYPES
    assert "curriculum_pdf" in KNOWLEDGE_DOCUMENT_TYPES


def test_valid_source_parses_with_defaults():
    s = KnowledgeSource(
        school="HUST",
        source_url="https://example.edu/tuition",
        document_type="tuition_page",
        topic="tuition",
    )
    assert s.fetch_strategy == "http"
    assert s.active is True
    assert s.program is None
    assert s.year is None


def test_invalid_topic_rejected():
    with pytest.raises(ValidationError):
        KnowledgeSource(
            school="HUST",
            source_url="https://example.edu/x",
            document_type="tuition_page",
            topic="weather",          # not in taxonomy
        )


def test_invalid_document_type_rejected():
    with pytest.raises(ValidationError):
        KnowledgeSource(
            school="HUST",
            source_url="https://example.edu/x",
            document_type="random_page",   # not in taxonomy
            topic="tuition",
        )
