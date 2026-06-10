import threading

from services.chat.intent_router import IntentResult
from services.chat.knowledge_fanout import run_knowledge_fanout, format_knowledge_blocks
from services.knowledge.models import Citation, KnowledgeQAResult


class FakeKnowledgeQA:
    def __init__(self, by_school=None, raise_for=None):
        # by_school: {school: KnowledgeQAResult}; default → no-data
        self._by_school = by_school or {}
        self._raise_for = raise_for or set()
        self.calls = []

    def answer(self, question, school, topic, conversation_context="", query_vector=None, national=None):
        self.calls.append({"question": question, "school": school, "topic": topic})
        if school in self._raise_for:
            raise RuntimeError("boom")
        return self._by_school.get(school, KnowledgeQAResult(has_data=False, confidence=0.0))


class _EmbedCountingQA(FakeKnowledgeQA):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.embed_calls = 0
        self.vectors_seen = []

    def embed_query(self, question):
        self.embed_calls += 1
        return [0.5, 0.5]

    def answer(self, question, school, topic, conversation_context="", query_vector=None, national=None):
        self.vectors_seen.append(query_vector)
        return super().answer(question, school, topic, conversation_context)


class _NationalCountingQA(FakeKnowledgeQA):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.national_calls = []

    def embed_query(self, question):
        return [0.5]

    def national_chunks(self, query_vector, topic):
        self.national_calls.append(topic)
        return []

    def answer(self, question, school, topic, conversation_context="", query_vector=None, national=None):
        return super().answer(question, school, topic, conversation_context)


class _PrevUserEmbedQA(FakeKnowledgeQA):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.embedded_texts = []

    def embed_query(self, question):
        self.embedded_texts.append(question)
        return [0.5]

    def national_chunks(self, query_vector, topic):
        return []


def test_fanout_prepends_prev_user_to_embedded_query():
    qa = _PrevUserEmbedQA()
    intent = IntentResult(route="HYBRID", school="HUST", topic="tuition")
    run_knowledge_fanout(
        qa, intent, "còn học phí thì sao",
        conversation_context="Trợ lý: ...", prev_user="HUST xét tuyển thế nào",
    )
    assert qa.embedded_texts == ["HUST xét tuyển thế nào\ncòn học phí thì sao"]


def test_fanout_standalone_question_embeds_verbatim():
    qa = _PrevUserEmbedQA()
    intent = IntentResult(route="HYBRID", school="HUST", topic="tuition")
    run_knowledge_fanout(
        qa, intent, "học phí HUST là bao nhiêu", prev_user="ngành CNTT thế nào",
    )
    assert qa.embedded_texts == ["học phí HUST là bao nhiêu"]  # has noun → not elliptical


def test_fanout_computes_national_once_per_topic():
    qa = _NationalCountingQA()
    intent = IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"])
    run_knowledge_fanout(qa, intent, "so sánh học phí", school_fallback=None)
    # 2 schools × 1 topic = 2 answer() calls, but national computed once for "tuition"
    assert qa.national_calls == ["tuition"]


def test_fanout_embeds_query_once_and_shares_vector():
    qa = _EmbedCountingQA()
    intent = IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"])
    run_knowledge_fanout(qa, intent, "so sánh học phí", school_fallback=None)
    assert qa.embed_calls == 1                       # one embed for the whole fan-out
    assert len(qa.vectors_seen) == 2                 # but both tasks ran
    assert all(v == [0.5, 0.5] for v in qa.vectors_seen)


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


class _CtxRecordingQA:
    def __init__(self):
        self.last_ctx = None

    def answer(self, question, school, topic, conversation_context="", query_vector=None, national=None):
        self.last_ctx = conversation_context
        return KnowledgeQAResult(has_data=False, confidence=0.0)


def test_run_knowledge_fanout_forwards_conversation_context():
    qa = _CtxRecordingQA()
    intent = IntentResult(route="HYBRID", topic="tuition", school="VNU-UET")
    run_knowledge_fanout(qa, intent, "ngành đó học phí?", conversation_context="Trợ lý: ...")
    assert qa.last_ctx == "Trợ lý: ..."


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


class _ConcurrentQA:
    """answer() chặn trên barrier `parties`; chỉ giải phóng khi đủ số call chạy
    đồng thời. Tuần tự → barrier timeout → max_concurrent < parties."""

    def __init__(self, parties):
        self._barrier = threading.Barrier(parties, timeout=2)
        self._lock = threading.Lock()
        self._active = 0
        self.max_concurrent = 0

    def answer(self, question, school, topic, conversation_context="", query_vector=None, national=None):
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            self._barrier.wait()
        finally:
            with self._lock:
                self._active -= 1
        return KnowledgeQAResult(has_data=False, confidence=0.0)


def test_fanout_runs_pairs_concurrently():
    qa = _ConcurrentQA(parties=2)
    intent = IntentResult(route="HYBRID", schools=["A", "B"], topics=["t"])
    blocks = run_knowledge_fanout(qa, intent, "q")
    assert qa.max_concurrent == 2                      # hai call đồng thời
    assert [b.school for b in blocks] == ["A", "B"]    # thứ tự bảo toàn


def test_format_knowledge_blocks_no_data_uses_first_person():
    from services.chat.knowledge_fanout import format_knowledge_blocks
    from services.chat.hybrid_models import KnowledgeBlock

    blocks = [KnowledgeBlock(school="hust", topic="tuition", has_data=False)]
    text = format_knowledge_blocks(blocks)

    assert "Hệ thống chưa có" not in text
    assert text.startswith("Mình hiện chưa có dữ liệu")


def test_no_module_uses_cold_system_phrasing():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    for rel in ["services/chat/knowledge_fanout.py", "services/chat/conversation_service.py"]:
        text = (root / rel).read_text(encoding="utf-8")
        assert "Hệ thống chưa có" not in text, f"{rel} still uses cold 'Hệ thống chưa có'"
