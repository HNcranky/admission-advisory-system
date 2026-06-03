from pydantic import BaseModel, field_validator

KNOWLEDGE_TOPICS = {
    "tuition",
    "curriculum",
    "scholarship",
    "dormitory",
    "career",
    "admission_policy",
    "program_overview",
}

KNOWLEDGE_DOCUMENT_TYPES = {
    "tuition_page",
    "curriculum_pdf",
    "scholarship_policy",
    "faq",
    "handbook",
    "program_overview_page",
    "career_page",
    "dormitory_page",
}


class KnowledgeSource(BaseModel):
    school: str
    source_url: str
    document_type: str
    topic: str
    fetch_strategy: str = "http"
    program: str | None = None
    year: int | None = None
    active: bool = True

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
