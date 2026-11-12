import json
import socket
from urllib.error import HTTPError, URLError
from http.client import HTTPException
from urllib.request import HTTPRedirectHandler, Request, build_opener


from app.network.contracts import APIError, MAX_BODY_BYTES


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect)


def get_json(base_url, path, timeout = 2.0):
    url = base_url + path
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "sfts-node/1"})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise APIError(502, "PEER_HTTP_ERROR", f"Пир вернул HTTP {response.status}")
            raw = response.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                raise APIError(502, "PEER_BAD_RESPONSE", "Ответ пира слишком большой")
            try:
                parsed = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise APIError(502, "PEER_BAD_RESPONSE", "Пир вернул невалидный JSON") from exc
            if not isinstance(parsed, dict):
                raise APIError(502, "PEER_BAD_RESPONSE", "Ожидался JSON-объект")
            return parsed
    except HTTPError as exc:
        raise APIError(502, "PEER_HTTP_ERROR", f"Пир вернул HTTP {exc.code}") from exc

    except HTTPException as exc:
        raise APIError(502, "PEER_BAD_RESPONSE", "Пир вернул некорректный или неполный HTTP-ответ") from exc

    except (socket.timeout, TimeoutError) as exc:
        raise APIError(504, "PEER_TIMEOUT", "Превышено время ожидания ответа пира") from exc

    except (URLError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise APIError(504, "PEER_TIMEOUT", "Превышено время ожидания ответа пира") from exc
        raise APIError(502, "PEER_UNAVAILABLE", "Пир недоступен или соединение отклонено") from exc


def post_json(base_url, path, data, timeout=2.0):
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")

    if len(payload) > MAX_BODY_BYTES:
        raise APIError(400, "BODY_TOO_LARGE", "Отправляемый блок слишком велик")

    request = Request(
        base_url + path,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "sfts-node/1"
        }
    )

    def read_response(response):
        raw = response.read(MAX_BODY_BYTES + 1)

        if len(raw) > MAX_BODY_BYTES:
            raise APIError(502, "PEER_BAD_RESPONSE", "Ответ пира слишком большой")

        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIError(502, "PEER_BAD_RESPONSE", "Некорректный JSON") from exc

        if not isinstance(result, dict):
            raise APIError(502, "PEER_BAD_RESPONSE", "Ожидался JSON-объект")

        return result

    try:
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                if response.status not in (200, 201):
                    raise APIError(502, "PEER_HTTP_ERROR", f"HTTP {response.status}")

                return read_response(response)

        except HTTPError as exc:
            if exc.code == 409:
                with exc:
                    result = read_response(exc)

                if result.get("status") == "REJECTED":
                    return result

            raise APIError(502, "PEER_HTTP_ERROR", f"HTTP {exc.code}") from exc

    except (socket.timeout, TimeoutError) as exc:
        raise APIError(504, "PEER_TIMEOUT", "Превышено время ожидания") from exc

    except HTTPException as exc:
        raise APIError(502, "PEER_BAD_RESPONSE", "Некорректный HTTP-ответ") from exc

    except (URLError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)

        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise APIError(504, "PEER_TIMEOUT", "Превышено время ожидания") from exc

        raise APIError(502, "PEER_UNAVAILABLE", "Пир недоступен") from exc
