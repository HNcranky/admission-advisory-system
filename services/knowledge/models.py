from pydantic import BaseModel, Field


class KnowledgeChunk(BaseModel):
    school: str
    topic: str | None = None
    program: str | None = None
    year: int | None = None
    document_type: str | None = None
    chunk_text: str
    content_hash: str | None = None
    embedding: list[float] | None = None
    source_url: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    knowledge_document_id: int | None = None


class ScoredChunk(KnowledgeChunk):
    score: float


class KnowledgeDocument(BaseModel):
    school: str
    document_type: str
    source_url: str
    content_hash: str | None = None
    raw_text: str | None = None
    id: int | None = None


class Citation(BaseModel):
    source_url: str
    chunk_text: str


class KnowledgeQAResult(BaseModel):
    has_data: bool
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
