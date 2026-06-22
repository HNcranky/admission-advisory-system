import logging

from services.chat.base_dispatcher import BaseRunDispatcher
from services.chat.compare_orchestrator import CompareOrchestrator
from observability.run_trace import advisory_run_trace

logger = logging.getLogger(__name__)


class HybridDispatcher(BaseRunDispatcher):
    def __init__(self, repository=None, orchestrator=None):
        super().__init__(repository=repository)
        self.orchestrator = orchestrator or CompareOrchestrator()

    def execute(self, session_token: str, run_id: int, content: str, profile_state, intent):
        try:
            self.repository.mark_run_running(run_id)
            with advisory_run_trace(
                run_id, session_token, content,
                intent=getattr(intent, "route", None),
                admission_year=getattr(profile_state, "admission_year", None),
            ):
                answer = self.orchestrator.run(intent, profile_state, content, trace_run_id=run_id)
            self.repository.complete_run(run_id, {"final_answer": answer, "kind": "hybrid"}, answer)
            self.repository.append_message(session_token, "assistant", answer, "assistant_result")
            self.repository.update_session_status(session_token, "completed")
        except Exception:
            logger.exception("hybrid run %s failed for session %s", run_id, session_token)
            self._mark_failed(session_token)
            raise
