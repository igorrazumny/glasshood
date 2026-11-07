# File: src/collectors/azure_resources.py
# Purpose: REQ-GHA-035 — GlassHood reads its own Azure resources and logs with its own
# managed identity (Reader + Log Analytics Reader on its resource group), no stored key.
#
#   probe:  {type: azure_resource, id: /subscriptions/.../providers/<type>/<name>}
#   logs:   [{source: azure, workspace: <Log Analytics workspace id>, query: <KQL table + filter>}]

import logging
import os
import threading
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

ARM = "https://management.azure.com"
LOGS = "https://api.loganalytics.io"
_API = {  # resource provider -> api-version
    "microsoft.app/containerapps": "2024-03-01",
    "microsoft.app/managedenvironments": "2024-03-01",
    "microsoft.web/staticsites": "2023-01-01",
    "microsoft.web/sites": "2023-01-01",
    "microsoft.storage/storageaccounts": "2023-01-01",
    "microsoft.keyvault/vaults": "2023-07-01",
    "microsoft.operationalinsights/workspaces": "2022-10-01",
}
_lock = threading.Lock()
_tokens: dict = {}   # resource -> (token, expires_on)


class NotOnAzure(Exception):
    """No managed identity here (for example a local run)."""


def token(resource: str) -> str:
    """A managed-identity token for the resource, cached until shortly before it expires."""
    with _lock:
        hit = _tokens.get(resource)
        if hit and hit[1] - 120 > time.time():
            return hit[0]
    endpoint, header = os.environ.get("IDENTITY_ENDPOINT"), os.environ.get("IDENTITY_HEADER")
    if not endpoint or not header:
        raise NotOnAzure("no managed identity in this environment")
    resp = httpx.get(endpoint, params={"resource": resource, "api-version": "2019-08-01"},
                     headers={"X-IDENTITY-HEADER": header}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    with _lock:
        _tokens[resource] = (data["access_token"], float(data["expires_on"]))
    return data["access_token"]


def _api_version(resource_id: str) -> str:
    parts = resource_id.strip("/").split("/")
    try:
        i = [p.lower() for p in parts].index("providers")
        kind = f"{parts[i + 1]}/{parts[i + 2]}".lower()
    except (ValueError, IndexError):
        kind = ""
    return _API.get(kind, "2022-09-01")


def read_resource(resource_id: str, get=None) -> dict:
    """The resource as Azure Resource Manager describes it."""
    if get:
        return get(resource_id)
    resp = httpx.get(f"{ARM}{resource_id}", params={"api-version": _api_version(resource_id)},
                     headers={"Authorization": f"Bearer {token(ARM + '/')}"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def judge(resource: dict) -> tuple:
    """(status, plain description, figures) from a resource's own properties."""
    p = resource.get("properties") or {}
    prov = p.get("provisioningState")
    figures = {"provisioning": prov}
    if "runningStatus" in p or "latestReadyRevisionName" in p:          # container app
        ready, latest = p.get("latestReadyRevisionName"), p.get("latestRevisionName")
        figures.update(running=p.get("runningStatus"), revision=ready)
        running = (p.get("runningStatus") or "").lower()
        if prov == "Failed" or running == "stopped":
            return "error", f"Container app {p.get('runningStatus') or prov}", figures
        if ready != latest:
            return "degraded", f"Newest revision {latest} is not ready; serving {ready}", figures
        if prov != "Succeeded" or running != "running":
            return "degraded", f"Container app is {p.get('runningStatus') or 'in an unknown state'} (provisioning {prov})", figures
        return "healthy", f"Running revision {ready}", figures
    if "state" in p and isinstance(p.get("state"), str):                 # function / web app
        figures["state"] = p["state"]
        ok = p["state"].lower() == "running"
        return ("healthy" if ok else "error"), f"State {p['state']}", figures
    if "statusOfPrimary" in p:                                         # storage account
        figures["primary"] = p["statusOfPrimary"]
        ok = p["statusOfPrimary"] == "available" and prov == "Succeeded"
        return ("healthy" if ok else "error"), f"Primary storage {p['statusOfPrimary']}", figures
    if prov is None:
        return "not checked", "Azure returned no state for this resource", figures
    if prov == "Succeeded":
        return "healthy", "Provisioning Succeeded", figures
    if prov in ("Failed", "Canceled"):
        return "error", f"Provisioning {prov}", figures
    return "degraded", f"Provisioning {prov}", figures


def box(probe: dict, get=None) -> dict:
    """A box for one of GlassHood's own Azure resources; unreadable is said, never healthy."""
    checked = datetime.now(timezone.utc).strftime("%H:%M UTC")
    try:
        status, desc, figures = judge(read_resource(probe.get("id", ""), get))
        return {"status": status, "metrics": figures, "check_description": f"{desc} · checked {checked}"}
    except Exception as e:
        why = f"GlassHood could not read this resource ({type(e).__name__})"
        return {"status": "not checked", "metrics": {"note": why}, "check_description": f"{why} · tried {checked}"}


def query_logs(workspace: str, query: str, since_hours: float, max_entries: int, post=None) -> list:
    """Log lines from GlassHood's Log Analytics workspace, newest first, as the log viewer shows them."""
    kql = f"{query} | where TimeGenerated > ago({int(since_hours * 60)}m) | order by TimeGenerated desc | take {int(max_entries)}"
    if post:
        data = post(workspace, kql)
    else:
        resp = httpx.post(f"{LOGS}/v1/workspaces/{workspace}/query", json={"query": kql},
                          headers={"Authorization": f"Bearer {token(LOGS)}"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    table = (data.get("tables") or [{}])[0]
    cols = [c["name"] for c in table.get("columns") or []]
    out = []
    for row in table.get("rows") or []:
        r = dict(zip(cols, row))
        msg = r.get("Log_s") or r.get("Log") or r.get("Message") or r.get("msg_s") or ""
        out.append({"timestamp": str(r.get("TimeGenerated", "")),
                    "severity": "ERROR" if any(w in str(msg) for w in ("ERROR", "Traceback", "CRITICAL"))
                    else "WARNING" if "WARNING" in str(msg) else "INFO",
                    "message": str(msg)[:500]})
    return out
