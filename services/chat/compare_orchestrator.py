import logging
from concurrent.futures import ThreadPoolExecutor

from services.chat.advisory_runner import run_advisory_for_session
from services.chat.hybrid_models import AdvisoryBlock
from services.chat.knowledge_fanout import run_knowledge_fanout
from services.chat.synthesis_agent import SynthesisAgent
from services.knowledge.qa_service import KnowledgeQAService

logger = logging.getLogger(__name__)


def _evidence_url(evidence):
    if isinstance(evidence, dict):
        return evidence.get("source_url")
    return getattr(evidence, "source_url", None)


class CompareOrchestrator:
    def __init__(self, advisory_runner=None, knowledge_qa=None, synthesis_agent=None):
        self.advisory_runner = advisory_runner or run_advisory_for_session
        self.knowledge_qa = knowledge_qa or KnowledgeQAService()
        self.synthesis_agent = synthesis_agent or SynthesisAgent()

    def run(self, intent, profile_state, content, trace_run_id=None) -> str:
        school_fallback = (
            profile_state.preferred_schools[0] if profile_state.preferred_schools else None
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            adv_future = (
                executor.submit(self._run_advisory, profile_state, content, trace_run_id)
                if intent.needs_advisory
                else None
            )
            kqa_future = executor.submit(
                run_knowledge_fanout, self.knowledge_qa, intent, content, school_fallback
            )
            advisory = self._collect_advisory(adv_future)
            knowledge = self._collect_knowledge(kqa_future)
        return self.synthesis_agent.synthesize(advisory, knowledge, content)

    def _run_advisory(self, profile_state, content, trace_run_id) -> AdvisoryBlock:
        result = self.advisory_runner(profile_state, content, trace_run_id=trace_run_id)
        answer = (result.get("final_answer") or result.get("advisory") or "").strip()
        if not answer:
            return AdvisoryBlock(has_data=False)
        sources = []
        for evidence in (result.get("citations") or []):
            url = _evidence_url(evidence)
            if url and url not in sources:
                sources.append(url)
        return AdvisoryBlock(has_data=True, answer=answer, sources=sources)

    @staticmethod
    def _collect_advisory(future) -> AdvisoryBlock:
        if future is None:
            return AdvisoryBlock(has_data=False)
        try:
            return future.result()
        except Exception as exc:
            logger.warning("advisory branch failed in hybrid compare: %r", exc)
            return AdvisoryBlock(has_data=False)

    @staticmethod
    def _collect_knowledge(future) -> list:
        try:
            return future.result()
        except Exception as exc:
            logger.warning("knowledge branch failed in hybrid compare: %r", exc)
            return []
