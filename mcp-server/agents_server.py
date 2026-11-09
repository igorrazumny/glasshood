"""GlassHood MCP server for agents (REQ-GHA-049).

An agent connects with its own credential and reads what GlassHood's monitoring says about every
system. The agent responsible for a system can also read its full setup, verify it and submit
corrections, which an operator applies. Nothing else can be changed through it.

Run: GLASSHOOD_AGENT_KEY=... python agents_server.py   (stdio; see README.md)
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

DEFAULT_APP = "https://glasshood.wittysmoke-13e0c5ee.switzerlandnorth.azurecontainerapps.io"
TIMEOUT = 60

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
FEED = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True)
SUBMIT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)

server = MCPServer(
    name="glasshood-agents",
    title="GlassHood for agents",
    instructions=(
        "GlassHood's live monitoring of the systems. Start with list_systems. Every answer carries the time it was "
        "evaluated; if a tool reports an error, GlassHood's data was not read, so do not assume anything about the system. "
        "If you are responsible for a system, verify_setup compares what GlassHood expects with what it last found."
    ),
)


def _call(path, method="GET", body=None):
    key = os.environ.get("GLASSHOOD_AGENT_KEY", "")
    if not key:
        raise ToolError("GLASSHOOD_AGENT_KEY is not set for this MCP server.")
    url = os.environ.get("GLASSHOOD_URL", DEFAULT_APP).rstrip("/") + path
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Agent-Key": key, "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("detail")
        except ValueError:
            detail = None
        raise ToolError(f"GlassHood answered HTTP {e.code}: {detail or e.reason}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ToolError(f"GlassHood did not answer ({getattr(e, 'reason', None) or type(e).__name__}); its state is unknown.") from None
    except ValueError:
        raise ToolError("GlassHood's answer was not valid JSON; its state is unknown.") from None


def _q(value):
    return urllib.parse.quote(value, safe="")


@server.tool(annotations=READ)
def list_systems() -> dict:
    """Every monitored system with its name, group, status and responsible agent."""
    return _call("/api/agents/systems")


@server.tool(annotations=READ)
def get_system(system: str) -> dict:
    """One system (its id from list_systems): latest AI review, score, open alerts and components."""
    return _call(f"/api/agents/systems/{_q(system)}")


@server.tool(annotations=READ)
def get_component_logs(system: str, component: str) -> dict:
    """Recent log lines of one component of a system."""
    return _call(f"/api/agents/systems/{_q(system)}/logs/{_q(component)}")


@server.tool(annotations=FEED)
def get_changes(system: str = "") -> dict:
    """What changed since your last call with the same scope: new alerts, ended alerts and status changes,
    for one system or, with no system, for all. Each change is returned once."""
    return _call("/api/agents/changes" + (f"?system={_q(system)}" if system else ""))


@server.tool(annotations=READ)
def get_setup(system: str) -> dict:
    """Responsible agent only: everything GlassHood holds about your system, without credential values."""
    return _call(f"/api/agents/systems/{_q(system)}/setup")


@server.tool(annotations=READ)
def verify_setup(system: str) -> dict:
    """Responsible agent only: per component, what GlassHood expects and what it last found. Components it
    could not confirm are listed; compare the rest with your current implementation."""
    return _call(f"/api/agents/systems/{_q(system)}/verify")


@server.tool(annotations=SUBMIT)
def submit_correction(system: str, kind: str, component: str, description: str, evidence: str) -> dict:
    """Responsible agent only: report a difference between GlassHood's setup and the real system. kind is
    no_longer_exists, missing or described_wrongly. An operator applies it; it changes nothing by itself."""
    return _call(f"/api/agents/systems/{_q(system)}/corrections", "POST",
                 {"kind": kind, "component": component, "description": description, "evidence": evidence})


if __name__ == "__main__":
    server.run()
