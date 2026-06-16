from pydantic import BaseModel, Field

from services.knowledge.models import ScoredChunk


class GoldenChunk(BaseModel):
    """A retrieved chunk frozen into the golden set at curation time. Only the
    fields generation actually reads are required; the rest mirror ScoredChunk."""

    chunk_text: str
    score: float
    school: str
    topic: str | None = None
    source_url: str | None = None

    def to_scored_chunk(self) -> ScoredChunk:
        return ScoredChunk(
            chunk_text=self.chunk_text,
            score=self.score,
            school=self.school,
            topic=self.topic,
            source_url=self.source_url,
        )


class GoldenCase(BaseModel):
    """One eval case. `chunks` is the frozen retrieval substrate; the eval feeds
    them straight into generation for each model under test."""

    id: str
    question: str
    school: str | None = None
    topic: str | None = None
    chunks: list[GoldenChunk]
    # The facts a correct answer must contain (empty for abstain cases).
    expected_answer_points: list[str] = Field(default_factory=list)
    # 1-based indices into `chunks` a faithful answer should cite.
    expected_source_ids: list[int] = Field(default_factory=list)
    # True when the chunks lack the info and the model SHOULD return no answer.
    abstain: bool = False
