# File: src/api/routes/logs.py
# Purpose: GET /api/logs/{node_id} — real GCP Cloud Logging for any topology node.
# REQ-704: filter+project are derived server-side from node_id via the compiled
# manifest. Client-supplied log_filter / log_project query parameters are
# IGNORED with a warning log (kept in the signature for one transition window
# so existing callers that still send them get a clean 200, not a 422).
# REQ-212: when a node exists in the manifest but does not declare
# monitoring.logs, fall back to the project-scoped gce_instance default so the
# modal still shows real entries — never an attacker-supplied project.
# REQ-GHA-032: a part with no lines in the last hour shows its most recent lines
# from the last 7 days and says so; every empty answer carries a plain reason.
# Amended 2026-11-09 (clauses 12 and 13): the window opens with several screens of
# lines (300 by default, 500 at most) and `before=<the oldest line shown>` returns
# the lines before it, within the 7-day limit, with a plain note when none remain.

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request

from src.api.routes.auth import verify_token
from src.config.settings import GCP_PROJECT_ID

router = APIRouter(tags=["logs"])
logger = logging.getLogger(__name__)

# REQ-212: default applied when a node exists in the manifest but does NOT
# declare monitoring.logs (e.g. LB without exported access logs). Always
# scoped to GCP_PROJECT_ID — never an arbitrary project.
DEFAULT_FILTER = 'resource.type="gce_instance"'


QUIET_FALLBACK = timedelta(days=7)
QUIET_NOTE = "No log lines in the last hour. Showing the most recent lines from the last 7 days."
EMPTY_NOTE = "No log lines for this part in the last 7 days."
EARLIER_EMPTY_NOTE = "No earlier lines in the last 7 days."
UNKNOWN_NOTE = "GlassHood does not know this part, so it cannot look up its logs."
LINES_DEFAULT, LINES_MAX = 300, 500
# "before" includes the boundary moment, so lines sharing the oldest timestamp can be reached;
# the window asks for one page plus the lines it already holds at that moment
LINES_MAX_EARLIER = 2000


def _parse_before(before: str) -> datetime:
    """The oldest line shown, in any of the forms the windows print (GCP, AWS, Azure, provider)."""
    text = before.strip().replace(" ", "T")
    finer = re.search(r"\.\d{6}(\d*[1-9]\d*)", text) is not None     # finer than a microsecond: round up, so nothing is skipped
    text = re.sub(r"(\.\d{6})\d+", r"\1", text).replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    dt = dt + timedelta(microseconds=1) if finer else dt
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _older(timestamp, before: datetime) -> bool:
    try:
        return _parse_before(str(timestamp)) <= before
    except ValueError:
        return False


def _query_logs_with_filter(project: str, log_filter: str, max_entries: int = 100,
                            window: timedelta = timedelta(hours=1), before: datetime = None) -> list[dict]:
    """Query GCP Cloud Logging with an explicit filter and project.

    REQ-705: the manifest-supplied filter is wrapped in parentheses so an
    `OR` clause inside the manifest filter cannot cause the trailing
    `AND timestamp>=...` to bind looser than expected and return entries
    outside the intended one-hour window. `before` narrows to the lines
    older than the oldest one already shown (REQ-GHA-032 clause 13).
    """
    from google.cloud.logging_v2 import Client

    cutoff = datetime.now(timezone.utc) - window
    filter_str = f'({log_filter}) AND timestamp>="{cutoff.isoformat()}"'
    if before is not None:
        filter_str += f' AND timestamp<="{before.isoformat()}"'

    client = Client(project=project)
    entries = list(client.list_entries(
        filter_=filter_str,
        order_by="timestamp desc",
        max_results=max_entries,
    ))

    results = []
    for entry in entries:
        results.append({
            "timestamp": str(entry.timestamp),
            "severity": entry.severity or "DEFAULT",
            "message": _readable(entry)[:500],
        })
    return results


