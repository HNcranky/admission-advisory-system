from eval.knowledge_qa.grader import (
    CaseGrade, abstention_correct, citation_f1,
)
from eval.knowledge_qa.models import GoldenCase, GoldenChunk
from services.knowledge.models import Citation, KnowledgeQAResult


def _chunks():
    return [
        GoldenChunk(chunk_text="A: chỉ tiêu 300.", score=0.8, school="hust"),
        GoldenChunk(chunk_text="B: học phí 25 triệu.", score=0.6, school="hust"),
    ]


def _answer_citing(idx_texts):
    return KnowledgeQAResult(
        has_data=True,
        answer="Chỉ tiêu là 300.",
        citations=[Citation(source_url="", chunk_text=t) for t in idx_texts],
        confidence=0.8,
    )


def test_abstention_correct():
    answered = KnowledgeQAResult(has_data=True, answer="có 300", confidence=0.8)
    empty = KnowledgeQAResult(has_data=False, answer="", confidence=0.3)

    assert abstention_correct(answered, abstain=False) is True
    assert abstention_correct(answered, abstain=True) is False
    assert abstention_correct(empty, abstain=True) is True
    assert abstention_correct(empty, abstain=False) is False


def test_citation_f1_perfect_and_miss():
    chunks = [c.to_scored_chunk() for c in _chunks()]

    perfect = _answer_citing(["A: chỉ tiêu 300."])
    assert citation_f1(perfect, expected_source_ids=[1], chunks=chunks) == 1.0

    wrong = _answer_citing(["B: học phí 25 triệu."])
    assert citation_f1(wrong, expected_source_ids=[1], chunks=chunks) == 0.0

    none_expected_none_cited = KnowledgeQAResult(has_data=False, answer="", confidence=0.2)
    assert citation_f1(none_expected_none_cited, expected_source_ids=[], chunks=chunks) == 1.0
