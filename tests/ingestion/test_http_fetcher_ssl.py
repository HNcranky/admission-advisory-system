import logging

import ingestion.fetchers.http_fetcher as http_fetcher


class _FakeResponse:
    content = b"<html>ok</html>"
    url = "https://example.test/page"
    headers = {"Content-Type": "text/html"}
    status_code = 200

    def raise_for_status(self):
        return None


def _patch_requests(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None, verify=None, allow_redirects=None):
        captured["verify"] = verify
        return _FakeResponse()

    monkeypatch.setattr(http_fetcher.requests, "get", fake_get)
    return captured


def test_http_fetch_warns_when_ssl_verification_disabled(monkeypatch, caplog):
    captured = _patch_requests(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="ingestion.fetchers.http_fetcher"):
        http_fetcher.http_fetch("https://example.test/page", verify_ssl=False)

    assert captured["verify"] is False
    assert any("SSL verification" in record.message for record in caplog.records)


def test_http_fetch_no_warning_when_ssl_verification_enabled(monkeypatch, caplog):
    captured = _patch_requests(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="ingestion.fetchers.http_fetcher"):
        http_fetcher.http_fetch("https://example.test/page", verify_ssl=True)

    assert captured["verify"] is True
    assert not any("SSL verification" in record.message for record in caplog.records)
