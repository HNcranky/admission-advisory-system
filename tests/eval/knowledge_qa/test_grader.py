from eval.knowledge_qa.grader import (
    CaseGrade, abstention_correct, citation_f1, grade_case,
)
from eval.knowledge_qa.models import GoldenCase, GoldenChunk
from services.inference.models import InferenceResult
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


class _FakeJudgeGateway:
    """Returns a canned judge verdict; records the request for assertions."""

    def __init__(self, faithful, correct):
        self._verdict = {"faithful": faithful, "correct": correct}
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return InferenceResult(
            agent_name="qa_eval_judge", model="gemini-2.5-flash", provider="fake",
            content="{}", parsed_data=self._verdict,
        )


def _golden(abstain=False, expected_ids=(1,)):
    return GoldenCase(
        id="c1", question="Chỉ tiêu?", school="hust", topic="quota",
        chunks=_chunks(), expected_answer_points=["300"],
        expected_source_ids=list(expected_ids), abstain=abstain,
    )


def test_grade_case_answered_uses_judge():
    gateway = _FakeJudgeGateway(faithful=True, correct=True)
    result = _answer_citing(["A: chỉ tiêu 300."])

    grade = grade_case(_golden(), result, model="gemini-2.5-flash-lite", gateway=gateway)

    assert grade.model == "gemini-2.5-flash-lite"
    assert grade.answered is True
    assert grade.abstention_correct is True
    assert grade.faithful is True and grade.correct is True
    assert grade.citation_f1 == 1.0
    assert len(gateway.requests) == 1


def test_grade_case_abstain_skips_judge():
    gateway = _FakeJudgeGateway(faithful=True, correct=True)
    empty = KnowledgeQAResult(has_data=False, answer="", confidence=0.2)

    grade = grade_case(_golden(abstain=True, expected_ids=()), empty,
                       model="gemini-2.5-flash", gateway=gateway)

    assert grade.abstention_correct is True
    assert grade.faithful is None and grade.correct is None
    assert gateway.requests == []  # judge never called on abstain cases


def test_grade_case_non_abstain_declined_is_incorrect_no_judge():
    gateway = _FakeJudgeGateway(faithful=True, correct=True)
    empty = KnowledgeQAResult(has_data=False, answer="", confidence=0.2)

    grade = grade_case(_golden(), empty, model="gemini-2.5-flash", gateway=gateway)

    assert grade.answered is False
    assert grade.abstention_correct is False
    assert grade.correct is False
    assert grade.citation_f1 == 0.0
    assert gateway.requests == []  # no answer to judge
