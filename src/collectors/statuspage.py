# File: src/collectors/statuspage.py
# Purpose: REQ-GHA-036 — public systems GlassHood does not control, read only from what
# they publish: a provider's public status API (Atlassian Statuspage v2 summary), no login.
#
# A landscape file marked `kind: outside_view` lists the provider's components as boxes:
#   monitoring: {probe: {type: statuspage, url: <summary.json>, component_id: <id>}}
# One summary read per provider per round serves all its boxes. Incidents and maintenance
# in progress become alarms; their update text is the box's log.

import logging
import threading
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "GlassHood-monitor/1.0 (+https://glasshood.ai; read-only status check)"
CACHE_S = 300          # one read per provider per 5 minutes at most
TIMEOUT_S = 15

_lock = threading.Lock()
_cache: dict = {}      # url -> {"at": ts, "data": dict | None, "error": str | None}
_fetching: dict = {}   # url -> lock held while that provider is being read (one read at a time)

_STATUS = {
    "operational": "healthy",
    "degraded_performance": "degraded",
    "partial_outage": "degraded",
    "under_maintenance": "degraded",
    "major_outage": "error",
}
_WORDS = {
    "operational": "operational", "degraded_performance": "degraded performance",
    "partial_outage": "partial outage", "major_outage": "major outage",
    "under_maintenance": "under maintenance",
}


def summary(url: str, fetch=None) -> dict:
    """{"data": summary or None, "error": reason or None, "at": when read}, cached per provider."""
    now = time.time()
    with _lock:
        hit = _cache.get(url)
        if hit and now - hit["at"] < CACHE_S:
            return hit
        gate = _fetching.setdefault(url, threading.Lock())
    with gate:  # concurrent first reads of one provider share a single fetch
        with _lock:
            hit = _cache.get(url)
            if hit and time.time() - hit["at"] < CACHE_S:
                return hit
        return _read(url, fetch, now)


def _read(url: str, fetch, now: float) -> dict:
    try:
        if fetch:
            data = fetch(url)
        else:
            resp = httpx.get(url, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("components"), list):
            raise ValueError("no component list in the provider's answer")
        entry = {"at": now, "data": data, "error": None}
    except Exception as e:
        logger.warning(f"statuspage read failed for {url}: {type(e).__name__}: {e}")
        entry = {"at": now, "data": None, "error": f"the provider's status could not be read ({type(e).__name__})"}
    with _lock:
        _cache[url] = entry
    return entry


def box(probe: dict, fetch=None) -> dict:
    """A component's box: the provider's state, its last update, and when GlassHood checked."""
    s = summary(probe.get("url", ""), fetch)
    checked = time.strftime("%H:%M UTC", time.gmtime(s["at"]))
    if not s["data"]:
        return {"status": "not checked", "metrics": {"note": f"Data unavailable: {s['error']}"},
                "check_description": f"Data unavailable: {s['error']} (tried {checked})"}
    comp = next((c for c in s["data"]["components"] if c.get("id") == probe.get("component_id")), None)
    if comp is None:
        return {"status": "not checked", "metrics": {"note": "the provider no longer lists this component"},
                "check_description": "Data unavailable: the provider no longer lists this component"}
    raw = comp.get("status", "")
    return {
        "status": _STATUS.get(raw, "not checked"),
        "metrics": {"provider_status": _WORDS.get(raw, raw or "unknown"),
                    "provider_updated": (comp.get("updated_at") or "")[:16].replace("T", " ")},
        "check_description": (f"Provider reports: {_WORDS.get(raw, raw or 'unknown')} · provider update "
                              f"{(comp.get('updated_at') or '')[:16].replace('T', ' ')} UTC · checked {checked}"),
    }


def _events(data: dict) -> list:
    """Incidents not yet resolved, and maintenance under way or being verified (the provider
    has not marked it completed), newest first."""
    out = [dict(i, _kind="incident") for i in data.get("incidents") or []
           if i.get("status") not in ("resolved", "postmortem")]
    out += [dict(m, _kind="maintenance") for m in data.get("scheduled_maintenances") or []
            if m.get("status") in ("in_progress", "verifying")]
    return out


