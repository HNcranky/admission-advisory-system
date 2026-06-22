from pydantic import BaseModel, field_validator

# Single source of truth shared with the chat intent router. Seeds must use a
# canonical topic (synonyms like "career" are a query-side concern only).
from services.knowledge.taxonomy import KNOWLEDGE_TOPICS

KNOWLEDGE_DOCUMENT_TYPES = {
    "tuition_page",
    "curriculum_pdf",
    "scholarship_policy",
    "faq",
    "handbook",
    "program_overview_page",
    "career_page",
    "dormitory_page",
    "exam_guide",
}


class KnowledgeSource(BaseModel):
    school: str
    source_url: str
    document_type: str
    topic: str
    fetch_strategy: str = "http"
    chunk_strategy: str = "size"  # "size" (default) | "whole_page"
    program: str | None = None
    year: int | None = None
    active: bool = True
    selector: str | None = None

    @field_validator("topic")
    @classmethod
    def _topic_in_taxonomy(cls, v: str) -> str:
        if v not in KNOWLEDGE_TOPICS:
            raise ValueError(
                f"topic {v!r} not in taxonomy {sorted(KNOWLEDGE_TOPICS)}"
            )
        return v

    @field_validator("document_type")
    @classmethod
    def _doctype_in_taxonomy(cls, v: str) -> str:
        if v not in KNOWLEDGE_DOCUMENT_TYPES:
            raise ValueError(
                f"document_type {v!r} not in taxonomy "
                f"{sorted(KNOWLEDGE_DOCUMENT_TYPES)}"
            )
        return v
