"""Local dashboard for the live scalper."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .engine import Engine

WEB = Path(__file__).resolve().parent.parent / "web"


class Handler(BaseHTTPRequestHandler):
    engine: Engine
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch(write_body=False)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch(write_body=True)

    def _dispatch(self, *, write_body: bool) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            self._file(WEB / "index.html", "text/html; charset=utf-8", write_body=write_body)
            return
        if path == "/api/state":
            self._json(200, self.engine.state(), write_body=write_body)
            return
        if path == "/health":
            self._json(200, {"ok": True}, write_body=write_body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/api/action":
            self.send_error(404)
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0) or 0)
        try:
            payload = json.loads(raw.decode() or "{}")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
        except (ValueError, UnicodeDecodeError) as e:
            self._json(400, {"ok": False, "error": str(e)})
            return
        self._json(200, self.engine.action(payload))

    def _json(self, code: int, obj: dict, *, write_body: bool = True) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _file(self, p: Path, ctype: str, *, write_body: bool = True) -> None:
        if not p.exists():
            self.send_error(404)
            return
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        if write_body:
            self.wfile.write(data)


def serve(engine: Engine, host: str, port: int) -> ThreadingHTTPServer:
    Handler.engine = engine
    httpd = ThreadingHTTPServer((host, port), Handler)
    t = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    t.start()
    return httpd
