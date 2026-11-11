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
