import io
import json
import socket
from http.client import BadStatusLine
from urllib.error import HTTPError, URLError

import pytest

from app.network import client
from app.network.contracts import APIError

BASE_URL = "http://127.0.0.1:8765"
GET_PATH = "/api/v1/status"
POST_PATH = "/api/v1/blocks"


class FakeResponse:

    def __init__(self, status=200, body=b"{}", read_error=None):
        self.status = status
        self.body = body
        self.read_error = read_error
        self.read_limits = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True
        return False

    def read(self, size=-1):
        self.read_limits.append(size)
        if self.read_error is not None:
            raise self.read_error
        return self.body if size < 0 else self.body[:size]


class FakeOpener:

    def __init__(self, result):
        self.result = result
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.fixture
def fake_open(monkeypatch):
    def configure(result):
        opener = FakeOpener(result)
        monkeypatch.setattr(client, "_OPENER", opener)
        return opener

    return configure


def http_error(code, body=b"{}"):
    return HTTPError(
        BASE_URL + POST_PATH,
        code,
        f"HTTP {code}",
        {},
        io.BytesIO(body),
    )


def assert_api_error(exc, status, code):
    error = exc.value
    assert error.status == status
    assert error.code == code
    assert isinstance(error.message, str) and error.message
    assert str(error) == error.message


def test_redirects_are_disabled():
    handler = client._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, BASE_URL) is None
    assert any(isinstance(h, client._NoRedirect) for h in client._OPENER.handlers)


# GET


def test_get_json_success_and_request_headers(fake_open):
    response = FakeResponse(body=b'{"height":2,"chainValid":true}')
    opener = fake_open(response)

    result = client.get_json(BASE_URL, GET_PATH, timeout=3.5)

    assert result == {"height": 2, "chainValid": True}
    assert response.closed
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == BASE_URL + GET_PATH
    assert request.get_method() == "GET"
    assert request.data is None
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("User-agent") == "sfts-node/1"
    assert timeout == 3.5


def test_get_json_allows_empty_object(fake_open):
    fake_open(FakeResponse(body=b"{}"))
    assert client.get_json(BASE_URL, GET_PATH) == {}


@pytest.mark.parametrize("status", [201, 204, 302, 404, 500])
def test_get_json_rejects_unexpected_response_status(fake_open, status):
    response = FakeResponse(status=status)
    fake_open(response)

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 502, "PEER_HTTP_ERROR")
    assert str(status) in exc.value.message
    assert response.closed


@pytest.mark.parametrize("status", [301, 302, 404, 409, 500, 503])
def test_get_json_converts_http_errors(fake_open, status):
    fake_open(http_error(status))

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 502, "PEER_HTTP_ERROR")
    assert str(status) in exc.value.message


@pytest.mark.parametrize("body", [b"", b"not-json", b'{"height":', b"\xff"],
                         ids=["empty", "invalid_text", "unfinished", "invalid_utf8"])
def test_get_json_rejects_invalid_json(fake_open, body):
    fake_open(FakeResponse(body=body))

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


@pytest.mark.parametrize("body", [b"[]", b"null", b"123", b'"hello"', b"true"])
def test_get_json_requires_json_object(fake_open, body):
    fake_open(FakeResponse(body=body))

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


def test_get_json_rejects_oversized_response(fake_open, monkeypatch):
    monkeypatch.setattr(client, "MAX_BODY_BYTES", 10)
    response = FakeResponse(body=b'{"very_long":true}')
    fake_open(response)

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")
    assert response.read_limits == [11]


def test_get_json_accepts_response_exactly_at_size_limit(fake_open, monkeypatch):
    body = b'{"ok":true}'
    monkeypatch.setattr(client, "MAX_BODY_BYTES", len(body))
    response = FakeResponse(body=body)
    fake_open(response)

    assert client.get_json(BASE_URL, GET_PATH) == {"ok": True}
    assert response.read_limits == [len(body) + 1]


