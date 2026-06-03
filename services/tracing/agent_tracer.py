import logging
from typing import Callable

from services.tracing.trace_repository import TraceRepository

STAGE_ORDER = ["profile", "retrieve", "conflict", "reason", "policy", "explain"]

logger = logging.getLogger(__name__)

_default_repo = TraceRepository()


def _safe(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except Exception as exc:
        logger.warning("trace persistence failed: %r", exc)
        return None


def traced(stage: str, sequence: int, output_extractor: Callable, repository: TraceRepository | None = None):
    repo = repository or _default_repo

    def decorator(agent_fn):
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            event_id = _safe(repo.start_event, run_id, stage, sequence)
            try:
                result = agent_fn(state)
            except Exception as exc:
                if event_id is not None:
                    _safe(repo.fail_event, event_id, repr(exc))
                raise
            try:
                output_json = output_extractor(result, state)
            except Exception as exc:
                logger.warning("trace extractor failed for stage=%s: %r", stage, exc)
                output_json = {"_extractor_error": repr(exc)}
            if event_id is not None:
                _safe(repo.complete_event, event_id, output_json)
            return result

        return wrapped

    return decorator
