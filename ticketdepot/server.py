"""Serves the UI on 127.0.0.1, maps POST /api/<method> onto Api, and serves downloads.

Other websites open in the same browser can send requests to 127.0.0.1 too, so:
- every request must carry our own Host header (blocks DNS rebinding);
- every POST must carry the per-launch token that only our page knows, and no
  foreign Origin.
"""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from . import __version__
from .api import Api


def ui_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))  # PyInstaller unpacks here
    return base / "ticketdepot" / "ui"


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, api: Api, port: int):
        self.api = api
        self.token = secrets.token_urlsafe(24)
        super().__init__(("127.0.0.1", port), _Handler)

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


class _Handler(BaseHTTPRequestHandler):
    server: Server

    def do_GET(self):
        if not self._host_ok():
            return self.send_error(403)
        api, path = self.server.api, self.path.split("?")[0]
        if path == "/api/ping":
            return self._send(200, json.dumps(api.ping()).encode(), "application/json")
        if m := re.fullmatch(r"/ticket/(\d+)\.pdf", path):
            pdf = api.ticket_pdf(m[1])
            return self._send(200, pdf.read_bytes(), "application/pdf") if pdf else self.send_error(404)
        if m := re.fullmatch(r"/proof/(\d+)\.pdf", path):
            return self._download(_safe(api.proof, int(m[1])), "application/pdf")
        if m := re.fullmatch(r"/ics/(\d+)\.ics", path):
            return self._download(_safe(api.calendar, int(m[1])), "text/calendar; charset=utf-8")
        if path == "/ics/alle.ics":
            return self._download(api.calendar(), "text/calendar; charset=utf-8")
        name = path.lstrip("/") or "index.html"
        ui = ui_dir().resolve()
        file = (ui / name).resolve()
        if ui not in file.parents or not file.is_file():
            return self.send_error(404)
        body = file.read_bytes()
        if name == "index.html":
            body = body.replace(b"{{TOKEN}}", self.server.token.encode()).replace(b"{{VERSION}}", __version__.encode())
        self._send(200, body, mimetypes.guess_type(file.name)[0] or "application/octet-stream")

    def do_POST(self):
        origin = self.headers.get("Origin")
        if (
            not self._host_ok()
            or not secrets.compare_digest(self.headers.get("X-Ticketdepot-Token", ""), self.server.token)
            or (origin and origin not in self._own_origins())
        ):
            return self.send_error(403)
        method = self.path.removeprefix("/api/")
        api = self.server.api
        if method.startswith("_") or method in ("ticket_pdf", "proof", "calendar") or not callable(getattr(api, method, None)):
            return self.send_error(404)
        args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"[]")
        try:
            result, status = getattr(api, method)(*args), 200
        except Exception as e:  # surfaced in the UI
            result, status = {"error": f"{type(e).__name__}: {e}"}, 500
        self._send(status, json.dumps(result).encode(), "application/json")

    def _own_origins(self) -> tuple[str, ...]:
        port = self.server.port
        return (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _host_ok(self) -> bool:
        port = self.server.port
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _download(self, result: tuple[str, bytes] | None, content_type: str):
        if not result:
            return self.send_error(404)
        name, body = result
        ascii_name = name.encode("ascii", "replace").decode()
        disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
        self._send(200, body, content_type, {"Content-Disposition": disposition})

    def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, val in (headers or {}).items():
            self.send_header(k, val)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _safe(fn, *args):
    try:
        return fn(*args)
    except KeyError:
        return None
