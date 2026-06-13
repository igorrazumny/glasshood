# File: src/api/routes/logs.py
# Purpose: GET /api/logs/{node_id} — real GCP Cloud Logging for any topology node.
# REQ-704: filter+project are derived server-side from node_id via the compiled
# manifest. Client-supplied log_filter / log_project query parameters are
# IGNORED with a warning log (kept in the signature for one transition window
# so existing callers that still send them get a clean 200, not a 422).
# REQ-212: when a node exists in the manifest but does not declare
# monitoring.logs, fall back to the project-scoped gce_instance default so the
# modal still shows real entries — never an attacker-supplied project.

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request

from src.api.routes.auth import verify_token
from src.config.settings import GCP_PROJECT_ID

router = APIRouter(tags=["logs"])
logger = logging.getLogger(__name__)

# REQ-212: default applied when a node exists in the manifest but does NOT
# declare monitoring.logs (e.g. LB without exported access logs). Always
# scoped to GCP_PROJECT_ID — never an arbitrary project.
DEFAULT_FILTER = 'resource.type="gce_instance"'


def _query_logs_with_filter(project: str, log_filter: str, max_entries: int = 100) -> list[dict]:
    """Query GCP Cloud Logging with an explicit filter and project.

    REQ-705: the manifest-supplied filter is wrapped in parentheses so an
    `OR` clause inside the manifest filter cannot cause the trailing
    `AND timestamp>=...` to bind looser than expected and return entries
    outside the intended one-hour window.
    """
    from google.cloud.logging_v2 import Client

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    filter_str = f'({log_filter}) AND timestamp>="{cutoff.isoformat()}"'

    client = Client(project=project)
    entries = list(client.list_entries(
        filter_=filter_str,
        order_by="timestamp desc",
        max_results=max_entries,
    ))

    results = []
    for entry in entries:
        payload = ""
        if isinstance(entry.payload, dict):
            payload = entry.payload.get("message", str(entry.payload))
        elif entry.payload:
            payload = str(entry.payload)
        results.append({
            "timestamp": str(entry.timestamp),
            "severity": entry.severity or "DEFAULT",
            "message": payload[:500],
        })
    return results


def _walk_node(node: dict, target_id: str) -> dict | None:
    """Depth-first search through a node's compiled `children` for target_id."""
    if not isinstance(node, dict):
        return None
    if node.get("id") == target_id:
        return node
    for child in (node.get("children") or []):
        found = _walk_node(child, target_id)
        if found:
            return found
    return None


def _find_in_manifests(compiled: list, node_id: str) -> dict | None:
    """Find a node by id across all compiled manifests' top-level nodes + children."""
    for m in compiled:
        for n in (m.get("nodes") or []):
            found = _walk_node(n, node_id)
            if found:
                return found
    return None


