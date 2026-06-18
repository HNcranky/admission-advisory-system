from typing import Any, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from services.knowledge.models import KnowledgeQAResult


class KQAState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str
    school: Optional[str] = None
    topic: Optional[str] = None
    conversation_context: str = ""
    # Batching hooks (fan-out injects these; embed/augment no-op when present).
    retrieval_query: Optional[str] = None
    query_vector: Any = None
    national: Any = None
    # Working state.
    embedding: Any = None
    chunks: list = Field(default_factory=list)
    confidence: float = 0.0
    result: Optional[KnowledgeQAResult] = None


def build_kqa_graph(service):
    """Compile the single-(school,topic) knowledge QA pipeline. Nodes reuse the
    service's existing helpers, so behaviour is identical to the former
    answer() body — the gate short-circuits below min_score."""

    def embed(state: KQAState) -> KQAState:
        if state.query_vector is not None:
            state.embedding = state.query_vector
        elif state.retrieval_query:
            state.embedding = service.embed_query(state.retrieval_query)
        else:
            state.embedding = service.embed_query(state.question)
        return state

    def retrieve_school(state: KQAState) -> KQAState:
        state.chunks = service._chunk_repository.vector_search(
            state.embedding, school=state.school, topic=state.topic, limit=service._top_k
        )
        return state

    def augment_national(state: KQAState) -> KQAState:
        state.chunks = service._augment_with_national(
            state.embedding, state.school, state.topic, state.chunks, national=state.national
        )
        state.confidence = state.chunks[0].score if state.chunks else 0.0
        return state

    def generate(state: KQAState) -> KQAState:
        state.result = service._generate(
            state.question, state.chunks, state.confidence, state.conversation_context
        )
        return state

    def no_data(state: KQAState) -> KQAState:
        state.result = KnowledgeQAResult(has_data=False, confidence=state.confidence)
        return state

    def gate(state: KQAState) -> str:
        if state.chunks and state.confidence >= service._min_score:
            return "generate"
        return "no_data"

    builder = StateGraph(KQAState)
    builder.add_node("embed", embed)
    builder.add_node("retrieve_school", retrieve_school)
    builder.add_node("augment_national", augment_national)
    builder.add_node("generate", generate)
    builder.add_node("no_data", no_data)

    builder.set_entry_point("embed")
    builder.add_edge("embed", "retrieve_school")
    builder.add_edge("retrieve_school", "augment_national")
    builder.add_conditional_edges("augment_national", gate,
                                  {"generate": "generate", "no_data": "no_data"})
    builder.add_edge("generate", END)
    builder.add_edge("no_data", END)
    return builder.compile()
