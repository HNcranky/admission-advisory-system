import logging

from services.chat.advisory_runner import run_advisory_for_session
from services.chat.hybrid_graph import HybridState, build_hybrid_graph
from services.chat.synthesis_agent import SynthesisAgent
from services.knowledge.qa_service import KnowledgeQAService

logger = logging.getLogger(__name__)


class CompareOrchestrator:
    def __init__(self, advisory_runner=None, knowledge_qa=None, synthesis_agent=None):
        self.advisory_runner = advisory_runner or run_advisory_for_session
        self.knowledge_qa = knowledge_qa or KnowledgeQAService()
        self.synthesis_agent = synthesis_agent or SynthesisAgent()
        self._graph = build_hybrid_graph(
            self.advisory_runner, self.knowledge_qa, self.synthesis_agent)

    def run(self, intent, profile_state, content, trace_run_id=None) -> str:
        state = HybridState(intent=intent, profile_state=profile_state,
                            content=content, trace_run_id=trace_run_id)
        final = self._graph.invoke(state)
        return final["answer"] if isinstance(final, dict) else final.answer
