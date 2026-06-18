import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from observability.langfuse_client import get_langfuse

logger = logging.getLogger(__name__)

_DEFAULT_LABEL = "production"
_DEFAULT_CACHE_TTL = 300


def _label() -> str:
    return os.getenv("LANGFUSE_PROMPT_LABEL", _DEFAULT_LABEL)


def _cache_ttl() -> int:
    raw = os.getenv("LANGFUSE_PROMPT_CACHE_TTL_SECONDS", str(_DEFAULT_CACHE_TTL))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_CACHE_TTL


@dataclass
class CompiledPrompt:
    """Resolved system prompt. ``handle`` is the Langfuse prompt client used to
    link a generation to its prompt version; None on fallback (nothing to link)."""

    text: str
    handle: Optional[Any] = None
    is_fallback: bool = False


class PromptService:
    """Resolve a named prompt to text + a linkable handle. Mirrors the
    graceful-degradation contract of build_default_gateway()/get_langfuse():
    callers never special-case Langfuse being off or down."""

    def get(self, name: str, *, fallback: str, variables: Optional[dict] = None) -> CompiledPrompt:
        client = get_langfuse()
        if client is None:
            return CompiledPrompt(text=fallback, handle=None, is_fallback=True)
        raise NotImplementedError  # enabled path implemented in Task 2
