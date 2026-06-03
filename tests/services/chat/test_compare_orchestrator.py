import time

from agents.models import Evidence
from services.chat.compare_orchestrator import CompareOrchestrator
from services.chat.hybrid_models import AdvisoryBlock
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState
from services.knowledge.models import Citation, KnowledgeQAResult


class FakeKnowledgeQA:
    def __init__(self, by_school=None, delay=0.0):
        self._by_school = by_school or {}
        self._delay = delay
        self.calls = []

    def answer(self, question, school, topic, conversation_context=""):
        self.calls.append({"school": school, "topic": topic})
        if self._delay:
            time.sleep(self._delay)
        return self._by_school.get(school, KnowledgeQAResult(has_data=False, confidence=0.0))


class RecordingSynthesis:
    def __init__(self):
        self.advisory = None
        self.knowledge = None
        self.calls = 0

    def synthesize(self, advisory, knowledge, question):
        self.calls += 1
        self.advisory = advisory
        self.knowledge = knowledge
        return "SYNTH"


def _intent(**kw):
    base = {"route": "HYBRID", "schools": ["VNU-UET"], "topics": ["tuition"], "needs_advisory": True}
    base.update(kw)
    return IntentResult(**base)


def test_run_calls_both_branches_and_synthesizes():
    qa = FakeKnowledgeQA(by_school={"VNU-UET": KnowledgeQAResult(
        has_data=True, answer="35 triệu",
        citations=[Citation(source_url="https://uet/hp", chunk_text="..")], confidence=0.9,
    )})
    synth = RecordingSynthesis()
    runner = lambda profile_state, content, trace_run_id=None: {
        "final_answer": "Tư vấn UET", "citations": [Evidence(
            source_url="https://uet/diem", school_name="VNU-UET", admission_year=2026, field_name="benchmark",
        )],
    }
    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    out = orch.run(_intent(), ChatProfileState(total_score=25.0), "so sánh", trace_run_id=1)
    assert out == "SYNTH"
    assert synth.calls == 1
    assert synth.advisory.has_data is True
    assert "Tư vấn UET" == synth.advisory.answer
    assert synth.advisory.sources == ["https://uet/diem"]
    assert synth.knowledge[0].has_data is True


def test_run_skips_advisory_when_needs_advisory_false():
    qa = FakeKnowledgeQA()
    synth = RecordingSynthesis()
    called = {"advisory": False}

    def runner(profile_state, content, trace_run_id=None):
        called["advisory"] = True
        return {"final_answer": "x"}

    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    orch.run(_intent(needs_advisory=False, schools=["VNU-UET", "HUST"]), ChatProfileState(), "q")
    assert called["advisory"] is False
    assert synth.advisory.has_data is False
    assert len(qa.calls) == 2  # fan-out still ran


def test_run_advisory_error_degrades_to_no_data_block():
    qa = FakeKnowledgeQA(by_school={"VNU-UET": KnowledgeQAResult(has_data=True, answer="35 triệu", citations=[], confidence=0.9)})
    synth = RecordingSynthesis()

    def runner(profile_state, content, trace_run_id=None):
        raise RuntimeError("graph blew up")

    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    orch.run(_intent(), ChatProfileState(), "q")
    assert synth.advisory.has_data is False        # advisory degraded
    assert synth.knowledge[0].has_data is True      # knowledge unaffected


def test_run_advisory_empty_answer_is_no_data():
    qa = FakeKnowledgeQA()
    synth = RecordingSynthesis()
    runner = lambda profile_state, content, trace_run_id=None: {"final_answer": "", "advisory": ""}
    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    orch.run(_intent(), ChatProfileState(), "q")
    assert synth.advisory.has_data is False


def test_run_executes_branches_in_parallel():
    # advisory sleeps 0.3s, knowledge sleeps 0.3s; parallel ⇒ well under the 0.6s sum.
    qa = FakeKnowledgeQA(delay=0.3)
    synth = RecordingSynthesis()

    def runner(profile_state, content, trace_run_id=None):
        time.sleep(0.3)
        return {"final_answer": "adv"}

    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    start = time.perf_counter()
    orch.run(_intent(), ChatProfileState(), "q")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.55  # max(0.3, 0.3)+overhead, not 0.6
