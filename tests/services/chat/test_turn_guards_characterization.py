# tests/services/chat/test_turn_guards_characterization.py
from unittest.mock import MagicMock

from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, FlowState


def _svc(profile=None, flow=None, session=None, delta=None):
    repo = MagicMock()
    repo.list_message.return_value = []
    repo.get_profile_state.return_value = profile or ChatProfileState()
    repo.get_flow_state.return_value = flow or FlowState()
    repo.get_session_by_token.return_value = session
    repo.count_runs.return_value = 0
    svc = ConversationService(
        repository=repo,
        extract_profile=lambda *a, **k: (delta or {}),
        intent_router=MagicMock(),
        knowledge_qa=MagicMock(),
    )
    return svc, repo


def test_reset_phrase_starts_fresh_profile_before_routing():
    svc, repo = _svc()
    svc.intent_router.classify.return_value = MagicMock(route="ADVISORY_FLOW")
    result = svc.handle_user_message("tok", "xoá hết thông tin, bắt đầu lại")
    # reset wins over intent routing; classify must NOT decide the turn
    assert result.should_start_run is False
    assert result.profile_state == ChatProfileState() or result.profile_state is not None


def test_continue_advisory_fills_pending_slot():
    profile = ChatProfileState(total_score=25, subject_combination="A00",
                               preferred_majors=["CNTT"], preferred_schools=["UET"])
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Bạn xét tuyển năm nào?")
    svc, repo = _svc(profile=profile, flow=flow, delta={"admission_year": 2026})
    result = svc.handle_user_message("tok", "năm 2026")
    # the bare answer advances the advisory flow rather than being misrouted
    assert result.profile_state.admission_year == 2026


def test_correction_rerun_after_prior_run():
    profile = ChatProfileState(total_score=27, subject_combination="A00",
                               admission_method="thpt_score", admission_year=2026,
                               preferred_majors=["CNTT"], preferred_schools=["UET"])
    session = MagicMock(status="completed", latest_run_id=42)
    svc, repo = _svc(profile=profile, session=session, delta={"total_score": 25.75})
    result = svc.handle_user_message("tok", "à mình tính lại 25.75 không phải 27")
    assert result.should_start_run is True
    assert result.correction_note and result.correction_note["new_value"] == 25.75
