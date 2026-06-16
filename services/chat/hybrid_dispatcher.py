import logging

from services.chat.base_dispatcher import BaseRunDispatcher
from services.chat.compare_orchestrator import CompareOrchestrator

logger = logging.getLogger(__name__)


class HybridDispatcher(BaseRunDispatcher):
    def __init__(self, repository=None, orchestrator=None, executor=None):
        super().__init__(repository=repository, executor=executor)
        self.orchestrator = orchestrator or CompareOrchestrator()

    def submit(self, session_token: str, run_id: int, content: str, profile_state, intent):
        self.executor.submit(self._execute, session_token, run_id, content, profile_state, intent)

    def _execute(self, session_token: str, run_id: int, content: str, profile_state, intent):
        try:
            self.repository.mark_run_running(run_id)
            answer = self.orchestrator.run(intent, profile_state, content, trace_run_id=run_id)
            self.repository.complete_run(run_id, {"final_answer": answer, "kind": "hybrid"}, answer)
            self.repository.append_message(session_token, "assistant", answer, "assistant_result")
            self.repository.update_session_status(session_token, "completed")
        except Exception:
            # Fire-and-forget executor thread: log or the failure is lost, and
            # mark failed best-effort so the session can't hang in 'running'.
            logger.exception("hybrid run %s failed for session %s", run_id, session_token)
            self._mark_failed(session_token)
            raise
