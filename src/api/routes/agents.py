# File: src/api/routes/agents.py
# Purpose: REQ-GHA-049: what the agents' MCP server reads. Each agent uses its own credential; every read
#   is logged under its name; the full setup and verification are for the system's responsible agent only.

import hashlib
import logging
import re
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.analysis import agent_access as store
from src.api.routes.auth import verify_token
from src.auth.rbac import require_role

router = APIRouter(tags=["agents"])
logger = logging.getLogger(__name__)

NOT_CONFIRMED = {"not checked", "not monitored", "unknown", "stale", "disabled", "planned", None, ""}
_SECRET_KEY = re.compile(r"(?i)(secret|password|passwd|token|api_?key|credential|private_?key)")
KINDS = ("no_longer_exists", "missing", "described_wrongly")


def _agent(request: Request) -> str:
    key = request.headers.get("X-Agent-Key", "")
    if not key:
        raise HTTPException(status_code=401, detail="This needs an agent credential")
    try:
        agent = store.agent_of(key)
    except store.Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not agent:
        raise HTTPException(status_code=401, detail="Unknown or withdrawn agent credential")
    logger.info(f"agent read: {agent} {request.method} {request.url.path}")
    return agent


def _landscapes() -> dict:
    """product -> (the landscape file as written, its version and time)."""
    from src.api.routes.manifests import MANIFEST_DIR
    out = {}
    for f in sorted(Path(MANIFEST_DIR).glob("*.yaml")):
        data = yaml.safe_load(f.read_text()) or {}
        if isinstance(data, dict) and data.get("product"):
            out[data["product"]] = (data, {"file": f.name, "version": hashlib.sha256(f.read_bytes()).hexdigest()[:12],
                                           "changed_at": f.stat().st_mtime})
    return out


def _landscape(system: str):
    found = _landscapes().get(system)
    if not found:
        raise HTTPException(status_code=404, detail=f"GlassHood monitors no system {system!r}")
    return found


def _responsible(request: Request, system: str):
    agent = _agent(request)
    data, version = _landscape(system)
    if data.get("responsible_agent") != agent:
        raise HTTPException(status_code=403, detail=f"Only the agent responsible for {system} can read its full setup")
    return agent, data, version


def _no_secrets(value):
    """Clause 12: a credential value is never part of the answer, whatever the file holds."""
    if isinstance(value, dict):
        return {k: "[not shown]" if _SECRET_KEY.search(str(k)) else _no_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_no_secrets(v) for v in value]
    return value


def _walk(nodes):
    for n in nodes or []:
        if isinstance(n, dict) and n.get("id"):
            yield n
            yield from _walk(n.get("children"))


def _topology() -> list:
    from src.api.routes.topology import get_topology_data
    return get_topology_data().get("nodes") or []


def _components(system: str, nodes=None) -> list:
    """The boxes of one system; a box inside another belongs to the same system."""
    out = []
    for top in (_topology() if nodes is None else nodes):
        if isinstance(top, dict) and top.get("project") == system:
            out.extend(_walk([top]))
    return out


def alerts_by_system(nodes=None) -> dict:
    from src.rules.engine import get_alerts
    owner = {}
    for top in (_topology() if nodes is None else nodes):
        if isinstance(top, dict) and top.get("project"):
            for n in _walk([top]):
                owner[n["id"]] = top["project"]
    out: dict = {}
    for a in get_alerts():
        if a.get("kind") != "example" and owner.get(a.get("node_id")):
            out.setdefault(owner[a["node_id"]], []).append(a)
    return out


def _alert_line(a: dict) -> dict:
    return {k: a.get(k) for k in ("number", "severity", "kind", "title", "node_id", "first_seen", "last_seen")}


def scan(nodes) -> None:
    """Called from the assessment scan: records what changed since the last look."""
    from src.analysis import vertex_overview as ov
    store.record_changes(ov.system_cards(), alerts_by_system(nodes))


@router.get("/api/agents/systems")
def list_systems(request: Request):
    _agent(request)
    from src.analysis import vertex_overview as ov
    outside, records = ov._outside_products(), ov.system_cards()
    return {"systems": [{"system": p, "name": d.get("solution") or p,
                         "group": "External systems" if p in outside else "Proprietary systems",
                         "status": store.status_word(records.get(p)), "evaluated_at": (records.get(p) or {}).get("analyzed_at"),
                         "responsible_agent": d.get("responsible_agent")}
                        for p, (d, _) in _landscapes().items()]}


