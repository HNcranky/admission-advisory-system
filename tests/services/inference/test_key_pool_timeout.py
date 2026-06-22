import services.inference.providers.key_pool as key_pool


def test_default_client_factory_sets_request_timeout(monkeypatch):
    captured = {}

    class _SDKClient:
        def __init__(self, *, api_key, http_options=None):
            captured["api_key"] = api_key
            captured["http_options"] = http_options

    monkeypatch.setattr(key_pool.genai, "Client", _SDKClient)
    key_pool._default_client_factory("k-1")

    assert captured["api_key"] == "k-1"
    assert captured["http_options"] is not None
    # google-genai dùng mili-giây; mặc định 60s = 60000ms.
    assert captured["http_options"].timeout == 60_000
