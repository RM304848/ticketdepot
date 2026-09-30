"""The local server: only our own page may call the API; downloads come as attachments."""

import http.client
import json
import re
import threading

import pytest

from ticketdepot.api import Api
from ticketdepot.server import Server


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKETDEPOT_DATA", str(tmp_path / "data"))
    srv = Server(Api(), 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(srv, method, path, body=None, headers=None, host=None):
    con = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    con.putrequest(method, path, skip_host=True)
    con.putheader("Host", host or f"127.0.0.1:{srv.port}")
    data = json.dumps(body).encode() if body is not None else b""
    for k, v in {"Content-Length": str(len(data)), **(headers or {})}.items():
        con.putheader(k, v)
    con.endheaders(data)
    res = con.getresponse()
    return res.status, dict(res.getheaders()), res.read()


def test_page_carries_token_and_version(server):
    status, _, body = request(server, "GET", "/")
    assert status == 200
    assert re.search(rb'name="csrf" content="([^"]+)"', body)[1].decode() == server.token
    assert b"{{VERSION}}" not in body


def test_api_needs_the_token(server):
    assert request(server, "POST", "/api/overview", [])[0] == 403
    status, _, body = request(server, "POST", "/api/overview", [], {"X-Ticketdepot-Token": server.token})
    assert status == 200 and json.loads(body)["journeys"] == []


def test_foreign_host_and_origin_are_rejected(server):
    assert request(server, "GET", "/", host="evil.example")[0] == 403
    headers = {"X-Ticketdepot-Token": server.token, "Origin": "https://evil.example"}
    assert request(server, "POST", "/api/overview", [], headers)[0] == 403


def test_internal_methods_are_not_callable(server):
    headers = {"X-Ticketdepot-Token": server.token}
    for method in ("_view", "proof", "calendar", "ticket_pdf"):
        assert request(server, "POST", f"/api/{method}", [1], headers)[0] == 404


def test_ping_and_bulk_calendar(server):
    assert json.loads(request(server, "GET", "/api/ping")[2])["app"] == "ticketdepot"
    status, headers, body = request(server, "GET", "/ics/alle.ics")
    assert status == 200 and headers["Content-Disposition"].startswith("attachment;")
    assert body.startswith(b"BEGIN:VCALENDAR\r\n")


def test_unknown_downloads_404(server):
    assert request(server, "GET", "/proof/999.pdf")[0] == 404
    assert request(server, "GET", "/ticket/1.pdf")[0] == 404
    assert request(server, "GET", "/../ticketdepot/api.py")[0] == 404


def test_quit_needs_the_token_and_stops_the_server(server):
    quit_called = threading.Event()
    server.on_quit = quit_called.set
    assert request(server, "POST", "/api/quit", [])[0] == 403
    assert not quit_called.wait(0.6)
    status, _, body = request(server, "POST", "/api/quit", [], {"X-Ticketdepot-Token": server.token})
    assert status == 200 and json.loads(body) is True
    assert quit_called.wait(2)


def test_quit_really_ends_serve_forever(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKETDEPOT_DATA", str(tmp_path / "data"))
    srv = Server(Api(), 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    assert request(srv, "POST", "/api/quit", [], {"X-Ticketdepot-Token": srv.token})[0] == 200
    t.join(3)
    assert not t.is_alive()
    srv.server_close()
