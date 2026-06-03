from fastapi.testclient import TestClient
from pathlib import Path


from web.app import build_app


def test_chat_page_references_static_client_assets():
    client = TestClient(build_app())

    response = client.get("/")

    assert '/static/js/chat.js' in response.text
    assert '/static/css/chat.css' in response.text
    
    
def test_chat_client_supports_snapshot_refresh_and_run_polling():
    script = Path("web/static/js/chat.js").read_text(encoding="utf-8")
    messages = Path("web/static/js/modules/messages.js").read_text(encoding="utf-8")

    assert "async function fetchSessionSnapshot" in script
    # renderTranscript now lives in the messages module (slice 03 extraction).
    assert "export function renderTranscript" in messages
    assert "renderTranscript" in script
    assert "function renderProfileSummary" in script
    assert "function schedulePolling" in script
    assert "window.localStorage" in script
    assert "`/api/sessions/${sessionToken}`" in script
    
    
def test_chat_client_clears_stale_session_token_and_reports_startup_errors():
    script = Path("web/static/js/chat.js").read_text(encoding="utf-8")
    styles = Path("web/static/css/chat.css").read_text(encoding="utf-8")

    assert "window.localStorage.removeItem(SESSION_KEY)" in script
    # The status line was removed; the startup error now surfaces via a toast.
    assert "Không thể khởi tạo phiên chat." in script
    assert ".toast--error" in styles
    assert ".message--assistant" in styles


def test_chat_client_and_styles_preserve_readable_multiline_output():
    script = Path("web/static/js/chat.js").read_text(encoding="utf-8")
    messages = Path("web/static/js/modules/messages.js").read_text(encoding="utf-8")
    styles = Path("web/static/css/chat.css").read_text(encoding="utf-8")
    template = Path("web/templates/chat.html").read_text(encoding="utf-8")

    assert "Hồ sơ tạm thời" in template
    assert "Khuyến nghị mới nhất" in template
    # "Chưa có khuyến nghị." moved into the messages module with the
    # renderRecommendationCard extraction in slice 03.
    assert "Chưa có khuyến nghị." in messages
    assert "Tổng điểm" in script
    assert "white-space: pre-wrap" in styles
