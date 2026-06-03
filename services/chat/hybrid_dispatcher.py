import logging
from concurrent.futures import ThreadPoolExecutor

from services.chat.compare_orchestrator import CompareOrchestrator
from services.chat.repository import ChatSessionRepository

logger = logging.getLogger(__name__)


class HybridDispatcher:
    def __init__(self, repository=None, orchestrator=None, executor=None):
        self.repository = repository or ChatSessionRepository()
        self.orchestrator = orchestrator or CompareOrchestrator()
        self.executor = executor or ThreadPoolExecutor(max_workers=2)

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

    def _mark_failed(self, session_token: str):
        try:
            self.repository.append_message(
                session_token,
                "assistant",
                "Xin loi, qua trinh tong hop bi gian doan. Ban hay thu lai.",
                "assistant_error",
            )
        except Exception:
            logger.exception("failed to append error message for session %s", session_token)
        try:
            self.repository.update_session_status(session_token, "failed")
        except Exception:
            logger.exception("failed to mark session %s as failed", session_token)
