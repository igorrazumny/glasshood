"""Host-routing wrapper factory (REQ-GHA-015).

Serves the architecture page at the ROOT of the `architecture.*` subdomain
(architecture.glasshood.ai -> the page, no /architecture/ suffix). For any other
host, or any path other than "/", this is a pure pass-through to the wrapped app.

Kept separate from src/api/server.py so the routing logic is unit-testable without
importing the full app. Mirrors TestRobin REQ-589 (xrobin backend/arch_subdomain.py).
"""
from starlette.responses import FileResponse


def make_app(inner, index_path):
    """Wrap an ASGI `inner` app so architecture.* '/' serves index_path.

    No file-existence guard: if index_path is missing (a packaging/path-drift bug),
    FileResponse raises -> a loud 500 on the architecture root, rather than silently
    falling through to `inner` and serving the SPA (No Silent Defaults).
    """
    index_path = str(index_path)

    async def app(scope, receive, send):
        if scope.get("type") == "http":
            headers = dict(scope.get("headers") or [])
            host = headers.get(b"host", b"").decode("latin-1").split(":")[0].lower()
            if host.startswith("architecture.") and scope.get("path") == "/":
                await FileResponse(index_path)(scope, receive, send)
                return
        await inner(scope, receive, send)

    return app
