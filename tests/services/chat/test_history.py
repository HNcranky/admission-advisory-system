from services.chat.history import build_history_context
from services.chat.models import ChatMessageRecord


def _msg(role, content, kind="chat"):
    return ChatMessageRecord(
        id=1, session_token="t", role=role, kind=kind, content=content
    )


def test_empty_returns_empty_string():
    assert build_history_context([]) == ""


def test_formats_user_and_assistant_lines():
    msgs = [_msg("user", "chào"), _msg("assistant", "xin chào")]
    out = build_history_context(msgs)
    assert "Người dùng: chào" in out
    assert "Trợ lý: xin chào" in out


def test_keeps_only_last_three_pairs():
    msgs = []
    for i in range(5):
        msgs.append(_msg("user", f"u{i}"))
        msgs.append(_msg("assistant", f"a{i}"))
    out = build_history_context(msgs)
    # 5 pairs in, only last 3 pairs (u2..u4) survive
    assert "u1" not in out
    assert "u2" in out
    assert "u4" in out


def test_truncates_long_message_with_ellipsis():
    long = "x" * 800
    out = build_history_context([_msg("user", long)], max_chars=500)
    assert "…" in out
    assert "x" * 501 not in out


def test_skips_non_user_assistant_roles():
    msgs = [_msg("system", "secret"), _msg("user", "hỏi"), _msg("assistant", "đáp")]
    out = build_history_context(msgs)
    assert "secret" not in out
    assert "hỏi" in out
