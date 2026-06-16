import logging
from concurrent.futures import ThreadPoolExecutor

from services.chat.repository import ChatSessionRepository

logger = logging.getLogger(__name__)


class BaseRunDispatcher:
    """Shared fire-and-forget run dispatching (audit §2.5).

    Subclasses keep their own ``submit``/``_execute`` (the actual work differs:
    advisory runner vs compare orchestrator). What's shared is the threadpool,
    the repository handle, and the single failure-recovery path — so the error
    message has one source of truth instead of two copies that drifted apart
    (the hybrid copy had lost its Vietnamese diacritics).
    """

    def __init__(self, repository=None, executor=None):
        self.repository = repository or ChatSessionRepository()
        self.executor = executor or ThreadPoolExecutor(max_workers=2)

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
