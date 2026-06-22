# tests/services/chat/test_hybrid_graph.py
from unittest.mock import MagicMock

from services.chat.hybrid_models import AdvisoryBlock, KnowledgeBlock
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState


def _deps(needs_advisory=True):
    advisory_runner = MagicMock(return_value={"final_answer": "Đậu ~70%.", "citations": []})
    knowledge_qa = MagicMock()
    synthesis = MagicMock()
    synthesis.synthesize.return_value = "TỔNG HỢP"
    return advisory_runner, knowledge_qa, synthesis


def test_hybrid_graph_runs_both_branches_then_synthesizes(monkeypatch):
    from services.chat import hybrid_graph as hg
    advisory_runner, knowledge_qa, synthesis = _deps()
    monkeypatch.setattr(hg, "run_knowledge_fanout",
                        lambda kqa, intent, content, school_fallback=None, **k:
                        [KnowledgeBlock(school="UET", topic="tuition", has_data=True,
                                        answer="15tr", sources=["http://u"])])
    graph = hg.build_hybrid_graph(advisory_runner, knowledge_qa, synthesis)
    state = hg.HybridState(
        intent=IntentResult(route="HYBRID", needs_advisory=True, schools=["UET"], topics=["tuition"]),
        profile_state=ChatProfileState(preferred_schools=["UET"]),
        content="so sánh", trace_run_id=1)
    final = graph.invoke(state)
    answer = final["answer"] if isinstance(final, dict) else final.answer
    assert answer == "TỔNG HỢP"
    advisory_runner.assert_called_once()
    # synthesis got an AdvisoryBlock with data and one KnowledgeBlock
    adv_arg, kb_arg, q_arg = synthesis.synthesize.call_args.args
    assert isinstance(adv_arg, AdvisoryBlock) and adv_arg.has_data is True
    assert kb_arg and kb_arg[0].answer == "15tr"


def test_hybrid_graph_skips_advisory_when_not_needed(monkeypatch):
    from services.chat import hybrid_graph as hg
    advisory_runner, knowledge_qa, synthesis = _deps()
    monkeypatch.setattr(hg, "run_knowledge_fanout", lambda *a, **k: [])
    graph = hg.build_hybrid_graph(advisory_runner, knowledge_qa, synthesis)
    state = hg.HybridState(
        intent=IntentResult(route="HYBRID", needs_advisory=False),
        profile_state=ChatProfileState(), content="chỉ học phí")
    graph.invoke(state)
    advisory_runner.assert_not_called()
    adv_arg, _, _ = synthesis.synthesize.call_args.args
    assert adv_arg.has_data is False
