import logging

from services.chat.repository import ChatSessionRepository

logger = logging.getLogger(__name__)


def reap_orphaned_runs(repository=None) -> int:
    """Mark orphaned advisory runs as failed and notify their sessions.

    Runs 'queued' or 'running' with no live executor are stuck after a process
    restart. Called once at startup; idempotent if called multiple times."""
    repo = repository or ChatSessionRepository()
    reaped = repo.reap_stale_runs()
    for run_id, session_token in reaped:
        try:
            repo.append_message(
                session_token, "assistant",
                "Xin lỗi, quá trình phân tích bị gián đoạn. Bạn thử lại giúp mình nhé.",
                "assistant_error",
            )
            repo.update_session_status(session_token, "failed")
        except Exception:
            logger.exception("reap: failed to finalize session %s", session_token)
    if reaped:
        logger.warning("reaped %d orphaned advisory run(s) on startup", len(reaped))
    return len(reaped)
