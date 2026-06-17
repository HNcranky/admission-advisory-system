import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.routes.system import router as system_router
from web.routes.chat_api import router as chat_router
from web.routes.pages import router as page_router

logger = logging.getLogger(__name__)


def build_app() -> FastAPI:
    app = FastAPI(title="Student Advisory Chat")
    app.mount("/static", StaticFiles(directory="web/static"), name="static")
    app.include_router(system_router)
    app.include_router(chat_router)
    app.include_router(page_router)

    @app.on_event("startup")
    def _reap_on_startup():
        try:
            from services.chat.startup import reap_orphaned_runs
            reap_orphaned_runs()
        except Exception:
            logger.exception("startup reap skipped")

    @app.on_event("startup")
    def _configure_threadpool():
        try:
            import os
            import anyio.to_thread
            size = int(os.getenv("WEB_THREADPOOL_SIZE", "40"))
            anyio.to_thread.current_default_thread_limiter().total_tokens = size
        except Exception:
            logger.exception("threadpool sizing skipped")

    @app.on_event("startup")
    def _start_queue_worker():
        try:
            from ingestion.config.settings import ADVISORY_DURABLE_QUEUE
            if not ADVISORY_DURABLE_QUEUE:
                return
            import os
            import socket
            import threading
            from services.chat.run_queue_worker import RunQueueWorker
            worker_id = f"{socket.gethostname()}-{os.getpid()}"
            worker = RunQueueWorker(worker_id=worker_id)
            app.state.queue_worker = worker
            threading.Thread(target=worker.run_forever, daemon=True).start()
            logger.info("durable queue worker started: %s", worker_id)
        except Exception:
            logger.exception("queue worker startup skipped")

    @app.on_event("shutdown")
    def _flush_langfuse():
        try:
            from observability.langfuse_client import flush_langfuse
            flush_langfuse()
        except Exception:
            logger.exception("langfuse flush skipped")

    return app