"""Local dashboard for the live scalper."""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import Engine

WEB = Path(__file__).resolve().parent.parent / "web"


def tokens_match(provided: str, needed: str) -> bool:
    if not needed:
        return True
    a = (provided or "").encode()
    b = needed.encode()
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


class Handler(BaseHTTPRequestHandler):
    engine: Engine
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def _query_token(self) -> str:
        qs = parse_qs(urlparse(self.path).query)
        vals = qs.get("token") or []
        return (vals[0] if vals else "").strip()

    def _provided_token(self, payload: dict | None = None) -> str:
        hdr = (self.headers.get("X-Scalper-Token") or "").strip()
        if hdr:
            return hdr
        if payload and isinstance(payload, dict):
            body = str(payload.get("token") or "").strip()
            if body:
                return body
        return self._query_token()

    def _token_ok(self, payload: dict | None = None) -> bool:
        need = (self.engine.cfg.dashboard_token or "").strip()
        return tokens_match(self._provided_token(payload), need)

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch(write_body=False)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch(write_body=True)

    def _dispatch(self, *, write_body: bool) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            self._file(WEB / "index.html", "text/html; charset=utf-8", write_body=write_body)
            return
        if path in {"/roughs", "/roughs/"}:
            self._file(WEB / "roughs" / "index.html", "text/html; charset=utf-8", write_body=write_body)
            return
        if path == "/api/state":
            if not self._token_ok():
                self._json(
                    401,
                    {"ok": False, "error": "dashboard token required", "dashboard_locked": True},
                    write_body=write_body,
                )
                return
            self._json(200, self.engine.state(), write_body=write_body)
            return
        if path == "/health":
            self._json(200, {"ok": True}, write_body=write_body)
            return
        # Static assets under web/ (dash.js, roughs/*.html). Never escape WEB.
        if path.startswith("/web/"):
            path = path[len("/web") :]
        rel = path.lstrip("/")
        if rel and ".." not in rel.split("/") and not rel.startswith("."):
            candidate = (WEB / rel).resolve()
            try:
                candidate.relative_to(WEB.resolve())
            except ValueError:
                self.send_error(404)
                return
            if candidate.is_file():
                ctype = "application/octet-stream"
                if candidate.suffix == ".html":
                    ctype = "text/html; charset=utf-8"
                elif candidate.suffix == ".js":
                    ctype = "application/javascript; charset=utf-8"
                elif candidate.suffix == ".css":
                    ctype = "text/css; charset=utf-8"
                elif candidate.suffix == ".svg":
                    ctype = "image/svg+xml"
                elif candidate.suffix == ".png":
                    ctype = "image/png"
                elif candidate.suffix == ".webmanifest":
                    ctype = "application/manifest+json"
                self._file(candidate, ctype, write_body=write_body)
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
        if not self._token_ok(payload):
            self._json(401, {"ok": False, "error": "dashboard token required", "dashboard_locked": True})
            return
        self._json(200, self.engine.action(payload))

    def _json(self, code: int, obj: dict, *, write_body: bool = True) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body) if write_body else 0))
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
        self.send_header("Content-Length", str(len(data) if write_body else 0))
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
