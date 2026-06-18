# tests/services/chat/test_turn_graph.py
from services.chat.models import ChatProfileState, FlowState


def test_turn_state_defaults():
    from services.chat.turn_graph import TurnState
    st = TurnState(session_token="tok", content="hi",
                   profile_state=ChatProfileState(), flow_state=FlowState(), delta={})
    assert st.route is None and st.result is None and st.session_status == "collecting_profile"