def _readable(entry) -> str:
    """One plain line per log entry (REQ-GHA-032).

    A load balancer request reads "GET 200 https://… · 0.012s · from 1.2.3.4"
    and a change record reads "v1.compute.firewalls.patch by someone@… on
    projects/…/firewalls/x"; other entries keep their message text as before.
    """
    http = getattr(entry, "http_request", None) or {}
    if isinstance(http, dict) and (http.get("requestMethod") or http.get("requestUrl")):
        parts = [" ".join(str(x) for x in (http.get("requestMethod"), http.get("status"),
                                          http.get("requestUrl")) if x)]
        if http.get("latency"):
            parts.append(str(http["latency"]))
        if http.get("remoteIp"):
            parts.append(f"from {http['remoteIp']}")
        return " · ".join(parts)
    payload = entry.payload
    if isinstance(payload, dict):
        if payload.get("methodName"):
            who = (payload.get("authenticationInfo") or {}).get("principalEmail") or "unknown caller"
            line = f"{payload['methodName']} by {who}"
            if payload.get("resourceName"):
                line += f" on {payload['resourceName']}"
            status = payload.get("status") or {}
            if isinstance(status, dict) and status.get("message"):
                line += f" ({status['message']})"
            return line
        return str(payload.get("message", payload))
    return str(payload) if payload else ""


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


def _resolve_node(node_id: str) -> tuple[str, str | None, str | dict | None]:
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
        if logs and logs[0].get("source") == "none":
            # REQ-GHA-032 clause 10: a part with no log source says why
            return ("no_logs", None, logs[0].get("reason") or "This part writes no logs GlassHood can read.")
        if logs and logs[0].get("source") == "aws":
            return ("aws_logs", None, logs[0])
        if logs and logs[0].get("source") == "azure" and logs[0].get("workspace") and logs[0].get("query"):
            # REQ-GHA-035: GlassHood's own logs, in its Azure Log Analytics workspace
            return ("azure_logs", logs[0]["workspace"], logs[0]["query"])
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

    # 3) A box inside a discovered VM (its container, app, embeddings): only the VM
    #    itself is in the discovery cache, so resolve the child from that VM's own
    #    cache entry and its parent's children_template (REQ-GHA-032). A child
    #    without its own logs shows the lines of the box it runs in.
    found = _resolve_vm_child(node_id)
    if found:
        return found

    return ("unknown", None, None)


def _resolve_vm_child(node_id: str):
    from src.collectors import manifest_metrics

    for vm_id, cached in manifest_metrics.get_all_statuses().items():
        if not (vm_id.startswith("vm-") and node_id.startswith(vm_id + "-") and cached.get("_parent")):
            continue
        template = manifest_metrics.get_children_template(cached["_parent"]) or []
        tree = manifest_metrics.resolve_children_template(
            template, vm_id[3:], cached.get("instance_id", ""))

        def walk(nodes, inherited):
            for n in nodes:
                logs = (n.get("monitoring") or {}).get("logs") or []
                own = logs[0] if logs and logs[0].get("filter") and logs[0].get("project") else None
                cfg = own or inherited
                if n.get("id") == node_id:
                    return cfg
                hit = walk(n.get("children") or [], cfg)
                if hit:
                    return hit
            return None

        cfg = walk(tree, None)
        if cfg:
            return ("discovered_vm", cfg["project"], cfg["filter"])
    return None


async def _earlier(node_id: str, status: str, project, resolved_filter, lines: int, before: datetime) -> dict:
    """REQ-GHA-032 clause 13: the lines before the oldest one shown, within the 7-day limit."""
    loop = asyncio.get_running_loop()
    floor = datetime.now(timezone.utc) - QUIET_FALLBACK
    try:
        if before <= floor:
            entries = []
        elif status == "aws_logs":
            from src.collectors.aws_resources import query_logs
            hours = (before - floor).total_seconds() / 3600
            entries = await loop.run_in_executor(
                None, lambda: query_logs(resolved_filter, hours, lines, end_ms=int(before.timestamp() * 1000) + 1))
        elif status == "azure_logs":
            from src.collectors.azure_resources import query_logs
            entries = await loop.run_in_executor(
                None, lambda: query_logs(project, resolved_filter, 24 * 7, lines, before=before))
        else:
            entries = await loop.run_in_executor(
                None, _query_logs_with_filter, project, resolved_filter, lines, QUIET_FALLBACK, before)
    except ImportError:
        return {"node_id": node_id, "entries": [], "count": 0, "earlier": True,
                "error": "google-cloud-logging not installed"}
    except Exception as e:
        logger.warning(f"Earlier log query failed for {node_id}: {e}")
        return {"node_id": node_id, "entries": [], "count": 0, "earlier": True,
                "error": f"GlassHood could not read this part's earlier logs ({type(e).__name__})"}
    return {"node_id": node_id, "entries": entries, "count": len(entries), "window": "7d", "earlier": True,
            **({} if entries else {"note": EARLIER_EMPTY_NOTE})}


