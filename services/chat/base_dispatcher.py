import logging
import threading

from services.chat.repository import ChatSessionRepository
from ingestion.config.settings import ADVISORY_RUN_WORKERS, ADVISORY_RUN_QUEUE_MAX

logger = logging.getLogger(__name__)


class BoundedExecutor:
    """ThreadPoolExecutor wrapper with a counted semaphore for backpressure.

    submit() returns False immediately when the queue is full instead of
    enqueueing silently — callers can post a rejection message to the user."""

    def __init__(self, max_workers, max_queue):
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._sem = threading.Semaphore(max_queue)

    def submit(self, fn, *args, **kwargs):
        if not self._sem.acquire(blocking=False):
            return False

        def _wrapped():
            try:
                fn(*args, **kwargs)
            finally:
                self._sem.release()

        self._pool.submit(_wrapped)
        return True


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
        self.executor = executor or BoundedExecutor(ADVISORY_RUN_WORKERS, ADVISORY_RUN_QUEUE_MAX)

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

    def _reject(self, session_token: str):
        try:
            self.repository.append_message(
                session_token,
                "assistant",
                "Hệ thống đang xử lý nhiều yêu cầu, bạn vui lòng thử lại sau giây lát nhé.",
                "assistant_error",
            )
            self.repository.update_session_status(session_token, "failed")
        except Exception:
            logger.exception("failed to post reject message for session %s", session_token)
