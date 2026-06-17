import logging
import os
import threading

logger = logging.getLogger(__name__)

_client = None
_initialized = False
_lock = threading.Lock()

_TRUTHY = {"1", "true", "yes", "on"}


def _enabled() -> bool:
    return os.getenv("ADVISORY_LANGFUSE_ENABLED", "false").strip().lower() in _TRUTHY


def get_langfuse():
    """Return a process-wide Langfuse client, or None when disabled/misconfigured.

    None => every observability helper no-ops. Mirrors build_default_gateway()'s
    graceful-degradation contract: callers never need to special-case Langfuse.
    """
    global _client, _initialized
    if _initialized:
        return _client
    with _lock:
        if _initialized:
            return _client
        _initialized = True
        if not _enabled():
            _client = None
            return _client
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
        if not public_key or not secret_key:
            logger.warning(
                "ADVISORY_LANGFUSE_ENABLED is set but LANGFUSE_PUBLIC_KEY/"
                "LANGFUSE_SECRET_KEY are missing; observability disabled"
            )
            _client = None
            return _client
        try:
            from langfuse import Langfuse
            _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        except Exception as exc:  # SDK import or init failure must not break the app
            logger.warning("Langfuse client init failed; observability disabled: %r", exc)
            _client = None
        return _client


def flush_langfuse() -> None:
    client = get_langfuse()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        logger.warning("Langfuse flush failed: %r", exc)


def reset_langfuse_client() -> None:
    """Test hook: clear the cached client so env changes take effect."""
    global _client, _initialized
    with _lock:
        _client = None
        _initialized = False