def outside_systems() -> list:
    """[(provider name, summary url, {component id: box id})] from the outside-view landscapes."""
    from src.api.routes.manifests import _load_manifests
    found = {}
    for m in _load_manifests():
        if m.get("kind") != "outside_view":
            continue
        for n in m.get("nodes") or []:
            probe = ((n.get("monitoring") or {}).get("probe") or {})
            if probe.get("type") == "statuspage" and probe.get("url") and probe.get("component_id"):
                name, comps = found.setdefault(probe["url"], (m.get("solution") or m.get("product"), {}))
                comps[probe["component_id"]] = n.get("id")
    return [(name, url, comps) for url, (name, comps) in found.items()]


def part_providers() -> dict:
    """{box id: provider name} for every outside-view box."""
    return {box: name for name, _, comps in outside_systems() for box in comps.values()}


def incidents(fetch=None) -> tuple:
    """(alarm entries, names of the providers read) for every outside system: one alarm per
    incident or maintenance, on the first box it names, keeping every box it names; the
    provider's own text and link are the evidence. A provider that could not be read is
    left out of the set, so only its own alarms stay as they were."""
    entries, read = [], set()
    for name, url, comps in outside_systems():
        s = summary(url, fetch)
        if not s["data"]:
            continue
        read.add(name)
        page = (s["data"].get("page") or {}).get("url") or url
        for ev in _events(s["data"]):
            named = [c for c in ev.get("components") or [] if c.get("id") in comps]
            if not named:
                continue
            updates = ev.get("incident_updates") or []
            latest = (updates[0].get("body") if updates else "") or ""
            impact = ev.get("impact") or "none"
            severity = "critical" if impact in ("critical", "major") and ev["_kind"] == "incident" else "warning"
            where = ", ".join(c.get("name", "") for c in named[:8]) + (f" and {len(named) - 8} more" if len(named) > 8 else "")
            kind_words = ("an incident" if ev["_kind"] == "incident" else
                          "maintenance being verified" if ev.get("status") == "verifying" else "maintenance in progress")
            what = (f"{name} reports {kind_words}: "
                    f"\"{ev.get('name')}\" ({ev.get('status', '').replace('_', ' ')}, impact {impact}), affecting {where}.")
            if latest:
                what += f" Latest provider update: {latest[:400]}"
            link = ev.get("shortlink") or page
            entries.append({
                "id": ev.get("id"), "provider": name, "part": comps[named[0]["id"]], "severity": severity,
                "parts": [comps[c["id"]] for c in named],
                "title": f"{ev.get('name')} ({'incident' if ev['_kind'] == 'incident' else 'maintenance'}, reported by {name})",
                "explanation": {"what": what, "suspicion": None,
                                "directions": [f"Follow the provider's updates: {link}"]},
                "evidence": [f"{u.get('created_at', '')[:16].replace('T', ' ')} UTC {u.get('status', '')}: {u.get('body', '')}"
                             for u in updates[:20]] + [f"Source: {link}"],
            })
    return entries, read


def log_entries(node_id: str, fetch=None) -> Optional[dict]:
    """For an outside-view box: the provider's published updates that name it, as its log.
    None when the box is not an outside-view component."""
    for name, url, comps in outside_systems():
        cid = next((c for c, b in comps.items() if b == node_id), None)
        if cid is None:
            continue
        s = summary(url, fetch)
        if not s["data"]:
            return {"entries": [], "error": f"Data unavailable: {s['error']}"}
        rows = []
        for ev in _events(s["data"]):
            if any(c.get("id") == cid for c in ev.get("components") or []):
                for u in ev.get("incident_updates") or []:
                    rows.append({"timestamp": u.get("created_at"), "severity": "WARNING",
                                 "message": f"[{name}] {ev.get('name')} — {u.get('status', '')}: {u.get('body', '')}"})
        rows.sort(key=lambda r: r["timestamp"] or "", reverse=True)
        note = None if rows else (f"{name} publishes no open incident or maintenance for this part. "
                                  "Only what the provider publishes is shown; GlassHood has no access inside it.")
        return {"entries": rows, "note": note}
    return None
