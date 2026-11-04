# File: src/collectors/coldvault_mcp.py
# Purpose: REQ-GHA-020 — check ColdVault through its MCP server (ColdVault REQ-227).
#   check_attestation: the regular check. verify_attestation with a fresh nonce; healthy
#     only when the answer is verified AND bound to that nonce. Calls no model.
#   recheck_ask: on demand only, never scheduled. One short question through `ask`;
#     reports whether an answer came back, from which model and how fast. The answer
#     text is untrusted and is neither returned nor stored.

import binascii
import json
import secrets
import time

import httpx

from src.collectors.mcp_client import McpError, McpSession

ATTESTATION_SCOPE = ("Proves genuine AMD SEV-SNP hardware signed GlassHood's nonce; "
                     "does not prove that a given request ran there, or which code runs there.")
RECHECK_QUESTION = "Reply with the single word OK."
MODES = ("vault", "partner")


def _call(url: str, tool: str, args: dict, timeout_s: float):
    """(result, error reason, elapsed seconds). Exactly one of result and reason is set."""
    start = time.monotonic()
    try:
        with McpSession(url, timeout_s) as s:
            result = s.call_tool(tool, args)
    except McpError as e:
        return None, str(e), time.monotonic() - start
    except httpx.TimeoutException:
        return None, f"no answer within {timeout_s:g}s", time.monotonic() - start
    except httpx.HTTPError as e:
        return None, f"unreachable ({type(e).__name__})", time.monotonic() - start
    elapsed = time.monotonic() - start
    if result.get("isError"):
        return None, _text(result)[:200] or "the tool reported an error", elapsed
    return result, None, elapsed


def _text(result: dict) -> str:
    return "".join(c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict)).strip()


def _data(result: dict):
    """The tool's answer as data: structuredContent, else its text parsed as JSON."""
    sc = result.get("structuredContent")
    if isinstance(sc, dict):
        return sc
    try:
        return json.loads(_text(result))
    except ValueError:
        return None


def _bound_verdicts(obj, nonce: str):
    """Yield every object in the answer carrying a verdict, with whether it binds `nonce`."""
    if isinstance(obj, dict):
        if "verified" in obj:
            bound = obj.get("nonce") == nonce
            rd = obj.get("report_data_hex")
            if not bound and isinstance(rd, str):
                try:
                    bound = binascii.unhexlify(rd).rstrip(b"\0").decode() == nonce
                except (ValueError, UnicodeDecodeError):
                    pass
            yield obj.get("verified") is True, bound
        for v in obj.values():
            yield from _bound_verdicts(v, nonce)
    elif isinstance(obj, list):
        for v in obj:
            yield from _bound_verdicts(v, nonce)


def check_attestation(url: str, timeout_s: float = 30) -> dict:
    """{ok, desc, metrics} for the 'Confidential hardware' component."""
    nonce = secrets.token_hex(32)
    result, reason, elapsed = _call(url, "verify_attestation", {"nonce": nonce}, timeout_s)
    ms = round(elapsed * 1000)
    if reason:
        return {"ok": False, "desc": f"MCP verify_attestation failed: {reason}",
                "metrics": {"attested": 0, "probe_latency_ms": ms}}
    verdicts = list(_bound_verdicts(_data(result), nonce))
    if any(v is False for v, _ in verdicts):
        why = "ColdVault reported the attestation as not verified"
    elif not any(b for _, b in verdicts):
        why = "the answer was not bound to GlassHood's nonce" if verdicts else \
              "the answer carried no attestation verdict"
    else:
        return {"ok": True,
                "desc": f"MCP verify_attestation — verified for GlassHood's fresh nonce ({ms}ms). "
                        + ATTESTATION_SCOPE,
                "metrics": {"attested": 1, "probe_latency_ms": ms}}
    return {"ok": False, "desc": f"MCP verify_attestation: {why}. {_text(result)[:160]}".strip(),
            "metrics": {"attested": 0, "probe_latency_ms": ms}}


def recheck_ask(url: str, mode: str = "vault", timeout_s: float = 120) -> dict:
    """One question through `ask`. The answer text is not returned."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    result, reason, elapsed = _call(url, "ask", {"question": RECHECK_QUESTION, "mode": mode}, timeout_s)
    out = {"mode": mode, "elapsed_s": round(elapsed, 1), "checked_at": time.time()}
    if reason:
        return {**out, "ok": False, "reason": reason}
    data = _data(result)
    answer = data.get("answer") if isinstance(data, dict) else _text(result)
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        return {**out, "ok": False, "reason": "ColdVault returned no answer", "model": model}
    return {**out, "ok": True, "model": model, "answer_chars": len(answer)}
