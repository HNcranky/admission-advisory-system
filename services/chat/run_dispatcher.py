import logging

from services.chat.advisory_runner import run_advisory_for_session
from services.chat.base_dispatcher import BaseRunDispatcher

logger = logging.getLogger(__name__)


class RunDispatcher(BaseRunDispatcher):
    def __init__(self, repository=None, runner=None):
        super().__init__(repository=repository)
        self.runner = runner or run_advisory_for_session

    def execute(self, session_token: str, run_id: int, latest_user_message: str, profile_state,
                correction_note: dict | None = None, closing_seed: int = 0):
        try:
            self.repository.mark_run_running(run_id)
            result = self.runner(profile_state, latest_user_message, trace_run_id=run_id,
                                 correction_note=correction_note, closing_seed=closing_seed)
            final_answer = result.get("final_answer") or result.get("advisory") or ""
            self.repository.complete_run(run_id, result, final_answer)
            self.repository.append_message(session_token, "assistant", final_answer, "assistant_result")
            self.repository.update_session_status(session_token, "completed")
        except Exception:
            logger.exception("advisory run %s failed for session %s", run_id, session_token)
            self._mark_failed(session_token)
            raise
