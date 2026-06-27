"""REQ-GHA-015: tests for the architecture-subdomain host router (src.api.arch_subdomain).

src.api.asgi makes this the production entrypoint, so the routing contract is tested
here. Driven via RAW ASGI (no TestClient/httpx dependency) and a tiny stub inner app —
src.api.server is NOT imported. Mirrors TestRobin REQ-589 (xrobin test_arch_subdomain).
"""
import asyncio

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from src.api.arch_subdomain import make_app

ARCH_HOST = "architecture.glasshood.ai"
MAIN_HOST = "glasshood.ai"


def _stub_inner():
    async def root(_req):
        return PlainTextResponse("INNER-ROOT")

    async def asset(_req):
        return PlainTextResponse("INNER-ASSET")

    return Starlette(routes=[Route("/", root), Route("/architecture/styles.css", asset)])


def _scope(host, path):
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", host.encode())],
        "server": ("testserver", 80),
        "client": ("test", 12345),
    }


def _run(app, host, path):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(_scope(host, path), receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], body


def test_architecture_root_serves_the_page(tmp_path):
    idx = tmp_path / "index.html"
    idx.write_text("<title>ARCH PAGE</title>")
    status, body = _run(make_app(_stub_inner(), idx), ARCH_HOST, "/")
    assert status == 200
    assert b"ARCH PAGE" in body  # the file, not the inner app


def test_architecture_host_with_port_routes(tmp_path):
    idx = tmp_path / "index.html"
    idx.write_text("<title>ARCH PAGE</title>")
    status, body = _run(make_app(_stub_inner(), idx), f"{ARCH_HOST}:443", "/")
    assert status == 200
    assert b"ARCH PAGE" in body


def test_architecture_non_root_path_passes_through(tmp_path):
    idx = tmp_path / "index.html"
    idx.write_text("x")
    status, body = _run(make_app(_stub_inner(), idx), ARCH_HOST, "/architecture/styles.css")
    assert status == 200
    assert body == b"INNER-ASSET"


def test_non_architecture_host_passes_through(tmp_path):
    idx = tmp_path / "index.html"
    idx.write_text("x")
    status, body = _run(make_app(_stub_inner(), idx), MAIN_HOST, "/")
    assert status == 200
    assert body == b"INNER-ROOT"


def test_missing_page_fails_loud_not_silent(tmp_path):
    # No Silent Defaults: a missing page must raise (loud), NOT fall through and
    # silently serve the SPA on the architecture host.
    app = make_app(_stub_inner(), tmp_path / "nope.html")
    with pytest.raises((RuntimeError, FileNotFoundError, OSError)):
        _run(app, ARCH_HOST, "/")
