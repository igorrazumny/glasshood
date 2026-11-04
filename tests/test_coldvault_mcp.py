# File: tests/test_coldvault_mcp.py
# Purpose: REQ-GHA-020 — checking ColdVault through its MCP server: the MCP client,
# the scheduled attestation check, the on-demand recheck and its endpoint.
# The stand-in speaks MCP's Streamable HTTP transport (JSON or event-stream answers).

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from src.collectors import coldvault_mcp as cm
from src.collectors.manifest_metrics import _poll_node
from src.collectors.mcp_client import McpError, McpSession


class FakeColdVault:
    """A ColdVault MCP stand-in. Tools are plain functions of the arguments."""

    def __init__(self):
        self.sse = False
        self.http_status = 200
        self.calls = []          # (tool, arguments)
        self.methods = []
        self.tools = {
            "verify_attestation": lambda a: {"verified": True, "nonce": a.get("nonce"), "summary": "ok"},
            "ask": lambda a: {"answer": "OK", "model": "vault-model"},
        }
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_DELETE(self):
                fake.methods.append("DELETE")
                self.send_response(200)
                self.end_headers()

            def do_POST(self):
                msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.methods.append(msg.get("method"))
                if fake.http_status != 200:
                    return self._send(fake.http_status, {"detail": "Method Not Allowed"})
                if "id" not in msg:
                    self.send_response(202)
                    self.end_headers()
                    return
                if msg["method"] == "initialize":
                    return self._reply(msg["id"], {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                                                   "serverInfo": {"name": "fake", "version": "0"}},
                                       session="s-1")
                if self.headers.get("Mcp-Session-Id") != "s-1":
                    return self._send(400, {"detail": "no session"})
                if msg["method"] != "tools/call":
                    return self._send(200, {"jsonrpc": "2.0", "id": msg["id"],
                                            "error": {"code": -32601, "message": "Method not found"}})
                name, args = msg["params"]["name"], msg["params"]["arguments"]
                fake.calls.append((name, args))
                fn = fake.tools.get(name)
                try:
                    out = fn(args) if fn else None
                    result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": fn is None}
                    if fn is None:
                        result["content"][0]["text"] = f"Unknown tool: {name}"
                except Exception as e:
                    result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
                self._reply(msg["id"], result)

            def _reply(self, rid, result, session=None):
                body = {"jsonrpc": "2.0", "id": rid, "result": result}
                if fake.sse:
                    data = (f"event: message\ndata: {json.dumps(body)}\n\n").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                else:
                    data = json.dumps(body).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                if session:
                    self.send_header("Mcp-Session-Id", session)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/api/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def cv():
    f = FakeColdVault()
    yield f
    f.httpd.shutdown()


# --- the client ---

@pytest.mark.parametrize("sse", [False, True])
def test_client_handshake_and_call(cv, sse):
    cv.sse = sse
    with McpSession(cv.url) as s:
        r = s.call_tool("ask", {"question": "q", "mode": "vault"})
    assert json.loads(r["content"][0]["text"])["model"] == "vault-model"
    assert cv.methods == ["initialize", "notifications/initialized", "tools/call", "DELETE"]


def test_client_reports_http_refusal(cv):
    cv.http_status = 405
    with pytest.raises(McpError, match="HTTP 405"):
        with McpSession(cv.url):
            pass


# --- the scheduled attestation check ---

@pytest.mark.parametrize("sse", [False, True])
def test_attested_when_verified_for_our_nonce(cv, sse):
    cv.sse = sse
    r = cm.check_attestation(cv.url)
    assert r["ok"] is True and r["metrics"]["attested"] == 1
    assert "does not prove that a given request ran there" in r["desc"]


def test_fresh_nonce_each_check(cv):
    cm.check_attestation(cv.url)
    cm.check_attestation(cv.url)
    nonces = [a["nonce"] for t, a in cv.calls if t == "verify_attestation"]
    assert len(nonces) == 2 and nonces[0] != nonces[1] and len(nonces[0]) == 64


def test_bound_through_report_data(cv):
    cv.tools["verify_attestation"] = lambda a: {"attestation": {
        "verified": True, "report_data_hex": a["nonce"].encode().hex()}}
    assert cm.check_attestation(cv.url)["ok"] is True


@pytest.mark.parametrize("answer, why", [
    (lambda a: {"verified": True, "nonce": "0" * 64}, "not bound to GlassHood's nonce"),
    (lambda a: {"verified": False, "nonce": a["nonce"]}, "not verified"),
    (lambda a: {"verified": "true", "nonce": a["nonce"]}, "not verified"),
    (lambda a: {"summary": "all good"}, "no attestation verdict"),
    (lambda a: [{"verified": True, "nonce": a["nonce"]}, {"verified": False, "nonce": a["nonce"]}], "not verified"),
])
def test_anything_else_is_an_error(cv, answer, why):
    cv.tools["verify_attestation"] = answer
    r = cm.check_attestation(cv.url)
    assert r["ok"] is False and r["metrics"]["attested"] == 0
    assert why in r["desc"]


