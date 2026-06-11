import json

from pydantic import BaseModel

from eval.knowledge_qa.models import GoldenCase
from services.inference.models import InferenceError, InferenceRequest
from services.knowledge.models import KnowledgeQAResult


class CaseGrade(BaseModel):
    case_id: str
    model: str
    answered: bool
    abstention_correct: bool
    # None on abstain cases (no expected answer to judge) or judge failure.
    faithful: bool | None = None
    correct: bool | None = None
    citation_f1: float | None = None


def _answered(result: KnowledgeQAResult) -> bool:
    return bool(result.has_data and (result.answer or "").strip())


def abstention_correct(result: KnowledgeQAResult, abstain: bool) -> bool:
    """Abstain cases are correct iff the model produced no answer; answerable
    cases are correct iff it produced one."""
    return (not _answered(result)) if abstain else _answered(result)


def _cited_indices(result: KnowledgeQAResult, chunks) -> set:
    """Map each citation back to its 1-based chunk index by exact text match."""
    idx = set()
    for cit in result.citations:
        for i, ch in enumerate(chunks, start=1):
            if ch.chunk_text == cit.chunk_text:
                idx.add(i)
    return idx


def citation_f1(result: KnowledgeQAResult, expected_source_ids, chunks) -> float:
    expected = set(expected_source_ids)
    cited = _cited_indices(result, chunks)
    if not expected and not cited:
        return 1.0
    if not expected or not cited:
        return 0.0
    tp = len(expected & cited)
    if tp == 0:
        return 0.0
    precision = tp / len(cited)
    recall = tp / len(expected)
    return 2 * precision * recall / (precision + recall)
