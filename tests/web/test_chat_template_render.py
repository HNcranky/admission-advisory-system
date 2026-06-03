"""Static template assertions for the chat page.

These tests stay at the HTML-string level (no JS execution); they verify
the contract that slice-03 assets are linked and the composer slots exist.
"""

from fastapi.testclient import TestClient

from web.app import build_app


def test_chat_template_links_chat_markdown_css():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "/static/css/chat-markdown.css" in response.text


def test_chat_template_has_chat_input_textarea():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert '<textarea' in response.text
    assert 'id="chat-input"' in response.text


def test_chat_template_has_send_button_and_status_slot():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="send-button"' in response.text
    assert 'id="composer-status"' in response.text