@pytest.mark.parametrize("stage", ["opening", "reading"])
def test_get_json_converts_malformed_http_response(fake_open, stage):
    error = BadStatusLine("bad response")
    fake_open(error if stage == "opening" else FakeResponse(read_error=error))

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


@pytest.mark.parametrize("stage", ["opening", "reading"])
@pytest.mark.parametrize("error_type", [TimeoutError, socket.timeout])
def test_get_json_converts_timeouts(fake_open, stage, error_type):
    error = error_type("timed out")
    fake_open(error if stage == "opening" else FakeResponse(read_error=error))

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 504, "PEER_TIMEOUT")


def test_get_json_recognizes_timeout_wrapped_in_url_error(fake_open):
    fake_open(URLError(TimeoutError("timed out")))

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 504, "PEER_TIMEOUT")


@pytest.mark.parametrize("error", [
    URLError("name resolution failed"),
    ConnectionRefusedError("connection refused"),
    ConnectionResetError("connection reset"),
    OSError("network unreachable"),
])
def test_get_json_converts_connection_errors(fake_open, error):
    fake_open(error)

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 502, "PEER_UNAVAILABLE")


def test_get_json_converts_network_error_while_reading(fake_open):
    fake_open(FakeResponse(read_error=ConnectionResetError("disconnected")))

    with pytest.raises(APIError) as exc:
        client.get_json(BASE_URL, GET_PATH)

    assert_api_error(exc, 502, "PEER_UNAVAILABLE")


# POST 


@pytest.mark.parametrize("status", [200, 201])
def test_post_json_success_and_request_headers(fake_open, status):
    response = FakeResponse(status=status, body=b'{"status":"ACCEPTED"}')
    opener = fake_open(response)
    data = {"block": {"index": 1}, "message": "Привет"}

    result = client.post_json(BASE_URL, POST_PATH, data, timeout=4.25)

    assert result == {"status": "ACCEPTED"}
    assert response.closed
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == BASE_URL + POST_PATH
    assert request.get_method() == "POST"
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Content-type") == "application/json; charset=utf-8"
    assert request.get_header("User-agent") == "sfts-node/1"
    assert timeout == 4.25
    assert request.data == json.dumps(data, ensure_ascii=False).encode("utf-8")
    assert "Привет".encode("utf-8") in request.data


def test_post_json_allows_empty_json_object_response(fake_open):
    fake_open(FakeResponse(body=b"{}"))
    assert client.post_json(BASE_URL, POST_PATH, {}) == {}


def test_post_json_rejects_payload_over_size_limit_without_http_call(fake_open, monkeypatch):
    monkeypatch.setattr(client, "MAX_BODY_BYTES", 15)
    opener = fake_open(FakeResponse())

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {"message": "x" * 20})

    assert_api_error(exc, 400, "BODY_TOO_LARGE")
    assert opener.requests == []


def test_post_json_allows_payload_exactly_at_size_limit(fake_open, monkeypatch):
    data = {"message": "hello"}
    size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(client, "MAX_BODY_BYTES", size)
    fake_open(FakeResponse(body=b"{}"))

    assert client.post_json(BASE_URL, POST_PATH, data) == {}


@pytest.mark.parametrize("status", [202, 204, 302, 400, 500])
def test_post_json_rejects_unexpected_response_status(fake_open, status):
    response = FakeResponse(status=status)
    fake_open(response)

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_HTTP_ERROR")
    assert str(status) in exc.value.message
    assert response.closed


@pytest.mark.parametrize("status", [301, 302, 400, 404, 500, 503])
def test_post_json_converts_non_conflict_http_errors(fake_open, status):
    fake_open(http_error(status))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_HTTP_ERROR")
    assert str(status) in exc.value.message


