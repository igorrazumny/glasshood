"""ASGI entrypoint (REQ-GHA-015).

Thin wiring: wrap src.api.server:app with the architecture-subdomain host router so
architecture.glasshood.ai serves the architecture page at its ROOT (clean URL, no
/architecture/ suffix). The page also stays reachable at /architecture on every host
via the normal static mount in server.py.

The routing logic + its tests live in src.api.arch_subdomain. The container entrypoint
(Dockerfile CMD) points uvicorn at `src.api.asgi:app`. For glasshood.ai (and any
non-architecture host) this is a pure pass-through — identical to src.api.server:app.
Mirrors TestRobin REQ-589 (xrobin backend/asgi.py).
"""
from pathlib import Path

from src.api.arch_subdomain import make_app
from src.api.server import app as _app

# Resolves to /app/architecture/index.html in the container (Dockerfile COPYs
# architecture/ -> /app/architecture) and to <repo>/architecture/index.html locally.
_ARCH_INDEX = Path(__file__).resolve().parents[2] / "architecture" / "index.html"

app = make_app(_app, _ARCH_INDEX)
