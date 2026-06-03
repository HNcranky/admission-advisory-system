from services.inference.providers.gemini_errors import (
    extract_status_code,
    is_rotatable_error,
    parse_retry_delay,
)


class FakeAPIError(Exception):
    """Mimics google.genai.errors.APIError: carries an int `code`."""

    def __init__(self, code, message=""):
        super().__init__(message or f"{code} error")
        self.code = code


# Realistic 429 string seen in production logs.
_REAL_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
    "'You exceeded your current quota. Please retry in 26.777807406s.', "
    "'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '26s'}]}}"
)


def test_extract_status_code_reads_code_attribute():
    assert extract_status_code(FakeAPIError(429)) == 429
    assert extract_status_code(FakeAPIError(503)) == 503


def test_extract_status_code_falls_back_to_string_scan():
    assert extract_status_code(RuntimeError("429 RESOURCE_EXHAUSTED")) == 429


def test_extract_status_code_returns_none_when_absent():
    assert extract_status_code(ValueError("boom")) is None


def test_is_rotatable_for_quota_auth_and_server_errors():
    assert is_rotatable_error(FakeAPIError(429)) is True
    assert is_rotatable_error(FakeAPIError(401)) is True
    assert is_rotatable_error(FakeAPIError(403)) is True
    assert is_rotatable_error(FakeAPIError(500)) is True
    assert is_rotatable_error(FakeAPIError(503)) is True


def test_is_not_rotatable_for_client_input_and_unknown_errors():
    assert is_rotatable_error(FakeAPIError(400)) is False
    assert is_rotatable_error(FakeAPIError(404)) is False
    assert is_rotatable_error(ValueError("network down")) is False


def test_parse_retry_delay_from_retrydelay_field():
    assert parse_retry_delay(RuntimeError("...'retryDelay': '26s'...")) == 26.0


def test_parse_retry_delay_from_retry_in_phrase():
    assert parse_retry_delay(RuntimeError("Please retry in 26.7s.")) == 26.7


def test_parse_retry_delay_on_real_429_payload():
    assert parse_retry_delay(FakeAPIError(429, _REAL_429)) == 26.0


def test_parse_retry_delay_returns_none_when_absent():
    assert parse_retry_delay(FakeAPIError(429, "quota exceeded")) is None
