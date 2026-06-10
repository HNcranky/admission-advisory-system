"""Format recent chat turns into a compact text block for LLM prompts.

Pure formatting — no DB, no IO. The caller fetches messages (via
``repository.list_message``) and passes them in chronological order.
"""

_ROLE_LABELS = {"user": "Người dùng", "assistant": "Trợ lý"}


def build_history_context(messages, max_pairs: int = 3, max_chars: int = 500) -> str:
    """Render the last ``max_pairs`` user/assistant turns as labelled lines.

    - Only ``user``/``assistant`` roles are kept (other roles are skipped).
    - Keeps the last ``max_pairs * 2`` such messages.
    - Each message body is truncated to ``max_chars`` (… appended) so one long
      message cannot blow up the prompt — the single context-window guard.
    - Empty input → "" (caller treats this as "no history").
    """
    kept = [m for m in messages if m.role in _ROLE_LABELS]
    kept = kept[-(max_pairs * 2):]
    lines = []
    for m in kept:
        text = m.content or ""
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        lines.append(f"{_ROLE_LABELS[m.role]}: {text}")
    return "\n".join(lines)
