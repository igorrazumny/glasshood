"""Tests for the GlassHood MCP server (REQ-GHA-019), against a local stand-in for GlassHood."""

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import server as gh  # noqa: E402

TOPOLOGY = {"nodes": [{"id": "lb", "status": "healthy"}, {"id": "grok4", "status": "error"}],
            "edges": [{"from": "lb", "to": "grok4"}], "overall_status": "degraded"}
ANALYSIS = {"score": 7, "summary": "Partially degraded.", "issues": ["Grok 4: 503"], "stale": False}
LOGS = {"node_id": "grok4", "entries": [{"severity": "ERROR", "message": "HTTP 503"}], "count": 1}


class Fake:
    """Answers like GlassHood and its controller; records every request."""

    def __init__(self):
        self.routes = {"/api/demo/topology": (200, TOPOLOGY), "/api/demo/analysis": (200, ANALYSIS),
                       "/api/demo/logs/grok4": (200, LOGS), "/api/status": (200, {"state": "awake"})}
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                fake.requests.append((self.command, self.path))
                code, body = fake.routes.get(self.path, (404, {"detail": "Not Found"}))
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _answer

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setenv("GLASSHOOD_URL", f.url)
    monkeypatch.setenv("GLASSHOOD_CONTROLLER", f.url + "/api")
    yield f
    f.httpd.shutdown()


def call(name, args=None, target=None):
    async def go():
        async with Client(target or gh.server) as c:
            return await c.call_tool(name, args or {})
    return asyncio.run(go())


def text(result):
    return "".join(getattr(c, "text", "") for c in result.content)


def payload(result):
    assert not result.is_error, text(result)
    return json.loads(text(result))


def test_three_read_only_tools():
    async def go():
        async with Client(gh.server) as c:
            return (await c.list_tools()).tools
    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == {"get_topology", "get_impact_analysis", "get_node_logs"}
    for t in tools.values():
        assert t.annotations.read_only_hint is True
        assert t.annotations.destructive_hint is False


def test_answers_are_glasshoods_data_unchanged(fake):
    assert payload(call("get_topology")) == TOPOLOGY
    assert payload(call("get_impact_analysis")) == ANALYSIS
    assert payload(call("get_node_logs", {"node_id": "grok4"})) == LOGS


def test_only_reads(fake):
    call("get_topology")
    call("get_impact_analysis")
    call("get_node_logs", {"node_id": "grok4"})
    fake.routes["/api/demo/topology"] = (403, {"detail": "Forbidden"})
    call("get_topology")
    assert fake.requests and all(m == "GET" for m, _ in fake.requests)
    assert all(p.startswith("/api/demo/") or p == "/api/status" for _, p in fake.requests)


def test_unknown_node_is_refused_not_made_up(fake):
    r = call("get_node_logs", {"node_id": "nope"})
    assert r.is_error
    assert "nope" in text(r) and "grok4" in text(r)
    assert ("GET", "/api/demo/logs/nope") not in fake.requests


def test_never_cached(fake):
    payload(call("get_impact_analysis"))
    newer = dict(ANALYSIS, score=9)
    fake.routes["/api/demo/analysis"] = (200, newer)
    assert payload(call("get_impact_analysis")) == newer


def test_asleep_says_so_and_names_the_wake_page(fake):
    fake.routes["/api/demo/topology"] = (403, {"detail": "Forbidden"})
    fake.routes["/api/status"] = (200, {"state": "asleep"})
    r = call("get_topology")
    assert r.is_error
    assert "GlassHood is asleep" in text(r) and "https://app.glasshood.ai" in text(r)
    assert "did not answer" not in text(r)


def test_unreachable_says_so_and_names_the_wake_page(monkeypatch):
    monkeypatch.setenv("GLASSHOOD_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("GLASSHOOD_CONTROLLER", "http://127.0.0.1:9/api")
    r = call("get_impact_analysis")
    assert r.is_error
    assert "did not answer" in text(r) and "https://app.glasshood.ai" in text(r)
    assert "GlassHood is asleep" not in text(r)


def test_not_json_is_an_error_not_data(fake):
    fake.routes["/api/demo/analysis"] = (200, b"<html>maintenance</html>")
    r = call("get_impact_analysis")
    assert r.is_error and "not valid JSON" in text(r)


def test_works_over_stdio_as_installed(fake):
    params = StdioServerParameters(command=sys.executable, args=[str(HERE / "server.py")],
                                   env={**os.environ, "GLASSHOOD_URL": fake.url})
    assert payload(call("get_node_logs", {"node_id": "grok4"}, target=params)) == LOGS
