from services.chat.intent_router import IntentResult
from services.chat.knowledge_fanout import run_knowledge_fanout, format_knowledge_blocks
from services.knowledge.models import Citation, KnowledgeQAResult


class FakeKnowledgeQA:
    def __init__(self, by_school=None, raise_for=None):
        # by_school: {school: KnowledgeQAResult}; default → no-data
        self._by_school = by_school or {}
        self._raise_for = raise_for or set()
        self.calls = []

    def answer(self, question, school, topic, conversation_context=""):
        self.calls.append({"question": question, "school": school, "topic": topic})
        if school in self._raise_for:
            raise RuntimeError("boom")
        return self._by_school.get(school, KnowledgeQAResult(has_data=False, confidence=0.0))


def test_fanout_calls_once_per_school_topic_pair():
    qa = FakeKnowledgeQA()
    intent = IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"])
    blocks = run_knowledge_fanout(qa, intent, "so sánh học phí", school_fallback=None)
    assert len(qa.calls) == 2
    assert {c["school"] for c in qa.calls} == {"VNU-UET", "HUST"}
    assert all(c["topic"] == "tuition" for c in qa.calls)
    assert len(blocks) == 2


def test_fanout_maps_has_data_result_into_block_with_sources():
    qa = FakeKnowledgeQA(by_school={"VNU-UET": KnowledgeQAResult(
        has_data=True, answer="35 triệu/năm",
        citations=[Citation(source_url="https://uet/hp", chunk_text="...")], confidence=0.9,
    )})
    intent = IntentResult(route="HYBRID", schools=["VNU-UET"], topics=["tuition"])
    blocks = run_knowledge_fanout(qa, intent, "học phí", school_fallback=None)
    assert blocks[0].has_data is True
    assert blocks[0].answer == "35 triệu/năm"
    assert blocks[0].school == "VNU-UET"
    assert blocks[0].sources == ["https://uet/hp"]


def test_fanout_failed_call_becomes_no_data_block_others_survive():
    qa = FakeKnowledgeQA(
        by_school={"HUST": KnowledgeQAResult(has_data=True, answer="24 triệu", citations=[], confidence=0.8)},
        raise_for={"VNU-UET"},
    )
    intent = IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"])
    blocks = run_knowledge_fanout(qa, intent, "q", school_fallback=None)
    by_school = {b.school: b for b in blocks}
    assert by_school["VNU-UET"].has_data is False
    assert by_school["HUST"].has_data is True


def test_fanout_falls_back_to_singular_then_school_fallback():
    qa = FakeKnowledgeQA()
    # no schools/topics lists, singular school present
    intent = IntentResult(route="HYBRID", school="NEU", topic="tuition")
    blocks = run_knowledge_fanout(qa, intent, "q", school_fallback="IGNORED")
    assert qa.calls[0]["school"] == "NEU"
    # no schools/topics/singular school → use school_fallback
    qa2 = FakeKnowledgeQA()
    intent2 = IntentResult(route="HYBRID", topics=["tuition"])
    run_knowledge_fanout(qa2, intent2, "q", school_fallback="VNU-UET")
    assert qa2.calls[0]["school"] == "VNU-UET"


def test_format_knowledge_blocks_renders_data_and_fallback():
    from services.chat.hybrid_models import KnowledgeBlock
    has = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=True, answer="35 triệu",
                          sources=["https://uet/hp"])]
    out = format_knowledge_blocks(has)
    assert "35 triệu" in out
    assert "https://uet/hp" in out

    empty = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=False)]
    out2 = format_knowledge_blocks(empty)
    assert "chưa có dữ liệu" in out2.lower()
    assert "liên hệ" in out2.lower()
