from typing import List, Optional

from pydantic import BaseModel, Field


class AdvisoryBlock(BaseModel):
    """The advisory branch result, normalized for synthesis."""
    has_data: bool = False
    answer: Optional[str] = None
    sources: List[str] = Field(default_factory=list)


class KnowledgeBlock(BaseModel):
    """One (school, topic) knowledge result, normalized for synthesis."""
    school: Optional[str] = None
    topic: Optional[str] = None
    has_data: bool = False
    answer: Optional[str] = None
    sources: List[str] = Field(default_factory=list)
