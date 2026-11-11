import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.network.contracts import APIError, MAX_BODY_BYTES
from app.network.node import Node

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def make_handler(node, *, demo_enabled=False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SFTS-Demo/1"

        def log_message(self, fmt, *args):
            logger.info("%s %s", self.client_address[0], fmt % args)

        def send_payload(self, status, data):
            content = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def read_payload(self):
            header = self.headers.get("Content-Length")
            if header is None or not header.isdecimal():
                raise APIError(411, "LENGTH_REQUIRED", "Требуется заголовок Content-Length")
            length = int(header)
            if length > MAX_BODY_BYTES:
                raise APIError(413, "BODY_TOO_LARGE", "Тело запроса слишком велико")
            try:
                return json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise APIError(400, "BAD_JSON", "Некорректный JSON") from exc

        def run_safely(self, handler):
            try:
                handler()
            except APIError as exc:
                self.send_payload(exc.status, {"status": "ERROR", "code": exc.code, "message": exc.message})
            except (OSError, ValueError, TypeError) as exc:
                logger.exception("Ошибка сохранения или обработки запроса")
                self.send_payload(500, {"status": "ERROR", "code": "INTERNAL_ERROR", "message": "Внутренняя ошибка сервера"})

        def do_GET(self):
            self.run_safely(self.handle_get)

        def handle_get(self):
            parsed = urlsplit(self.path)
            path = parsed.path
            if path in STATIC_FILES and not parsed.query:
                filename, mime = STATIC_FILES[path]
                data = (WEB_DIR / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/v1/status" and not parsed.query:
                return self.send_payload(200, node.status())
            if path.startswith("/api/v1/blocks/") and not parsed.query:
                index = path[len("/api/v1/blocks/"):]
                if not index.isdecimal():
                    raise APIError(400, "BAD_REQUEST", "Индекс блока должен быть числом")
                return self.send_payload(200, node.get_block(int(index)))
            if path == "/api/v1/peers/status":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) != {"url"} or len(query["url"]) != 1:
                    raise APIError(400, "BAD_REQUEST", "Укажите один query-параметр url")
                return self.send_payload(200, node.peer_status(query["url"][0]))
            raise APIError(404, "NOT_FOUND", "Маршрут не найден")

        def do_POST(self):
            self.run_safely(self.handle_post)

        def handle_post(self):
            path = urlsplit(self.path)
            if path.query:
                raise APIError(400, "BAD_REQUEST", "Параметры запроса не поддерживаются")
            if path.path == "/api/v1/documents":
                data = self.read_payload()
                if not isinstance(data, dict) or set(data) != {"documentId", "fileHash"}:
                    raise APIError(400, "BAD_REQUEST", "Ожидаются documentId и fileHash")
                return self.send_payload(201, node.create_document(data["documentId"], data["fileHash"]))
            if path.path == "/api/v1/blocks":
                result = node.accept_block(self.read_payload())
                return self.send_payload(409 if result["status"] == "REJECTED" else 201 if result["status"] == "ACCEPTED" else 200, result)
            if path.path == "/api/v1/peers/pull":
                data = self.read_payload()
                if not isinstance(data, dict) or set(data) != {"peerUrl"}:
                    raise APIError(400, "BAD_REQUEST", "Ожидается peerUrl")
                result = node.pull_one(data["peerUrl"])
                return self.send_payload(409 if result["status"] == "REJECTED" else 200, result)
            if path.path == "/api/v1/demo/blocks" and demo_enabled:
                data = self.read_payload()
                if data != {}:
                    raise APIError(400, "BAD_REQUEST", "Ожидается пустой JSON-объект")
                return self.send_payload(201, node.create_demo_block())
            raise APIError(404, "NOT_FOUND", "Маршрут не найден")
    return Handler


def make_server(host, port, node, *, demo_enabled=False):
    server = ThreadingHTTPServer((host, port), make_handler(node, demo_enabled=demo_enabled))
    server.daemon_threads = True
    server.allow_reuse_address = True
    return server


def main():
    parser = argparse.ArgumentParser(description="HTTP-нода и первый UI распределённой цепочки")
    parser.add_argument("--node-id", required=True, help="Например A или B")
    parser.add_argument("--data-dir", required=True, help="Отдельный каталог с chain.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--network-id", default=None, help="Идентификатор сети (по умолчанию общий demo v1)")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--allow-remote-peers", action="store_true", help="Разрешить обращение за пределы loopback; только для доверенных сетей")
    parser.add_argument("--demo", action="store_true", help="Разрешить POST /api/v1/demo/blocks")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout должен быть больше нуля")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    kwargs = {"allow_remote_peers": args.allow_remote_peers, "timeout": args.timeout}
    if args.network_id is not None:
        kwargs["network_id"] = args.network_id
    node = Node(args.node_id, args.data_dir, **kwargs)
    with make_server(args.host, args.port, node, demo_enabled=args.demo) as server:
        print(f"Node {args.node_id}: http://{args.host}:{args.port}  data={args.data_dir}", flush=True)
        print(f"UI: http://{args.host}:{args.port}/", flush=True)
        try:
            server.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            print("Остановка ноды", flush=True)


if __name__ == "__main__":
    main()
