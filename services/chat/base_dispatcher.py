import logging

from services.chat.repository import ChatSessionRepository

logger = logging.getLogger(__name__)


class BaseRunDispatcher:
    """Shared execution helpers for advisory and hybrid runs.

    After PR9 the executor-based dispatch path is removed; dispatchers only
    provide execute() called by RunQueueWorker. What remains here is the
    repository handle and the shared failure-recovery messages."""

    def __init__(self, repository=None):
        self.repository = repository or ChatSessionRepository()

    def _mark_failed(self, session_token: str):
        try:
            self.repository.append_message(
                session_token,
                "assistant",
                "Xin lỗi, quá trình phân tích bị gián đoạn. Bạn thử lại giúp mình nhé.",
                "assistant_error",
            )
        except Exception:
            logger.exception("failed to append error message for session %s", session_token)
        try:
            self.repository.update_session_status(session_token, "failed")
        except Exception:
            logger.exception("failed to mark session %s as failed", session_token)
