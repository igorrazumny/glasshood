# File: src/collectors/gcp_resources.py
# Purpose: REQ-GHA-023 — read-only checks of a monitored project's real parts, and its findings.
# Every call uses GlassHood's existing read-only roles (Compute, Cloud Asset, Logging and
# Monitoring viewers, Secret Manager metadata). No secret value is read; nothing is written.
# Each probe returns {status, metrics, check_description}.

import logging
import threading
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_creds = None
_creds_lock = threading.Lock()
_TIMEOUT = 15

# Resource states that mean "in service" for the Compute resources GlassHood reads.
_GOOD_STATES = {"IN_USE", "RUNNING", "ACTIVE", "READY", "RESERVED"}


def _headers() -> dict:
    """Bearer token; credentials that name a quota project (local user credentials) send it."""
    h = {"Authorization": f"Bearer {_token()}"}
    quota = getattr(_creds, "quota_project_id", None)
    if quota:
        h["x-goog-user-project"] = quota
    return h


def _token() -> str:
    global _creds
    import google.auth
    import google.auth.transport.requests
    with _creds_lock:
        if _creds is None:
            _creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not _creds.valid:
            _creds.refresh(google.auth.transport.requests.Request())
        return _creds.token


def _get(url: str, params=None) -> httpx.Response:
    return httpx.get(url, params=params, timeout=_TIMEOUT, headers=_headers())


def _result(status: str, desc: str, **metrics) -> dict:
    return {"status": status, "metrics": metrics, "check_description": desc}


def _field(data: dict, path: str):
    """Nested field by dotted path; resource URLs are shortened to their last segment."""
    v = data
    for part in path.split("."):
        if not isinstance(v, dict):
            return None
        v = v.get(part)
    if isinstance(v, str) and v.startswith("https://"):
        return v.rsplit("/", 1)[-1]
    if isinstance(v, list):
        return ", ".join(str(x).rsplit("/", 1)[-1] if str(x).startswith("https://") else str(x) for x in v)
    return v


def _days_until(iso: str) -> float:
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() / 86400


def probe_compute(project: str, path: str, fields=None) -> dict:
    """GET one Compute resource (e.g. 'global/sslCertificates/x'). Healthy when it exists and
    is in service; a certificate is degraded under 30 days to expiry and in error under 7."""
    try:
        r = _get(f"https://compute.googleapis.com/compute/v1/projects/{project}/{path}")
    except httpx.HTTPError as e:
        return _result("error", f"Compute API unreachable ({type(e).__name__})")
    name = path.rsplit("/", 1)[-1]
    if r.status_code == 404:
        return _result("error", f"{name} — not found")
    if r.status_code != 200:
        return _result("error", f"{name} — Compute API HTTP {r.status_code}")
    data = r.json()
    metrics = {f.rsplit(".", 1)[-1]: _field(data, f) for f in fields or []}
    state = data.get("status")
    if isinstance(state, dict):  # instanceGroupManagers carry a status object, not a state
        state = None
    status, notes = "healthy", []
    if state:
        metrics["state"] = state
        if state not in _GOOD_STATES:
            status = "error"
        notes.append(state)
    expire = data.get("expireTime")
    if expire:
        days = round(_days_until(expire), 1)
        metrics["days_to_expiry"] = days
        managed = (data.get("managed") or {}).get("status")
        if managed and managed != "ACTIVE":
            status = "error"
            notes.append(f"managed {managed}")
        status = "error" if days < 7 else ("degraded" if days < 30 and status == "healthy" else status)
        notes.append(f"expires {expire[:10]} ({days:g} days)")
    detail = ", ".join(f"{k} {v}" for k, v in metrics.items() if v not in (None, "") and k not in ("state", "days_to_expiry"))
    desc = f"{name} — " + "; ".join(x for x in [", ".join(notes), detail] if x) if (notes or detail) else f"{name} — exists"
    return _result(status, desc, **metrics)


def probe_backend_health(project: str, backend_service: str) -> dict:
    """How many backends the load balancer's own health check sees as HEALTHY."""
    base = f"https://compute.googleapis.com/compute/v1/projects/{project}/global/backendServices/{backend_service}"
    try:
        bs = _get(base)
        if bs.status_code != 200:
            return _result("error", f"{backend_service} — Compute API HTTP {bs.status_code}")
        states = []
        for b in bs.json().get("backends", []):
            r = httpx.post(f"{base}/getHealth", json={"group": b["group"]}, timeout=_TIMEOUT,
                           headers=_headers())
            if r.status_code == 200:
                states += [h.get("healthState") for h in r.json().get("healthStatus", [])]
    except httpx.HTTPError as e:
        return _result("error", f"Compute API unreachable ({type(e).__name__})")
    healthy = sum(1 for s in states if s == "HEALTHY")
    status = "healthy" if states and healthy == len(states) else ("degraded" if healthy else "error")
    return _result(status, f"{backend_service} — {healthy} of {len(states)} backends HEALTHY "
                           "(the load balancer's own health check)",
                   healthy_backends=healthy, backends=len(states))