def test_tool_failure_reason_is_shown(cv):
    def boom(a):
        raise RuntimeError("SNP firmware unavailable")
    cv.tools["verify_attestation"] = boom
    r = cm.check_attestation(cv.url)
    assert r["ok"] is False and "SNP firmware unavailable" in r["desc"]


def test_unreachable_and_refused_are_errors(cv):
    r = cm.check_attestation("http://127.0.0.1:9/api/mcp", timeout_s=3)
    assert r["ok"] is False and "unreachable" in r["desc"]
    cv.http_status = 405
    r = cm.check_attestation(cv.url)
    assert r["ok"] is False and "HTTP 405" in r["desc"]


def test_poll_node_maps_the_check(cv):
    node = {"id": "cv-hw", "monitoring": {"probe": {"type": "mcp_attestation", "url": cv.url}}}
    out = _poll_node(node)
    assert out["status"] == "healthy" and out["metrics"]["attested"] == 1
    cv.tools["verify_attestation"] = lambda a: {"verified": False}
    assert _poll_node(node)["status"] == "error"


def test_scheduled_checks_never_ask(cv):
    node = {"id": "cv-hw", "monitoring": {"probe": {"type": "mcp_attestation", "url": cv.url},
                                          "recheck": {"type": "mcp_ask", "url": cv.url}}}
    _poll_node(node)
    _poll_node(node)
    assert [t for t, _ in cv.calls] == ["verify_attestation", "verify_attestation"]


# --- the on-demand recheck ---

def test_recheck_reports_model_and_time_not_text(cv):
    r = cm.recheck_ask(cv.url, "vault")
    assert r["ok"] is True and r["model"] == "vault-model" and r["mode"] == "vault"
    assert "OK" not in json.dumps({k: v for k, v in r.items() if k != "ok"})
    assert cv.calls == [("ask", {"question": cm.RECHECK_QUESTION, "mode": "vault"})]


def test_recheck_failure_and_empty_answer(cv):
    def fail(a):
        raise RuntimeError("All models failed to respond.")
    cv.tools["ask"] = fail
    r = cm.recheck_ask(cv.url)
    assert r["ok"] is False and "All models failed" in r["reason"]
    cv.tools["ask"] = lambda a: {"answer": "  ", "model": "m"}
    assert cm.recheck_ask(cv.url)["ok"] is False


def test_recheck_mode_is_checked():
    with pytest.raises(ValueError):
        cm.recheck_ask("http://x", "public")


# --- the endpoint ---

@pytest.fixture
def api(cv, tmp_path, monkeypatch):
    manifest = {"schema_version": 2, "solution": "ColdVault", "product": "coldvault", "environments": [{
        "environment": "prod", "nodes": [
            {"id": "cv-api", "label": "ColdVault API",
             "monitoring": {"recheck": {"type": "mcp_ask", "url": cv.url}}},
            {"id": "cv-web", "label": "Website", "monitoring": {}}]}]}
    (tmp_path / "coldvault.yaml").write_text(yaml.safe_dump(manifest))
    monkeypatch.setattr("src.api.routes.manifests.MANIFEST_DIR", tmp_path)
    import src.api.routes.mcp_recheck as rc
    monkeypatch.setattr(rc, "_last_start", 0.0)
    from src.api.routes.auth import _make_access_token
    from src.api.server import app
    client = TestClient(app)

    def post(node, role="operator", **body):
        h = {"Authorization": f"Bearer {_make_access_token('u@example.com', role)}"} if role else {}
        return client.post(f"/api/mcp-recheck/{node}", json=body, headers=h)
    return post


def test_endpoint_operator_rechecks(api, cv):
    r = api("cv-api", mode="vault")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["model"] == "vault-model"


def test_endpoint_refuses_demo_and_anonymous(api, cv):
    assert api("cv-api", role="viewer").status_code == 403
    assert api("cv-api", role=None).status_code == 401
    assert cv.calls == []


def test_endpoint_only_uses_the_manifest_url(api, cv):
    assert api("cv-web").status_code == 404
    assert api("nope").status_code == 404
    assert api("cv-api", url="http://127.0.0.1:9/evil").json()["ok"] is True


def test_endpoint_bad_mode_and_rate_limit(api, cv):
    assert api("cv-api", mode="public").status_code == 400
    assert api("cv-api", mode="partner").status_code == 200
    second = api("cv-api")
    assert second.status_code == 429 and "Next recheck" in second.json()["detail"]
    assert [a["mode"] for t, a in cv.calls] == ["partner"]
