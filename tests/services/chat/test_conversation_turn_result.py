from services.chat.models import ChatProfileState, ConversationTurnResult
from services.knowledge.models import Citation


def test_conversation_turn_result_defaults_citations_empty():
    r = ConversationTurnResult(
        session_status="ready",
        assistant_message="hi",
        profile_state=ChatProfileState(),
    )
    assert r.citations == []


def test_conversation_turn_result_accepts_citations():
    r = ConversationTurnResult(
        session_status="ready",
        assistant_message="hi",
        profile_state=ChatProfileState(),
        citations=[Citation(source_url="u", chunk_text="t")],
    )
    assert len(r.citations) == 1
    assert r.citations[0].source_url == "u"


def test_turn_result_defaults_run_kind_advisory():
    r = ConversationTurnResult(
        session_status="ready", assistant_message="ok", profile_state=ChatProfileState(),
    )
    assert r.run_kind == "advisory"
    assert r.hybrid_intent is None


def test_turn_result_accepts_hybrid_kind_and_intent_payload():
    r = ConversationTurnResult(
        session_status="running",
        assistant_message="đang tổng hợp",
        should_start_run=True,
        run_kind="hybrid",
        hybrid_intent={"route": "HYBRID", "schools": ["VNU-UET", "HUST"], "needs_advisory": True},
        profile_state=ChatProfileState(),
    )
    assert r.run_kind == "hybrid"
    assert r.hybrid_intent["schools"] == ["VNU-UET", "HUST"]
