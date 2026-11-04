# File: src/collectors/mcp_client.py
# Purpose: REQ-GHA-020 — a small MCP client over the Streamable HTTP transport.
# GlassHood only needs to call a remote server's tools, so this speaks just that part
# of the protocol: initialize, notifications/initialized, tools/call, and closing the
# session. Answers may come back as plain JSON or as a server-sent event stream.

import json

import httpx

PROTOCOL_VERSION = "2025-06-18"


class McpError(Exception):
    """The server did not answer as MCP requires; the message says why."""


class McpSession:
    """One MCP session: `with McpSession(url) as s: s.call_tool(name, args)`."""

    def __init__(self, url: str, timeout_s: float = 30):
        self.url = url
        self._http = httpx.Client(timeout=timeout_s, follow_redirects=False)
        self._session_id = None
        self._protocol = None
        self._next_id = 0

    def __enter__(self):
        try:
            result = self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "glasshood", "version": "1"},
            })
            self._protocol = result.get("protocolVersion") or PROTOCOL_VERSION
            self._notify("notifications/initialized")
        except BaseException:
            self._http.close()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self._session_id:
                self._http.delete(self.url, headers=self._headers())
        except httpx.HTTPError:
            pass
        finally:
            self._http.close()

    def call_tool(self, name: str, arguments: dict) -> dict:
        """The tool's result: {content, structuredContent?, isError?}."""
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def _headers(self) -> dict:
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        if self._protocol:
            h["MCP-Protocol-Version"] = self._protocol
        return h

    def _notify(self, method: str):
        r = self._http.post(self.url, json={"jsonrpc": "2.0", "method": method}, headers=self._headers())
        if r.status_code not in (200, 202, 204):
            raise McpError(f"HTTP {r.status_code} on {method}")

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        rid = self._next_id
        r = self._http.post(self.url, json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
                            headers=self._headers())
        if r.status_code != 200:
            raise McpError(f"HTTP {r.status_code} on {method}")
        if method == "initialize":
            self._session_id = r.headers.get("mcp-session-id")
        msg = _find_response(r, rid)
        if msg is None:
            raise McpError(f"no answer to {method}")
        if "error" in msg:
            err = msg["error"] or {}
            raise McpError(f"MCP error {err.get('code')}: {str(err.get('message', ''))[:160]}")
        result = msg.get("result")
        if not isinstance(result, dict):
            raise McpError(f"malformed answer to {method}")
        return result


def _find_response(r: httpx.Response, rid: int):
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype == "application/json":
        try:
            return _match(r.json(), rid)
        except ValueError:
            raise McpError("answer was not valid JSON") from None
    if ctype == "text/event-stream":
        data = []
        for line in r.text.splitlines() + [""]:
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line == "" and data:
                try:
                    found = _match(json.loads("\n".join(data)), rid)
                except ValueError:
                    found = None
                if found is not None:
                    return found
                data = []
        return None
    raise McpError(f"unexpected content type {ctype or 'none'}")


def _match(payload, rid):
    for m in payload if isinstance(payload, list) else [payload]:
        if isinstance(m, dict) and m.get("id") == rid and ("result" in m or "error" in m):
            return m
    return None
