"""One-off curation driver (NOT in the test suite). Requires the Docker DB and a
Gemini key. Freezes real retrieval per seed and LLM-drafts expected grounding,
emitting a candidate golden set for HUMAN review before it becomes golden_set.json.
Run: python -m eval.knowledge_qa.curate
"""
import json
from pathlib import Path

from eval.knowledge_qa.gateways import build_judge_gateway
from services.inference.models import InferenceError, InferenceRequest
from services.knowledge.qa_service import KnowledgeQAService

SEEDS_PATH = Path(__file__).resolve().parent / "curation_seeds.json"
CANDIDATE_PATH = Path(__file__).resolve().parent / "golden_set.candidate.json"

DRAFT_SYSTEM_PROMPT = """
Bạn giúp tạo dữ liệu đánh giá. Cho một câu hỏi và các đoạn tham khảo đánh số,
hãy nêu các ý đúng mà một câu trả lời tốt phải có, và số thứ tự các đoạn chứa
thông tin đó. Trả về JSON: {"expected_answer_points": [...], "expected_source_ids": [...]}.
Nếu các đoạn KHÔNG đủ thông tin để trả lời, trả về cả hai mảng rỗng.
""".strip()


def _draft_grounding(question, chunks, gateway):
    numbered = "\n".join(f"[{i}] {c.chunk_text}" for i, c in enumerate(chunks, start=1))
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="qa_eval_judge", task_type="qa_eval_curate",
                system_prompt=DRAFT_SYSTEM_PROMPT,
                user_prompt=f"Câu hỏi: {question}\n\nCác đoạn:\n{numbered}",
                output_mode="json", temperature=0.0,
            )
        )
    except InferenceError:
        return {"expected_answer_points": [], "expected_source_ids": []}
    data = result.parsed_data or {}
    return {
        "expected_answer_points": data.get("expected_answer_points", []) or [],
        "expected_source_ids": data.get("expected_source_ids", []) or [],
    }


def _freeze_chunk(chunk):
    return {
        "chunk_text": chunk.chunk_text,
        "score": round(float(chunk.score), 4),
        "school": chunk.school,
        "topic": chunk.topic,
        "source_url": chunk.source_url,
    }


def main():
    seeds = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))["seeds"]
    service = KnowledgeQAService()          # real DB + embedder
    gateway = build_judge_gateway()
    cases = []
    for n, seed in enumerate(seeds, start=1):
        chunks = service.retrieve(seed["question"], seed.get("school"), seed.get("topic"))
        frozen = [_freeze_chunk(c) for c in chunks]
        if seed.get("abstain"):
            grounding = {"expected_answer_points": [], "expected_source_ids": []}
        else:
            grounding = _draft_grounding(seed["question"], chunks, gateway)
        cases.append({
            "id": f"seed-{n:02d}",
            "question": seed["question"],
            "school": seed.get("school"),
            "topic": seed.get("topic"),
            "chunks": frozen,
            "abstain": bool(seed.get("abstain")),
            **grounding,
        })
    CANDIDATE_PATH.write_text(
        json.dumps({"version": 1, "cases": cases}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} candidate cases to {CANDIDATE_PATH}")
    print("REVIEW BY HAND, then move to golden_set.json.")


if __name__ == "__main__":
    main()
