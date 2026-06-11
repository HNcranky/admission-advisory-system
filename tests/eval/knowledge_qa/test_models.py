from eval.knowledge_qa.models import GoldenCase, GoldenChunk
from services.knowledge.models import ScoredChunk


def test_golden_chunk_converts_to_scored_chunk():
    gc = GoldenChunk(
        chunk_text="Chỉ tiêu ngành CNTT năm 2026 là 200.",
        score=0.81,
        school="hust",
        topic="quota",
        source_url="https://hust.edu.vn/ts2026",
    )

    scored = gc.to_scored_chunk()

    assert isinstance(scored, ScoredChunk)
    assert scored.score == 0.81
    assert scored.chunk_text.startswith("Chỉ tiêu")
    assert scored.school == "hust"
    assert scored.source_url == "https://hust.edu.vn/ts2026"


def test_golden_case_defaults_and_abstain():
    case = GoldenCase(
        id="hust-quota-1",
        question="Chỉ tiêu ngành CNTT?",
        school="hust",
        topic="quota",
        chunks=[GoldenChunk(chunk_text="...", score=0.4, school="hust")],
        abstain=True,
    )

    assert case.expected_answer_points == []
    assert case.expected_source_ids == []
    assert case.abstain is True
