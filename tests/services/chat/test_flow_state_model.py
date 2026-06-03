from services.chat.models import FlowState


def test_flow_state_defaults():
    state = FlowState()
    assert state.active_flow is None
    assert state.pending_question is None


def test_flow_state_model_validate_from_empty_dict():
    state = FlowState.model_validate({})
    assert state == FlowState()


def test_flow_state_model_validate_from_full_dict():
    state = FlowState.model_validate({
        "active_flow": "ADVISORY_FLOW",
        "pending_question": "Bạn học khối gì?",
    })
    assert state.active_flow == "ADVISORY_FLOW"
    assert state.pending_question == "Bạn học khối gì?"


def test_flow_state_model_copy_update_does_not_mutate_original():
    original = FlowState(active_flow="ADVISORY_FLOW")
    updated = original.model_copy(update={"pending_question": "Q?"})
    assert updated.active_flow == "ADVISORY_FLOW"
    assert updated.pending_question == "Q?"
    assert original.pending_question is None


def test_flow_state_ignores_legacy_return_to_flow_key():
    """Old rows may still contain return_to_flow; it must be ignored, not raise."""
    state = FlowState.model_validate({
        "active_flow": "ADVISORY_FLOW",
        "pending_question": "Q?",
        "return_to_flow": True,
    })
    assert state.active_flow == "ADVISORY_FLOW"
    assert not hasattr(state, "return_to_flow")


def test_flow_state_equality():
    a = FlowState(active_flow="ADVISORY_FLOW", pending_question="Q?")
    b = FlowState(active_flow="ADVISORY_FLOW", pending_question="Q?")
    assert a == b
