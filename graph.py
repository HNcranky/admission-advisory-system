from langgraph.graph import StateGraph

from state import AgentState

from agents.profile_agent import profile_agent
from agents.retrieval_agent import retrieval_agent
from agents.conflict_agent import conflict_agent
from agents.reasoning_agent import reasoning_agent
from agents.policy_agent import policy_agent
from agents.explanation_agent import explanation_agent

from services.tracing.agent_tracer import traced
from services.tracing.extractors import (
    extract_profile,
    extract_candidates,
    extract_conflicts,
    extract_reasoning,
    extract_policy,
    extract_explanation,
)


builder = StateGraph(AgentState)

builder.add_node("profile",  traced("profile",  0, extract_profile)(profile_agent))
builder.add_node("retrieve", traced("retrieve", 1, extract_candidates)(retrieval_agent))
builder.add_node("conflict", traced("conflict", 2, extract_conflicts)(conflict_agent))
builder.add_node("reason",   traced("reason",   3, extract_reasoning)(reasoning_agent))
builder.add_node("policy",   traced("policy",   4, extract_policy)(policy_agent))
builder.add_node("explain",  traced("explain",  5, extract_explanation)(explanation_agent))


builder.set_entry_point("profile")

builder.add_edge("profile", "retrieve")
builder.add_edge("retrieve", "conflict")
builder.add_edge("conflict", "reason")
builder.add_edge("reason", "policy")
builder.add_edge("policy", "explain")


graph = builder.compile()
