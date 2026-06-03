from agents.models import Evidence
from services.chat.compare_orchestrator import CompareOrchestrator
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState
from services.chat.synthesis_agent import SynthesisAgent
from services.knowledge.models import Citation, KnowledgeQAResult


class FailingGateway:
    """Force SynthesisAgent down the deterministic concatenation path."""
    def is_available(self):
        return True

    def run(self, request):
        raise RuntimeError("llm down")


class FakeKnowledgeQA:
    def __init__(self, by_school=None):
        self._by_school = by_school or {}

    def answer(self, question, school, topic, conversation_context=""):
        return self._by_school.get(school, KnowledgeQAResult(has_data=False, confidence=0.0))


def _orchestrator(advisory_runner, knowledge_qa):
    return CompareOrchestrator(
        advisory_runner=advisory_runner,
        knowledge_qa=knowledge_qa,
        synthesis_agent=SynthesisAgent(gateway=FailingGateway()),
    )


def _intent():
    return IntentResult(
        route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"], needs_advisory=True,
    )


def _profile():
    return ChatProfileState(
        admission_year=2026, total_score=27.0,
        preferred_majors=["computer_science"], location_preference="Ha Noi",
        preferred_schools=["VNU-UET", "HUST"],
    )


def test_full_data_both_branches_separates_sections_and_sources():
    advisory_runner = lambda profile_state, content, trace_run_id=None: {
        "final_answer": "Bạn có khả năng đậu UET ngành CNTT.",
        "citations": [Evidence(source_url="https://uet/diem", school_name="VNU-UET",
                               admission_year=2026, field_name="benchmark")],
    }
    qa = FakeKnowledgeQA(by_school={
        "VNU-UET": KnowledgeQAResult(has_data=True, answer="Học phí UET ~35 triệu/năm.",
                                     citations=[Citation(source_url="https://uet/hp", chunk_text="..")], confidence=0.9),
        "HUST": KnowledgeQAResult(has_data=True, answer="Học phí HUST ~24 triệu/năm.",
                                  citations=[Citation(source_url="https://hust/hp", chunk_text="..")], confidence=0.9),
    })
    out = _orchestrator(advisory_runner, qa).run(_intent(), _profile(), "so sánh UET và HUST")

    assert "Theo dữ liệu tuyển sinh" in out          # structured section present
    assert "Thông tin trường" in out                  # knowledge section present
    assert "khả năng đậu UET" in out
    assert "35 triệu" in out and "24 triệu" in out
    assert "Nguồn:" in out
    for url in ("https://uet/diem", "https://uet/hp", "https://hust/hp"):
        assert url in out


def test_knowledge_missing_marks_that_part_only():
    advisory_runner = lambda profile_state, content, trace_run_id=None: {
        "final_answer": "Tư vấn: UET phù hợp với điểm của bạn.", "citations": [],
    }
    qa = FakeKnowledgeQA(by_school={})  # no knowledge data for any school
    out = _orchestrator(advisory_runner, qa).run(_intent(), _profile(), "q")

    assert "UET phù hợp" in out                        # advisory still answered
    assert "chưa có dữ liệu" in out.lower()            # knowledge part flagged missing


def test_advisory_missing_marks_that_part_only():
    def advisory_runner(profile_state, content, trace_run_id=None):
        raise RuntimeError("advisory graph failed")

    qa = FakeKnowledgeQA(by_school={
        "VNU-UET": KnowledgeQAResult(has_data=True, answer="Học phí UET ~35 triệu.", citations=[], confidence=0.9),
    })
    out = _orchestrator(advisory_runner, qa).run(_intent(), _profile(), "q")

    assert "35 triệu" in out                            # knowledge still answered
    assert "chưa có dữ liệu" in out.lower()            # advisory part flagged missing


def test_both_missing_produces_no_data_response_without_fabrication():
    def advisory_runner(profile_state, content, trace_run_id=None):
        return {"final_answer": "", "citations": []}

    qa = FakeKnowledgeQA(by_school={})
    out = _orchestrator(advisory_runner, qa).run(_intent(), _profile(), "q")

    assert "chưa có dữ liệu" in out.lower()
    assert "Nguồn:" not in out                          # no sources, nothing fabricated
