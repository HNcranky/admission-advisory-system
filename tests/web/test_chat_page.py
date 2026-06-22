from fastapi.testclient import TestClient

from web.app import build_app


def test_chat_page_renders_reset_and_results_regions():
    client = TestClient(build_app())

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="reset-session"' in response.text
    assert 'id="recommendation-panel"' in response.text
    assert 'id="send-button"' in response.text


def test_chat_page_renders_two_column_shell():
    client = TestClient(build_app())

    response = client.get("/")
    body = response.text

    assert response.status_code == 200
    assert 'class="app-shell chat-shell"' in body
    assert 'class="app-header"' in body
    assert 'id="profile-panel"' in body
    assert 'id="chat-panel"' in body
    assert 'id="trace-panel"' not in body


def test_chat_page_renders_collapse_and_drawer_buttons():
    client = TestClient(build_app())

    response = client.get("/")
    body = response.text

    assert response.status_code == 200
    assert 'id="collapse-left"' in body
    assert 'id="open-left-drawer"' in body
    assert 'id="collapse-right"' not in body
    assert 'id="open-right-drawer"' not in body


def test_chat_page_preserves_legacy_ids_for_existing_js():
    client = TestClient(build_app())

    response = client.get("/")
    body = response.text

    assert response.status_code == 200
    for legacy in ("chat-transcript", "chat-form", "chat-input", "profile-summary"):
        assert f'id="{legacy}"' in body


def test_chat_page_shows_composer_hint():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "Ctrl+Enter để gửi" in response.text


def test_chat_page_has_help_popover_and_reset_inside():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert 'id="help-button"' in body
    assert 'id="help-popover"' in body
    assert 'id="reset-session"' in body
    popover_idx = body.index('id="help-popover"')
    reset_idx = body.index('id="reset-session"')
    assert reset_idx > popover_idx, "reset-session must be rendered inside help-popover"
