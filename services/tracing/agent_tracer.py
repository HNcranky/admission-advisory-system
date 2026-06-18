import logging
from typing import Callable

from observability.run_trace import stage_span, set_span_output

logger = logging.getLogger(__name__)


def traced(stage: str, sequence: int, output_extractor: Callable,
           input_extractor: Callable | None = None):
    """Wrap a graph node so it emits one Langfuse stage span.

    The span's input is `input_extractor(state)` and its output is
    `output_extractor(result, state)`. No-ops (runs the node bare) when the
    state carries no `trace_run_id`, i.e. outside a traced run.
    """
    def decorator(agent_fn):
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            input_json = None
            if input_extractor is not None:
                try:
                    input_json = input_extractor(state)
                except Exception as exc:
                    logger.warning("trace input extractor failed for stage=%s: %r", stage, exc)
                    input_json = {"_extractor_error": repr(exc)}
            with stage_span(stage, sequence, input_json=input_json) as span:
                result = agent_fn(state)
                try:
                    output_json = output_extractor(result, state)
                except Exception as exc:
                    logger.warning("trace extractor failed for stage=%s: %r", stage, exc)
                    output_json = {"_extractor_error": repr(exc)}
                set_span_output(span, output_json)
            return result

        return wrapped

    return decorator
