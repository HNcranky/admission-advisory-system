import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.app import build_app


def test_chat_page_renders_debug_flag_true_when_env_set():
    with patch.dict(os.environ, {"ADVISORY_DEBUG_UI": "1"}):
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-debug-ui="true"' in response.text


def test_chat_page_renders_debug_flag_false_by_default():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ADVISORY_DEBUG_UI", None)
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-debug-ui="false"' in response.text


def test_chat_page_theme_default_light_when_env_unset():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ADVISORY_THEME_DEFAULT", None)
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-theme-default="light"' in response.text


def test_chat_page_theme_default_dark_when_env_set_dark():
    with patch.dict(os.environ, {"ADVISORY_THEME_DEFAULT": "dark"}):
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-theme-default="dark"' in response.text


def test_chat_page_theme_default_falls_back_to_light_for_invalid_value():
    with patch.dict(os.environ, {"ADVISORY_THEME_DEFAULT": "neon-purple"}):
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-theme-default="light"' in response.text


def test_chat_page_renders_vietnamese_stage_labels():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    for label in [
        "Phân tích hồ sơ",
        "Tra cứu chương trình",
        "Đối chiếu nguồn dữ liệu",
        "Suy luận khuyến nghị",
        "Đối chiếu quy chế",
        "Soạn lời giải thích",
    ]:
        assert label in response.text, f"missing stage label: {label}"


def test_chat_page_exposes_stage_labels_and_debug_globals():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "window.__stageLabels" in response.text
    assert "window.__debugUi" in response.text


def test_chat_page_renders_svg_sprite():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert '<symbol id="icon-user-circle"' in response.text
    assert '<symbol id="icon-status-pending"' in response.text


def test_chat_page_includes_app_version():
    import tomllib
    from pathlib import Path

    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="help-popover"' in response.text
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject.get("project", {}).get("version") or "dev"
    assert version in response.text


def test_chat_page_renders_toast_stack():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="toast-stack"' in response.text


def test_chat_page_includes_greeting_empty_state_strings():
    """Greeting markup is rendered by JS; confirm the Vietnamese string lives
    in the bundled module so it ships with the page."""
    from pathlib import Path
    messages_js = Path("web/static/js/modules/messages.js").read_text(encoding="utf-8")
    assert "Xin chào! Hãy mô tả" in messages_js
