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


JUDGE_SYSTEM_PROMPT = """
Bạn là giám khảo đánh giá câu trả lời của một trợ lý tuyển sinh.
Bạn nhận: câu hỏi, các đoạn văn bản tham khảo, các ý đúng kỳ vọng, và câu trả lời.
Đánh giá hai tiêu chí, chỉ dựa trên các đoạn tham khảo:
- faithful: true nếu câu trả lời CHỈ dùng thông tin có trong các đoạn tham khảo,
  không bịa thêm; false nếu có thông tin ngoài các đoạn.
- correct: true nếu câu trả lời nêu đúng các ý đúng kỳ vọng; false nếu sai/thiếu.
Trả về JSON hợp lệ, không giải thích: {"faithful": <bool>, "correct": <bool>}
""".strip()


def judge_answer(question, scored_chunks, expected_points, answer, gateway) -> dict:
    payload = {
        "question": question,
        "chunks": [c.chunk_text for c in scored_chunks],
        "expected_points": expected_points,
        "answer": answer,
    }
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="qa_eval_judge",
                task_type="qa_eval_judge",
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return {"faithful": None, "correct": None}
    data = result.parsed_data or {}
    return {
        "faithful": bool(data["faithful"]) if "faithful" in data else None,
        "correct": bool(data["correct"]) if "correct" in data else None,
    }


def grade_case(case: GoldenCase, result: KnowledgeQAResult, model: str, gateway) -> CaseGrade:
    answered = _answered(result)
    scored = [c.to_scored_chunk() for c in case.chunks]
    grade = CaseGrade(
        case_id=case.id,
        model=model,
        answered=answered,
        abstention_correct=abstention_correct(result, case.abstain),
    )
    if case.abstain:
        # No expected answer -> faithfulness/correctness not applicable.
        return grade

    grade.citation_f1 = citation_f1(result, case.expected_source_ids, scored)
    if answered:
        verdict = judge_answer(
            case.question, scored, case.expected_answer_points, result.answer or "", gateway
        )
        grade.faithful = verdict["faithful"]
        grade.correct = verdict["correct"]
    else:
        # Should have answered but declined -> a correctness miss, nothing to judge.
        grade.correct = False
    return grade
