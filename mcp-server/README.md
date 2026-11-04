# GlassHood MCP server

Lets an AI assistant read GlassHood's public demo through the [Model Context Protocol](https://modelcontextprotocol.io) (REQ-GHA-019).

| Tool | Returns |
|---|---|
| `get_topology` | Every node of the demo estate with its status, metrics and diagnostics, the edges between nodes, and the overall status. |
| `get_impact_analysis` | GlassHood's analysis of the estate: a health score, a summary, the open issues and the recommended actions. |
| `get_node_logs(node_id)` | Recent log entries of one node. `node_id` comes from `get_topology`. |

- **Read-only.** Every tool sends one or two GET requests to GlassHood's public demo endpoints and nothing else. No login, key or customer data is involved.
- **Unchanged and current.** Answers are GlassHood's own responses, passed through as they are and never cached. An unknown node id is refused rather than answered with a placeholder.
- **Asleep.** GlassHood sleeps when nobody uses it. A tool called then says so, and that opening <https://app.glasshood.ai> in a browser wakes it.

The demo is a curated sample estate, not a customer's live systems.

## Install (about two minutes)

Needs Python 3.10 or newer.

```
git clone https://github.com/igorrazumny/glasshood.git
cd glasshood/mcp-server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then add the server to your MCP client. For Claude Desktop, Cursor and most other clients, that is an entry under `mcpServers` in the client's MCP configuration file, with absolute paths:

```json
{
  "mcpServers": {
    "glasshood": {
      "command": "/path/to/glasshood/mcp-server/.venv/bin/python",
      "args": ["/path/to/glasshood/mcp-server/server.py"]
    }
  }
}
```

Restart the client and ask, for example: *"Using GlassHood, which part of the demo estate is failing, and what does it mean for the business?"*

## Settings

| Variable | Default |
|---|---|
| `GLASSHOOD_URL` | GlassHood's app address |
| `GLASSHOOD_CONTROLLER` | GlassHood's wake controller, asked only when the app does not answer |

## Tests

```
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

The tests run against a local stand-in for GlassHood and also start the server over stdio, as a client would.