@router.get("/api/logs/{node_id}")
async def get_logs(node_id: str, request: Request, lines: int = LINES_DEFAULT, before: str = None,
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

    before_dt = None
    if before:
        try:
            before_dt = _parse_before(before)
        except ValueError:
            raise HTTPException(status_code=400, detail="before must be a time as the log lines print it")

    # REQ-GHA-036: a public system's box shows what its provider publishes about it
    from src.collectors import statuspage
    published = statuspage.log_entries(node_id)
    if published is not None:
        if before_dt is not None:   # the provider's updates come whole; "earlier" is what is older than the oldest shown
            entries = [e for e in published.get("entries") or [] if _older(e.get("timestamp"), before_dt)]
            return {"node_id": node_id, "entries": entries, "count": len(entries), "window": "provider", "earlier": True,
                    **({} if entries else {"note": EARLIER_EMPTY_NOTE})}
        return {"node_id": node_id, "count": len(published["entries"]), "window": "provider", **published}

    status, project, resolved_filter = _resolve_node(node_id)
    if status == "unknown":
        return {"node_id": node_id, "entries": [], "count": 0,
                "error": UNKNOWN_NOTE}

    lines = max(1, min(lines, LINES_MAX_EARLIER if before_dt is not None else LINES_MAX))
    if status == "no_logs":
        return {"node_id": node_id, "entries": [], "count": 0, "note": resolved_filter}
    if before_dt is not None:
        return await _earlier(node_id, status, project, resolved_filter, lines, before_dt)
    if status == "aws_logs":
        from src.collectors.aws_resources import query_logs
        try:
            loop = asyncio.get_running_loop()
            entries = await loop.run_in_executor(None, query_logs, resolved_filter, 1, lines)
            if entries:
                return {"node_id": node_id, "entries": entries, "count": len(entries), "window": "1h"}
            entries = await loop.run_in_executor(None, query_logs, resolved_filter, 24 * 7, lines)
            return {"node_id": node_id, "entries": entries, "count": len(entries), "window": "7d",
                    "note": QUIET_NOTE if entries else EMPTY_NOTE}
        except Exception as e:
            return {"node_id": node_id, "entries": [], "count": 0,
                    "error": f"GlassHood could not read this part's AWS logs ({type(e).__name__})"}
    if status == "azure_logs":
        from src.collectors.azure_resources import query_logs
        try:
            loop = asyncio.get_running_loop()
            entries = await loop.run_in_executor(None, query_logs, project, resolved_filter, 1, lines)
            if entries:
                return {"node_id": node_id, "entries": entries, "count": len(entries), "window": "1h"}
            entries = await loop.run_in_executor(None, query_logs, project, resolved_filter, 24 * 7, lines)
            return {"node_id": node_id, "entries": entries, "count": len(entries), "window": "7d",
                    "note": QUIET_NOTE if entries else EMPTY_NOTE}
        except Exception as e:
            logger.warning(f"Azure log query failed for {node_id}: {e}")
            return {"node_id": node_id, "entries": [], "count": 0,
                    "error": f"GlassHood could not read this part's logs ({type(e).__name__})"}
    try:
        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(
            None, _query_logs_with_filter, project, resolved_filter, lines)
        if entries:
            return {"node_id": node_id, "entries": entries, "count": len(entries), "window": "1h"}
        # REQ-GHA-032 clause 7: a quiet part shows its latest lines from the last 7 days
        entries = await loop.run_in_executor(
            None, _query_logs_with_filter, project, resolved_filter, lines, QUIET_FALLBACK)
        return {"node_id": node_id, "entries": entries, "count": len(entries), "window": "7d",
                "note": QUIET_NOTE if entries else EMPTY_NOTE}
    except ImportError:
        return {"node_id": node_id, "entries": [], "count": 0,
                "error": "google-cloud-logging not installed"}
    except Exception as e:
        logger.warning(f"Log query failed for {node_id}: {e}")
        return {"node_id": node_id, "entries": [], "count": 0,
                "error": f"GlassHood could not read this part's logs: {str(e)[:100]}"}
