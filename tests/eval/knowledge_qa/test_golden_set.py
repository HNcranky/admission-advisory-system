from pathlib import Path

from eval.knowledge_qa.golden_set import DEFAULT_GOLDEN_PATH, load_golden_set
from eval.knowledge_qa.models import GoldenCase


def test_loads_seed_fixture():
    cases = load_golden_set()

    assert len(cases) >= 2
    assert all(isinstance(c, GoldenCase) for c in cases)

    answerable = next(c for c in cases if c.id == "hust-quota-cntt-2026")
    assert answerable.abstain is False
    assert answerable.expected_source_ids == [1]
    assert answerable.chunks[0].to_scored_chunk().score == 0.83

    abstain = next(c for c in cases if c.id == "hust-scholarship-abstain")
    assert abstain.abstain is True
    assert abstain.expected_answer_points == []


def test_default_path_points_at_packaged_fixture():
    assert DEFAULT_GOLDEN_PATH == Path(__file__).resolve().parents[3] / "eval" / "knowledge_qa" / "golden_set.json"
