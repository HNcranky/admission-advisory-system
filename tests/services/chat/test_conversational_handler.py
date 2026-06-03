from services.chat.conversational_handler import build_conversational_response


def test_greeting_returns_nonempty_friendly_text():
    msg = build_conversational_response("GREETING", seed=0)
    assert msg
    assert "nói rõ hơn câu hỏi" not in msg


def test_greeting_is_deterministic_for_same_seed():
    a = build_conversational_response("GREETING", seed=3)
    b = build_conversational_response("GREETING", seed=3)
    assert a == b


def test_greeting_varies_across_seeds():
    seen = {build_conversational_response("GREETING", seed=i) for i in range(3)}
    assert len(seen) > 1  # có nhiều biến thể, không lặp một câu duy nhất


def test_thanks_and_goodbye_and_identity_return_text():
    for subtype in ("THANKS", "GOODBYE", "IDENTITY"):
        assert build_conversational_response(subtype, seed=0)


def test_capability_describes_enabled_features():
    msg = build_conversational_response("CAPABILITY", seed=0)
    assert "tư vấn" in msg.lower()
    # mô tả đúng năng lực đang bật: advisory + tra cứu thông tin
    assert "học phí" in msg.lower() or "thông tin" in msg.lower()


def test_emotional_support_acknowledges_and_pivots():
    msg = build_conversational_response("EMOTIONAL_SUPPORT", seed=0)
    assert msg
    # có yếu tố chuyển sang bước advisory cụ thể (điểm/tổ hợp/ngành)
    low = msg.lower()
    assert "điểm" in low or "tổ hợp" in low or "ngành" in low