@router.get("/api/agents/systems/{system}")
def get_system(system: str, request: Request):
    _agent(request)
    data, _ = _landscape(system)
    from src.analysis import vertex_overview as ov
    record = ov.system_cards().get(system) or {}
    nodes = _topology()
    return {"system": system, "name": data.get("solution") or system, "status": store.status_word(record),
            "evaluated_at": record.get("analyzed_at"), "evaluation_error": record.get("error"),
            "score": record.get("score"), "summary": record.get("summary"), "issues": record.get("issues") or [],
            "open_alerts": [_alert_line(a) for a in alerts_by_system(nodes).get(system) or []],
            "components": [{"id": n["id"], "label": n.get("label"), "status": n.get("status")} for n in _components(system, nodes)]}


@router.get("/api/agents/systems/{system}/logs/{component}")
async def component_logs(system: str, component: str, request: Request):
    _agent(request)
    _landscape(system)
    if component not in {n["id"] for n in _components(system)}:
        raise HTTPException(status_code=404, detail=f"{system} has no component {component!r}")
    from src.api.routes.logs import get_logs
    return await get_logs(component, request)


@router.get("/api/agents/changes")
def changes(request: Request, system: str = None):
    agent = _agent(request)
    if system:
        _landscape(system)
    try:
        return {"changes": store.changes_for(agent, system)}
    except store.Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/api/agents/systems/{system}/setup")
def setup(system: str, request: Request):
    _, data, version = _responsible(request, system)
    from src.analysis import vertex_overview as ov
    return {"system": system, "landscape": version, "setup": ov.sanitize(_no_secrets(data))}


def _expected(data: dict) -> dict:
    return {n["id"]: n for env in data.get("environments") or [] for n in _walk(env.get("nodes"))}


@router.get("/api/agents/systems/{system}/verify")
def verify(system: str, request: Request):
    _, data, version = _responsible(request, system)
    from src.analysis import vertex_overview as ov
    expected, found = _expected(data), {n["id"]: n for n in _components(system)}
    parts = []
    for cid in sorted(set(expected) | set(found)):
        e, f = expected.get(cid) or {}, found.get(cid) or {}
        metrics = f.get("metrics") or {}
        status = f.get("status")
        parts.append({"component": cid, "label": e.get("label") or f.get("label"),
                      "expected_check": _no_secrets((e.get("monitoring") or {}).get("probe")),
                      "in_landscape": cid in expected, "last_result": status,
                      "check_description": metrics.get("_check_description"), "last_checked": metrics.get("_last_poll"),
                      "confirmed": status not in NOT_CONFIRMED})
    return ov.sanitize({"system": system, "landscape": version, "not_confirmed": [p["component"] for p in parts if not p["confirmed"]],
                        "note": "A component that is not confirmed is unknown. It is not evidence that the setup is correct.",
                        "components": parts})


class Correction(BaseModel):
    kind: str
    component: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=4000)


@router.post("/api/agents/systems/{system}/corrections")
def submit_correction(system: str, body: Correction, request: Request):
    """Clause 14: recorded and shown to the operator; it changes nothing by itself."""
    agent, _, _ = _responsible(request, system)
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {', '.join(KINDS)}")
    try:
        return store.add_correction(agent, system, body.kind, body.component, body.description, body.evidence)
    except store.Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/api/agents/corrections")
def list_corrections(request: Request):
    verify_token(request)
    require_role(request, "operator")
    try:
        return {"corrections": store.corrections()}
    except store.Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


class NewKey(BaseModel):
    agent: str = Field(min_length=1, max_length=64)


@router.post("/api/agents/keys")
def create_key(body: NewKey, request: Request):
    """The credential is shown once, to the operator who asked; only its hash is kept."""
    try:
        return {"agent": body.agent, "key": store.create_key(body.agent)}
    except store.Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/api/agents/keys/{agent}")
def withdraw_key(agent: str, request: Request):
    try:
        return {"agent": agent, "withdrawn": store.withdraw_key(agent)}
    except store.Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
