from unittest.mock import patch

from fastapi.testclient import TestClient

from web.app import build_app


def test_trace_endpoint_returns_payload_for_known_session():
    fake_payload = {
        "run_id": 42,
        "run_status": "running",
        "events": [
            {"stage": "profile", "sequence": 0, "status": "completed",
             "duration_ms": 1234, "started_at": "2026-05-28T03:15:01+00:00",
             "completed_at": "2026-05-28T03:15:02+00:00",
             "output_json": {"k": 1}, "error_text": None},
        ],
    }

    with patch("web.routes.chat_api.TraceService") as mock_cls:
        mock_cls.return_value.get_trace.return_value = fake_payload
        client = TestClient(build_app())
        response = client.get("/api/sessions/abc-token/trace")

    assert response.status_code == 200
    assert response.json() == fake_payload


def test_trace_endpoint_returns_404_for_unknown_session():
    with patch("web.routes.chat_api.TraceService") as mock_cls:
        mock_cls.return_value.get_trace.return_value = None
        client = TestClient(build_app())
        response = client.get("/api/sessions/unknown/trace")

    assert response.status_code == 404
