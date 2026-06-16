import logging
import threading

from ingestion.config.settings import ADVISORY_QUEUE_POLL_SECONDS
from services.chat.repository import ChatSessionRepository

logger = logging.getLogger(__name__)


class RunQueueWorker:
    """Poll chat_advisory_runs for queued items and execute them via the dispatcher's _execute.

    Uses SKIP LOCKED so multiple workers / replicas never claim the same run."""

    def __init__(self, worker_id: str, repository=None, run=None, hybrid=None,
                 poll_seconds: float = ADVISORY_QUEUE_POLL_SECONDS):
        self.worker_id = worker_id
        self.repository = repository or ChatSessionRepository()
        self._run = run
        self._hybrid = hybrid
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()

    def _get_run_dispatcher(self):
        if self._run is not None:
            return self._run
        from services.chat.run_dispatcher import RunDispatcher
        return RunDispatcher(repository=self.repository)

    def _get_hybrid_dispatcher(self):
        if self._hybrid is not None:
            return self._hybrid
        from services.chat.hybrid_dispatcher import HybridDispatcher
        return HybridDispatcher(repository=self.repository)

    def poll_once(self) -> bool:
        claimed = self.repository.claim_next_queued_run(self.worker_id)
        if claimed is None:
            return False
        args = claimed.get("dispatch_args") or {}
        run_kind = args.get("run_kind", "advisory")
        try:
            if run_kind == "hybrid":
                from services.chat.intent_router import IntentResult
                intent = IntentResult.model_validate(
                    args.get("intent") or {"route": "HYBRID"}
                )
                self._get_hybrid_dispatcher().execute(
                    claimed["session_token"], claimed["run_id"],
                    args.get("content", ""), args.get("profile_state"),
                    intent,
                )
            else:
                self._get_run_dispatcher().execute(
                    claimed["session_token"], claimed["run_id"],
                    args.get("latest_user_message", ""), args.get("profile_state"),
                    args.get("correction_note"), args.get("closing_seed", 0),
                )
        except Exception:
            logger.exception(
                "queue worker: run %s for session %s failed",
                claimed["run_id"], claimed["session_token"],
            )
        return True

    def run_forever(self):
        while not self._stop.is_set():
            try:
                worked = self.poll_once()
            except Exception:
                logger.exception("queue worker poll failed")
                worked = False
            if not worked:
                self._stop.wait(self.poll_seconds)

    def stop(self):
        self._stop.set()
