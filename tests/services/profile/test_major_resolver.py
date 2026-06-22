import pytest

from services.profile.major_resolver import resolve_majors


class ExplodingRepo:
    def vector_search_programs(self, embedding, limit=8):
        raise AssertionError("Tier2 không được gọi khi Tier1 đã khớp")


class ExplodingEmbedder:
    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        raise AssertionError("embedder không được gọi khi Tier1 đã khớp")


def test_tier1_alias_match_short_circuits():
    # "kỹ thuật phần mềm" là alias của software_engineering trong programs.json.
    result = resolve_majors("em muốn học kỹ thuật phần mềm",
                            repository=ExplodingRepo(), embedder=ExplodingEmbedder())
    assert "software_engineering" in result


from services.profile.major_catalog_repository import ProgramCandidate


class FakeEmbedderOK:
    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        return [[0.2] * 768 for _ in texts]


class FakeRepo:
    def __init__(self, candidates):
        self._candidates = candidates

    def vector_search_programs(self, embedding, limit=8):
        return self._candidates[:limit]


class FailingEmbedder:
    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        raise RuntimeError("embedding service down")


def test_tier2_confident_single_strong_candidate_returns_it():
    # Không khớp alias → vào Tier2. 1 ứng viên mạnh trên high_threshold.
    repo = FakeRepo([ProgramCandidate("data_science", "Khoa học Dữ liệu", 0.82)])
    result = resolve_majors("em thích phân tích dữ liệu lớn",
                            repository=repo, embedder=FakeEmbedderOK())
    assert result == ["data_science"]


def test_tier2_below_threshold_returns_empty():
    repo = FakeRepo([ProgramCandidate("law", "Luật", 0.40)])
    result = resolve_majors("câu nói mơ hồ", active_slot="preferred_majors",
                            repository=repo, embedder=FakeEmbedderOK())
    assert result == []


def test_tier2_embedder_failure_degrades_to_empty():
    repo = FakeRepo([ProgramCandidate("x", "X", 0.9)])
    result = resolve_majors("bất kỳ", active_slot="preferred_majors",
                            repository=repo, embedder=FailingEmbedder())
    assert result == []


from services.inference.models import InferenceError, InferenceResult


class FakeGatewayPick:
    def __init__(self, program_ids):
        self._ids = program_ids
        self.calls = 0

    def run(self, request):
        self.calls += 1
        return InferenceResult(
            agent_name=request.agent_name, model="fake", provider="fake",
            content="{}", parsed_data={"program_ids": self._ids},
        )


class FailingGateway:
    def run(self, request):
        raise InferenceError("llm down")


def _ambiguous_repo():
    # hai ứng viên sát điểm (< margin) → Tier3.
    return FakeRepo([
        ProgramCandidate("computer_science", "Khoa học Máy tính", 0.66),
        ProgramCandidate("software_engineering", "Kỹ thuật Phần mềm", 0.63),
    ])


def test_tier3_llm_picks_subset_from_shortlist():
    gw = FakeGatewayPick(["software_engineering"])
    result = resolve_majors("em thích tạo sản phẩm phần mềm",
                            repository=_ambiguous_repo(), embedder=FakeEmbedderOK(), gateway=gw)
    assert result == ["software_engineering"]
    assert gw.calls == 1


def test_tier3_filters_out_ids_not_in_shortlist():
    gw = FakeGatewayPick(["software_engineering", "hallucinated_id"])
    result = resolve_majors("...", active_slot="preferred_majors", repository=_ambiguous_repo(),
                            embedder=FakeEmbedderOK(), gateway=gw)
    assert result == ["software_engineering"]  # id ngoài shortlist bị loại


def test_tier3_llm_failure_falls_back_to_top_embedding():
    result = resolve_majors("...", active_slot="preferred_majors", repository=_ambiguous_repo(),
                            embedder=FakeEmbedderOK(), gateway=FailingGateway())
    assert result == ["computer_science"]  # top embedding


def test_tier3_not_called_when_confident():
    gw = FakeGatewayPick(["should_not_be_used"])
    repo = FakeRepo([ProgramCandidate("data_science", "KHDL", 0.85)])
    result = resolve_majors("phân tích dữ liệu", active_slot="preferred_majors", repository=repo,
                            embedder=FakeEmbedderOK(), gateway=gw)
    assert result == ["data_science"]
    assert gw.calls == 0  # confident → skip LLM (minimize_num_calls)


class SpyEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        self.calls += 1
        return [[0.2] * 768 for _ in texts]


def test_info_question_skips_tier2_when_no_major_intent():
    # Câu hỏi thông tin (học phí) KHÔNG có ý định ngành → KHÔNG chạy embedding,
    # không nhiễm preferred_majors bằng ứng viên tiếp tuyến.
    spy = SpyEmbedder()
    repo = FakeRepo([ProgramCandidate("electronics_telecom", "Điện tử - Viễn thông", 0.72)])
    result = resolve_majors("tôi muốn tìm hiểu thông tin học phí của UET",
                            repository=repo, embedder=spy)
    assert result == []
    assert spy.calls == 0  # gated trước Tier2


def test_interest_cue_runs_tier2():
    # Có cue sở thích ("thích") → vào Tier2 bình thường.
    spy = SpyEmbedder()
    repo = FakeRepo([ProgramCandidate("data_science", "Khoa học Dữ liệu", 0.85)])
    result = resolve_majors("em thích phân tích dữ liệu lớn",
                            repository=repo, embedder=spy)
    assert result == ["data_science"]
    assert spy.calls == 1


def test_answering_major_slot_bypasses_intent_gate():
    # User đang trả lời đúng slot ngành → bỏ qua cổng intent dù text không có cue.
    spy = SpyEmbedder()
    repo = FakeRepo([ProgramCandidate("data_science", "Khoa học Dữ liệu", 0.85)])
    result = resolve_majors("phân tích số liệu", repository=repo, embedder=spy,
                            active_slot="preferred_majors")
    assert result == ["data_science"]
    assert spy.calls == 1