def _resolve_node(node_id: str) -> tuple[str, str | None, str | None]:
    """Resolve (status, project, filter) for node_id via manifest + discovery cache.

    Returns one of:
      ("manifest_logs", project, filter)   — node declares monitoring.logs
      ("manifest_default", GCP_PROJECT_ID, DEFAULT_FILTER)
                                            — node exists but no logs declared
      ("discovered_vm", project, filter)   — runtime VM resolved via parent's
                                            children_template
      ("unknown", None, None)              — id not in any manifest or cache
    """
    # Lazy imports keep the route importable in test contexts that mock these.
    from src.manifest_compiler import compile_all
    from src.api.routes.manifests import _load_manifests
    from src.collectors import manifest_metrics

    compiled = compile_all(_load_manifests())

    # 1) Static manifest node (top-level or compiled child).
    found = _find_in_manifests(compiled, node_id)
    if found is not None:
        logs = (found.get("monitoring") or {}).get("logs") or []
        if logs and logs[0].get("filter") and logs[0].get("project"):
            return ("manifest_logs", logs[0]["project"], logs[0]["filter"])
        return ("manifest_default", GCP_PROJECT_ID, DEFAULT_FILTER)

    # 2) Runtime-discovered VM child resolved via parent's children_template.
    #    Note on trust: manifest_metrics._metrics_cache is only populated by
    #    internal discovery code paths (gcp_assets + MIG listManagedInstances
    #    + manifest_compiler) — there is no client-facing write path. We
    #    trust a cache hit for the parent_id AND for the instance_id metadata
    #    that gets template-interpolated into {vm_id}; both come from
    #    authenticated GCP API calls inside our trust boundary. The filter
    #    structure itself still comes from the manifest template, never from
    #    the cache entry directly.
    cached = manifest_metrics.get_node_status(node_id)
    if cached and cached.get("_parent"):
        parent_id = cached["_parent"]
        template = manifest_metrics.get_children_template(parent_id)
        if template:
            stripped = node_id[3:] if node_id.startswith("vm-") else node_id
            for tmpl in template:
                suffix = tmpl.get("id_suffix", "")
                # Empty suffix = template applies to the bare "vm-{vm_name}"
                # id. Non-empty suffix must match by endswith.
                if suffix:
                    if not stripped.endswith(suffix):
                        continue
                    vm_name = stripped[: -len(suffix)]
                else:
                    vm_name = stripped
                resolved = manifest_metrics.resolve_children_template(
                    [tmpl], vm_name, cached.get("instance_id", ""))
                if resolved:
                    mon = resolved[0].get("monitoring", {})
                    logs = mon.get("logs") or []
                    if logs and logs[0].get("filter") and logs[0].get("project"):
                        return ("discovered_vm", logs[0]["project"], logs[0]["filter"])
            # No template matched — inherit logs from the parent manifest node.
            parent_node = _find_in_manifests(compiled, parent_id)
            if parent_node:
                p_logs = (parent_node.get("monitoring") or {}).get("logs") or []
                if p_logs and p_logs[0].get("filter") and p_logs[0].get("project"):
                    return ("discovered_vm", p_logs[0]["project"], p_logs[0]["filter"])
        # Known runtime node but no template logs → safe project-scoped default.
        return ("manifest_default", GCP_PROJECT_ID, DEFAULT_FILTER)

    return ("unknown", None, None)


@router.get("/api/logs/{node_id}")
async def get_logs(node_id: str, request: Request, lines: int = 100,
                   log_filter: str = None, log_project: str = None):
    """Return recent logs for a topology node.

    REQ-704: log_filter and log_project query parameters are accepted-and-ignored
    for one transition window so existing callers that still pass them get a
    clean 200 (not FastAPI's 422 "unexpected query parameter"). The backend
    resolves the GCP filter + project from node_id via the compiled manifest.

    TODO(neo, after 2026-06-30): the FE in this codebase already stopped
    sending log_filter / log_project (LogViewerModal, 2026-05-22). After one
    month of cache invalidation and any external caller cleanup, drop both
    parameters from the signature entirely so a stray ?log_filter=... starts
    returning 422 instead of being silently ignored.
    """
    verify_token(request)

    if log_filter is not None or log_project is not None:
        logger.warning(
            "REQ-704: ignoring client-supplied log_filter/log_project for "
            f"node_id={node_id!r} — filter+project are derived server-side"
        )

    status, project, resolved_filter = _resolve_node(node_id)
    if status == "unknown":
        return {"node_id": node_id, "entries": [], "count": 0,
                "error": "Unknown node"}

    lines = max(1, min(lines, 200))
    try:
        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(
            None, _query_logs_with_filter, project, resolved_filter, lines)
        return {"node_id": node_id, "entries": entries, "count": len(entries)}
    except ImportError:
        return {"node_id": node_id, "entries": [], "count": 0,
                "error": "google-cloud-logging not installed"}
    except Exception as e:
        logger.warning(f"Log query failed for {node_id}: {e}")
        return {"node_id": node_id, "entries": [], "count": 0,
                "error": f"Log collection failed: {str(e)[:100]}"}
