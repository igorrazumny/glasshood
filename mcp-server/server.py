"""GlassHood MCP server (REQ-GHA-019).

Lets any MCP client read GlassHood's public demo: the integration topology,
the business-impact analysis and one node's recent logs. Read-only, demo only:
no login, no key, no customer data. Every answer is GlassHood's own response,
passed through unchanged and never cached.

Run: python server.py   (stdio; see README.md)
"""

import json
import os
import urllib.error
import urllib.request

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

DEFAULT_APP = "https://glasshood.wittysmoke-13e0c5ee.switzerlandnorth.azurecontainerapps.io"
DEFAULT_CONTROLLER = "https://func-glasshood-wake.azurewebsites.net/api"
WAKE_URL = "https://app.glasshood.ai"
TIMEOUT = 15

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=True)

server = MCPServer(
    name="glasshood",
    title="GlassHood demo",
    instructions=(
        "GlassHood monitors integration chains and explains their health in business terms. "
        "These tools read GlassHood's public demo, a curated sample estate, not a customer's "
        "live systems. Say so when you present the data."
    ),
    website_url="https://glasshood.ai",
)


def _app_url():
    return os.environ.get("GLASSHOOD_URL", DEFAULT_APP).rstrip("/")


def _controller_url():
    return os.environ.get("GLASSHOOD_CONTROLLER", DEFAULT_CONTROLLER).rstrip("/")


def _get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def _unavailable(reason):
    """Explain why GlassHood did not answer, asking its wake controller whether it is asleep."""
    try:
        state = _get_json(_controller_url() + "/status").get("state")
    except Exception:
        state = None
    if state in ("asleep", "going-to-sleep", "waking"):
        return (f"GlassHood is {state.replace('-', ' ')} and cannot answer now. "
                f"Opening {WAKE_URL} in a browser wakes it; ask again once it has loaded.")
    return (f"GlassHood did not answer ({reason}). It may be asleep: opening {WAKE_URL} "
            f"in a browser wakes it; ask again once it has loaded.")


def _demo(path):
    try:
        return _get_json(_app_url() + "/api/demo/" + path)
    except urllib.error.HTTPError as e:
        raise ToolError(_unavailable(f"HTTP {e.code}")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ToolError(_unavailable(getattr(e, "reason", None) or type(e).__name__)) from None
    except ValueError:
        raise ToolError(_unavailable("the answer was not valid JSON")) from None


@server.tool(annotations=READ_ONLY)
def get_topology() -> dict:
    """The demo estate's integration topology: every node with its status, metrics and
    diagnostics, the edges between nodes, and the overall status."""
    return _demo("topology")


@server.tool(annotations=READ_ONLY)
def get_impact_analysis() -> dict:
    """GlassHood's analysis of the demo estate: a health score, a summary, the open issues
    and the recommended actions."""
    return _demo("analysis")


@server.tool(annotations=READ_ONLY)
def get_node_logs(node_id: str) -> dict:
    """Recent log entries of one node in the demo estate. node_id is a node's id from
    get_topology, for example "grok4"."""
    ids = [n.get("id") for n in _demo("topology").get("nodes", [])]
    if node_id not in ids:
        # The demo answers any id with a placeholder line; refuse instead of passing that on.
        raise ToolError(f"No node {node_id!r} in the demo topology. Known ids: {', '.join(ids)}.")
    return _demo("logs/" + urllib.request.quote(node_id, safe=""))


if __name__ == "__main__":
    server.run()