def test_post_json_returns_rejected_payload_on_http_409(fake_open):
    payload = {
        "status": "REJECTED", "code": "BLOCK_CONFLICT",
        "message": "Блок отклонён", "blockIndex": 1,
        "blockHash": "a" * 64,
    }
    fake_open(http_error(409, json.dumps(payload, ensure_ascii=False).encode("utf-8")))

    assert client.post_json(BASE_URL, POST_PATH, {"block": {}}) == payload


@pytest.mark.parametrize("body", [
    b'{"status":"ACCEPTED"}',
    b'{"status":"ALREADY_PRESENT"}',
    b'{"status":null}',
    b'{}',
])
def test_post_json_rejects_http_409_without_rejected_status(fake_open, body):
    fake_open(http_error(409, body))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_HTTP_ERROR")
    assert "409" in exc.value.message


@pytest.mark.parametrize("body", [b"", b"invalid", b"\xff"])
def test_post_json_rejects_invalid_json_on_http_409(fake_open, body):
    fake_open(http_error(409, body))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


@pytest.mark.parametrize("body", [b"[]", b"null", b'"REJECTED"'])
def test_post_json_rejects_non_object_on_http_409(fake_open, body):
    fake_open(http_error(409, body))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


def test_post_json_rejects_oversized_response_on_http_409(fake_open, monkeypatch):
    monkeypatch.setattr(client, "MAX_BODY_BYTES", 20)
    fake_open(http_error(409, b'{"status":"REJECTED","detail":"too long"}'))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


@pytest.mark.parametrize("body", [b"", b"not json", b'{"status":', b"\xff"])
def test_post_json_rejects_invalid_json_on_success(fake_open, body):
    fake_open(FakeResponse(body=body))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


@pytest.mark.parametrize("body", [b"[]", b"null", b"12", b'"ok"'])
def test_post_json_requires_json_object_on_success(fake_open, body):
    fake_open(FakeResponse(body=body))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


def test_post_json_rejects_oversized_success_response(fake_open, monkeypatch):
    monkeypatch.setattr(client, "MAX_BODY_BYTES", 10)
    response = FakeResponse(body=b'{"very_long":true}')
    fake_open(response)

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")
    assert response.read_limits == [11]


def test_post_json_accepts_response_exactly_at_size_limit(fake_open, monkeypatch):
    body = b'{"ok":true}'
    monkeypatch.setattr(client, "MAX_BODY_BYTES", len(body))
    response = FakeResponse(body=body)
    fake_open(response)

    assert client.post_json(BASE_URL, POST_PATH, {}) == {"ok": True}
    assert response.read_limits == [len(body) + 1]


@pytest.mark.parametrize("stage", ["opening", "reading"])
def test_post_json_converts_malformed_http_response(fake_open, stage):
    error = BadStatusLine("bad status line")
    fake_open(error if stage == "opening" else FakeResponse(read_error=error))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


@pytest.mark.parametrize("stage", ["opening", "reading"])
@pytest.mark.parametrize("error_type", [TimeoutError, socket.timeout])
def test_post_json_converts_timeouts(fake_open, stage, error_type):
    error = error_type("timed out")
    fake_open(error if stage == "opening" else FakeResponse(read_error=error))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 504, "PEER_TIMEOUT")


def test_post_json_recognizes_timeout_wrapped_in_url_error(fake_open):
    fake_open(URLError(TimeoutError("timed out")))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 504, "PEER_TIMEOUT")


@pytest.mark.parametrize("error", [
    URLError("DNS failure"),
    ConnectionRefusedError("connection refused"),
    ConnectionResetError("connection reset"),
    OSError("network unreachable"),
])
def test_post_json_converts_connection_errors(fake_open, error):
    fake_open(error)

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_UNAVAILABLE")


def test_post_json_converts_network_error_while_reading(fake_open):
    fake_open(FakeResponse(read_error=ConnectionResetError("connection lost")))

    with pytest.raises(APIError) as exc:
        client.post_json(BASE_URL, POST_PATH, {})

    assert_api_error(exc, 502, "PEER_UNAVAILABLE")