def _why(e: Exception) -> str:
    resp = getattr(e, "response", None)
    if resp is not None:
        return f"Cloud Asset Inventory HTTP {resp.status_code}"
    return f"Cloud Asset Inventory unreachable ({type(e).__name__})"


def search_assets(project: str, asset_type: str, name: str = "") -> list:
    """Cloud Asset Inventory search; with a name, only exact display-name matches."""
    params = {"assetTypes": asset_type, "pageSize": 500}
    if name:
        params["query"] = f'displayName:"{name}"'
    out, token = [], None
    for _ in range(10):
        if token:
            params["pageToken"] = token
        r = _get(f"https://cloudasset.googleapis.com/v1/projects/{project}:searchAllResources", params)
        r.raise_for_status()
        body = r.json()
        out += [a for a in body.get("results", []) if not name or a.get("displayName") == name]
        token = body.get("nextPageToken")
        if not token:
            break
    return out


def probe_asset(project: str, asset_type: str, name: str = "", expect: str = "one") -> dict:
    """Exists in the project's inventory. With expect 'one', duplicates are reported as drift."""
    label = name or asset_type.rsplit("/", 1)[-1]
    try:
        found = search_assets(project, asset_type, name)
    except httpx.HTTPError as e:
        return _result("error", _why(e))
    n = len(found)
    if n == 0:
        return _result("error", f"{label} — not found in the project's inventory", count=0)
    if expect == "one" and n > 1:
        # Drift is a finding (clause 6), not an outage: the part still works.
        return _result("healthy", f"{label} — works; {n} copies where one is expected "
                                  "(configuration drift, listed under findings)", count=n, duplicates=n - 1)
    return _result("healthy", f"{label} — present in the project's inventory", count=n)


def probe_secret_count(project: str) -> dict:
    """Number of secrets, from metadata only. No secret value is read."""
    try:
        n, token = 0, None
        for _ in range(10):
            params = {"pageSize": 250, **({"pageToken": token} if token else {})}
            r = _get(f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets", params)
            if r.status_code != 200:
                return _result("error", f"Secret Manager API HTTP {r.status_code}")
            body = r.json()
            n += len(body.get("secrets", []))
            token = body.get("nextPageToken")
            if not token:
                break
    except httpx.HTTPError as e:
        return _result("error", f"Secret Manager API unreachable ({type(e).__name__})")
    return _result("healthy" if n else "error",
                   f"{n} secrets (names and metadata only; no value is read)", secrets=n)


def probe_sql_backup(project: str, max_age_h: float = 36) -> dict:
    """Age of the newest successful Cloud SQL backup, from the asset inventory."""
    try:
        found = search_assets(project, "sqladmin.googleapis.com/Backup")
    except httpx.HTTPError as e:
        return _result("error", _why(e))
    done = sorted((a.get("createTime") for a in found if a.get("state") == "SUCCESSFUL" and a.get("createTime")),
                  reverse=True)
    if not done:
        return _result("error", "no successful Cloud SQL backup found", successful_backups=0)
    age_h = round(-_days_until(done[0]) * 24, 1)
    status = "healthy" if age_h <= max_age_h else ("degraded" if age_h <= 2 * max_age_h else "error")
    return _result(status, f"last successful backup {done[0]} ({age_h:g} h ago); {len(done)} kept",
                   last_backup_age_h=age_h, successful_backups=len(done))


# --- Findings: drift and leftovers, listed as warnings and never drawn ---

_findings: list = []
_findings_lock = threading.Lock()


def evaluate_findings(project: str, findings: list) -> list:
    """A finding is active while its check holds: `asset` exists (or is duplicated, with
    `min_count`). A finding with no check is a statement by its `source`, always listed."""
    active = []
    for f in findings or []:
        chk = f.get("check")
        if chk:
            try:
                n = len(search_assets(chk.get("project", project), chk["asset_type"], chk.get("name", "")))
            except (httpx.HTTPError, KeyError) as e:
                logger.debug(f"finding check {f.get('id')} failed: {e}")
                continue  # unknown is not reported as a finding
            if n < chk.get("min_count", 1):
                continue
            text = f["text"].replace("{count}", str(n))
        else:
            text = f["text"]
        active.append({"id": f["id"], "text": text, "source": f.get("source", ""),
                       "checked": bool(chk), "checked_at": time.time()})
    return active


def set_findings(items: list) -> None:
    with _findings_lock:
        _findings[:] = items


def get_findings() -> list:
    with _findings_lock:
        return list(_findings)
