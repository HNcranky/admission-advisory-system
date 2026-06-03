from services.chat.hybrid_models import AdvisoryBlock, KnowledgeBlock
from services.chat.synthesis_agent import SynthesisAgent


class FailingGateway:
    """Forces the deterministic fallback path."""
    def is_available(self):
        return True

    def run(self, request):
        raise RuntimeError("synthesis llm down")


def _agent_with_failing_gateway():
    return SynthesisAgent(gateway=FailingGateway())


def test_fallback_concatenation_has_both_sections():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=True, answer="Bạn có khả năng đậu UET ngành CNTT.")
    knowledge = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=True, answer="Học phí ~35 triệu/năm.")]
    out = agent.synthesize(advisory, knowledge, "so sánh")
    assert "Theo dữ liệu tuyển sinh" in out
    assert "Thông tin trường" in out
    assert "khả năng đậu UET" in out
    assert "35 triệu" in out


def test_fallback_states_missing_advisory():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=False)
    knowledge = [KnowledgeBlock(school="HUST", topic="tuition", has_data=True, answer="Học phí HUST ~24 triệu.")]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "Thông tin trường" in out
    assert "24 triệu" in out
    assert "chưa có dữ liệu" in out.lower()


def test_fallback_states_missing_knowledge():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=True, answer="Tư vấn: nên ưu tiên UET.")
    knowledge = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=False)]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "nên ưu tiên UET" in out
    assert "chưa có dữ liệu" in out.lower()


def test_merged_sources_are_deduped_and_appended():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=True, answer="A", sources=["https://x", "https://y"])
    knowledge = [
        KnowledgeBlock(school="U", topic="tuition", has_data=True, answer="B", sources=["https://y", "https://z"]),
    ]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "Nguồn:" in out
    # https://y appears once despite being in both blocks
    assert out.count("https://y") == 1
    assert "https://x" in out and "https://z" in out


def test_no_sources_block_when_no_urls():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=True, answer="A")
    knowledge = [KnowledgeBlock(school="U", topic="tuition", has_data=True, answer="B")]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "Nguồn:" not in out


from services.inference.models import InferenceResult


class RecordingGateway:
    def __init__(self, content="**Theo dữ liệu tuyển sinh**\n...\n**Thông tin trường**\n..."):
        self._content = content
        self.last_request = None

    def is_available(self):
        return True

    def run(self, request):
        self.last_request = request
        return InferenceResult(
            agent_name=request.agent_name, model="m", provider="p", content=self._content,
        )


def test_llm_path_used_when_gateway_returns_content():
    gw = RecordingGateway(content="Câu trả lời tổng hợp từ LLM.")
    agent = SynthesisAgent(gateway=gw)
    advisory = AdvisoryBlock(has_data=True, answer="adv", sources=["https://x"])
    knowledge = [KnowledgeBlock(school="U", topic="tuition", has_data=True, answer="kno", sources=["https://y"])]
    out = agent.synthesize(advisory, knowledge, "so sánh U")
    assert "Câu trả lời tổng hợp từ LLM." in out
    assert gw.last_request.agent_name == "synthesis_agent"
    assert gw.last_request.output_mode == "free_text"
    # sources still appended deterministically (not trusted to the LLM)
    assert "https://x" in out and "https://y" in out


def test_prompt_carries_grounding_rule_and_both_blocks():
    gw = RecordingGateway()
    agent = SynthesisAgent(gateway=gw)
    advisory = AdvisoryBlock(has_data=True, answer="ADV_TEXT")
    knowledge = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=True, answer="KNO_TEXT")]
    agent.synthesize(advisory, knowledge, "câu hỏi gốc")
    sys = gw.last_request.system_prompt
    usr = gw.last_request.user_prompt
    assert "không thêm" in sys.lower() or "tuyệt đối không" in sys.lower()
    assert "ADV_TEXT" in usr
    assert "KNO_TEXT" in usr
    assert "VNU-UET" in usr
    assert "câu hỏi gốc" in usr


def test_empty_llm_content_falls_back_to_concatenation():
    gw = RecordingGateway(content="   ")  # whitespace only
    agent = SynthesisAgent(gateway=gw)
    advisory = AdvisoryBlock(has_data=True, answer="adv only")
    knowledge = [KnowledgeBlock(school="U", topic="tuition", has_data=False)]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "adv only" in out
    assert "Theo dữ liệu tuyển sinh" in out
