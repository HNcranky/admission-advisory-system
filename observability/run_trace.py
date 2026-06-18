import contextlib
import logging

from observability.langfuse_client import get_langfuse

logger = logging.getLogger(__name__)


def _redact(payload):
    """Phase-1 passthrough. Single seam to add masking later without
    restructuring call sites (e.g. when switching to Langfuse Cloud)."""
    return payload


def _safe_exit(cm):
    if cm is None:
        return
    try:
        cm.__exit__(None, None, None)
    except Exception as exc:
        logger.warning("langfuse span close failed: %r", exc)


@contextlib.contextmanager
def advisory_run_trace(run_id, session_token, user_message, intent=None, admission_year=None):
    """Root span/trace for one advisory run. Yields the span (or None when
    disabled). Any Langfuse error is swallowed; the run always proceeds."""
    client = get_langfuse()
    cm = None
    span = None
    if client is not None:
        try:
            trace_id = client.create_trace_id(seed=str(run_id))
            cm = client.start_as_current_span(
                name="advisory-run",
                input=_redact({"user_message": user_message, "intent": intent}),
                trace_context={"trace_id": trace_id},
            )
            span = cm.__enter__()
            span.update_trace(
                session_id=str(session_token),
                metadata={"run_id": run_id, "intent": intent, "admission_year": admission_year},
                tags=["advisory"],
            )
        except Exception as exc:
            logger.warning("langfuse advisory_run_trace open failed: %r", exc)
            _safe_exit(cm)
            cm = None
            span = None
    try:
        yield span
    finally:
        _safe_exit(cm)


@contextlib.contextmanager
def turn_trace(turn_id, session_token, user_message):
    """Root span/trace for one synchronous chat turn. Yields the span (or None
    when disabled). Generations emitted while active (intent router, inline
    knowledge QA) nest under it via OTEL contextvars. Errors are swallowed."""
    client = get_langfuse()
    cm = None
    span = None
    if client is not None:
        try:
            trace_id = client.create_trace_id(seed=str(turn_id))
            cm = client.start_as_current_span(
                name="chat-turn",
                input=_redact({"user_message": user_message}),
                trace_context={"trace_id": trace_id},
            )
            span = cm.__enter__()
            span.update_trace(
                session_id=str(session_token),
                metadata={"turn_id": turn_id},
                tags=["turn"],
            )
        except Exception as exc:
            logger.warning("langfuse turn_trace open failed: %r", exc)
            _safe_exit(cm)
            cm = None
            span = None
    try:
        yield span
    finally:
        _safe_exit(cm)


@contextlib.contextmanager
def stage_span(stage, sequence, input_json=None):
    """Child span for one pipeline stage. Generations created while this span
    is active nest under it (OTEL contextvars, same worker thread).

    ``input_json`` is the state slice the node consumes; without it the span's
    input shows null (output is set separately via ``set_span_output``)."""
    client = get_langfuse()
    cm = None
    span = None
    if client is not None:
        try:
            cm = client.start_as_current_span(
                name=stage, input=_redact(input_json), metadata={"sequence": sequence})
            span = cm.__enter__()
        except Exception as exc:
            logger.warning("langfuse stage_span open failed for %s: %r", stage, exc)
            _safe_exit(cm)
            cm = None
            span = None
    try:
        yield span
    finally:
        _safe_exit(cm)


def set_span_output(span, output_json):
    if span is None:
        return
    try:
        span.update(output=_redact(output_json))
    except Exception as exc:
        logger.warning("langfuse set_span_output failed: %r", exc)


def record_generation(request, result, usage=None, latency_ms=None, attempt=None,
                      used_fallback=None, failure_type=None, model=None, prompt=None):
    """Emit one generation observation under the active span. Each retry/fallback
    call site emits its own generation."""
    client = get_langfuse()
    if client is None:
        return
    try:
        usage_details = None
        if usage:
            usage_details = {
                "input": usage.get("input"),
                "output": usage.get("output"),
                "total": usage.get("total"),
            }
        with client.start_as_current_generation(
            name=getattr(request, "agent_name", "generation"),
            model=model or getattr(result, "model", None),
            input=_redact({
                "system": getattr(request, "system_prompt", None),
                "user": getattr(request, "user_prompt", None),
            }),
            model_parameters={"temperature": getattr(request, "temperature", None)},
            prompt=prompt,
        ) as gen:
            gen.update(
                output=_redact(getattr(result, "content", None)),
                usage_details=usage_details,
                metadata={
                    "attempt": attempt,
                    "used_fallback": used_fallback,
                    "failure_type": failure_type
                    if failure_type is not None
                    else getattr(result, "failure_type", None),
                    "task_type": getattr(request, "task_type", None),
                    "latency_ms": latency_ms,
                },
            )
    except Exception as exc:
        logger.warning("langfuse record_generation failed: %r", exc)
