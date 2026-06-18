import logging
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from services.chat.hybrid_models import AdvisoryBlock
from services.chat.knowledge_fanout import run_knowledge_fanout

logger = logging.getLogger(__name__)


class HybridState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    intent: Any
    profile_state: Any
    content: str
    trace_run_id: Any = None
    advisory: Optional[AdvisoryBlock] = None
    knowledge: list = Field(default_factory=list)
    answer: str = ""


def _evidence_url(evidence):
    if isinstance(evidence, dict):
        return evidence.get("source_url")
    return getattr(evidence, "source_url", None)


def build_hybrid_graph(advisory_runner, knowledge_qa, synthesis_agent):
    """advisory ∥ knowledge → synthesis. Mirrors CompareOrchestrator but lets
    LangGraph own branch execution (so stage spans nest under the run span)."""

    # The two branches run in parallel (fan-out from START). Each returns ONLY
    # the field it owns as a partial update — returning the whole state would
    # make both branches write every channel and trip LangGraph's LastValue
    # "one value per step" guard. Disjoint writes need no custom reducer.
    def advisory_branch(state: HybridState) -> dict:
        if not getattr(state.intent, "needs_advisory", False):
            return {"advisory": AdvisoryBlock(has_data=False)}
        try:
            result = advisory_runner(state.profile_state, state.content,
                                     trace_run_id=state.trace_run_id)
            answer = (result.get("final_answer") or result.get("advisory") or "").strip()
            if not answer:
                return {"advisory": AdvisoryBlock(has_data=False)}
            sources = []
            for evidence in (result.get("citations") or []):
                url = _evidence_url(evidence)
                if url and url not in sources:
                    sources.append(url)
            return {"advisory": AdvisoryBlock(has_data=True, answer=answer, sources=sources)}
        except Exception as exc:
            logger.warning("advisory branch failed in hybrid graph: %r", exc)
            return {"advisory": AdvisoryBlock(has_data=False)}

    def knowledge_branch(state: HybridState) -> dict:
        school_fallback = (
            state.profile_state.preferred_schools[0]
            if getattr(state.profile_state, "preferred_schools", None) else None
        )
        try:
            return {"knowledge": run_knowledge_fanout(
                knowledge_qa, state.intent, state.content, school_fallback)}
        except Exception as exc:
            logger.warning("knowledge branch failed in hybrid graph: %r", exc)
            return {"knowledge": []}

    def synthesis(state: HybridState) -> dict:
        advisory = state.advisory or AdvisoryBlock(has_data=False)
        return {"answer": synthesis_agent.synthesize(advisory, state.knowledge, state.content)}

    builder = StateGraph(HybridState)
    builder.add_node("advisory_branch", advisory_branch)
    builder.add_node("knowledge_branch", knowledge_branch)
    builder.add_node("synthesis", synthesis)

    # Fan out from START to both branches; synthesis waits for both (barrier).
    builder.add_edge(START, "advisory_branch")
    builder.add_edge(START, "knowledge_branch")
    builder.add_edge("advisory_branch", "synthesis")
    builder.add_edge("knowledge_branch", "synthesis")
    builder.add_edge("synthesis", END)
    return builder.compile()
