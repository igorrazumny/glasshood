# File: src/discovery/gcp_assets.py
# Purpose: GCP auto-discovery via Cloud Asset Inventory API

import logging
import threading
import time

from src.config.settings import GCP_PROJECT_ID, GCP_ZONE
from src.models.topology import Node, Edge

logger = logging.getLogger(__name__)

ASSET_TYPES = [
    "compute.googleapis.com/ForwardingRule",
    "compute.googleapis.com/TargetHttpsProxy",
    "compute.googleapis.com/UrlMap",
    "compute.googleapis.com/BackendService",
    "compute.googleapis.com/SecurityPolicy",
    "compute.googleapis.com/InstanceGroup",
    "compute.googleapis.com/Instance",
]

GCP_STATUS_MAP = {
    "RUNNING": "healthy", "STAGING": "degraded", "PROVISIONING": "degraded",
    "STOPPING": "degraded", "SUSPENDING": "degraded", "SUSPENDED": "error",
    "TERMINATED": "error", "REPAIRING": "degraded",
}

# asset_type -> (node_type, icon, label_prefix)
TYPE_META = {
    "ForwardingRule":    ("lb",  "shield", "LB"),
    "TargetHttpsProxy":  ("lb",  "shield", "HTTPS Proxy"),
    "UrlMap":            ("lb",  "shield", "URL Map"),
    "BackendService":    ("lb",  "shield", "Backend"),
    "SecurityPolicy":    ("lb",  "shield", "Cloud Armor"),
    "InstanceGroup":     ("mig", "layers", "Instance Group"),
    "Instance":          ("vm",  "server", ""),
}

# asset_type short name -> node id prefix
ID_PREFIX = {
    "ForwardingRule": "fr", "TargetHttpsProxy": "proxy", "UrlMap": "urlmap",
    "BackendService": "bs", "SecurityPolicy": "sp", "InstanceGroup": "ig",
    "Instance": "vm",
}

_cached_graph: dict = {"nodes": [], "edges": [], "timestamp": None}
_lock = threading.Lock()
_project_permissions: dict = {}  # {project_id: (bool, timestamp)} — per-project IAM cache
_permissions_lock = threading.Lock()
_PERMISSION_TTL_OK = 3600       # 1 hour for successful checks
_PERMISSION_TTL_FAIL = 300      # 5 min for failed checks (retry sooner)


def _ref(url: str) -> str:
    """Extract last path segment from a GCP resource URL."""
    return url.rsplit("/", 1)[-1] if url else ""


def _short_type(asset_type: str) -> str:
    """compute.googleapis.com/Instance -> Instance"""
    return asset_type.rsplit("/", 1)[-1]


def _node_id(asset_type: str, name: str) -> str:
    prefix = ID_PREFIX.get(_short_type(asset_type), "res")
    return f"{prefix}-{name}"


def _parse_zone(data: dict) -> str:
    zone = data.get("zone", "")
    return zone.rsplit("/", 1)[-1] if "/" in zone else (zone or GCP_ZONE)


def _check_permissions(project_id: str) -> bool:
    """IAM preflight — verify cloudasset.assets.listResource per project.

    Results are cached with TTL: 1h for success, 5min for failure (retries sooner).
    """
    now = time.time()
    with _permissions_lock:
        cached = _project_permissions.get(project_id)
    if cached is not None:
        allowed, ts = cached
        ttl = _PERMISSION_TTL_OK if allowed else _PERMISSION_TTL_FAIL
        if now - ts < ttl:
            return allowed
    try:
        from google.cloud import asset_v1
        client = asset_v1.AssetServiceClient()
        resp = client.list_assets(request={
            "parent": f"projects/{project_id}",
            "asset_types": ["compute.googleapis.com/Instance"],
            "content_type": asset_v1.types.ContentType.RESOURCE,
            "page_size": 1,
        })
        for _ in resp:
            break
        with _permissions_lock:
            _project_permissions[project_id] = (True, now)
        logger.info(f"IAM preflight passed for {project_id}")
        return True
    except Exception as e:
        with _permissions_lock:
            _project_permissions[project_id] = (False, now)
        logger.warning(f"IAM preflight failed for {project_id}: {e}")
        return False


def _list_assets(project_id: str) -> list:
    """Fetch relevant assets from Cloud Asset Inventory."""
    from google.cloud import asset_v1
    client = asset_v1.AssetServiceClient()
    resp = client.list_assets(request={
        "parent": f"projects/{project_id}",
        "asset_types": ASSET_TYPES,
        "content_type": asset_v1.types.ContentType.RESOURCE,
        "page_size": 500,
    })
    return [{"asset_type": a.asset_type, "name": a.name,
             "data": dict(a.resource.data) if a.resource and a.resource.data else {}}
            for a in resp]


def _resolve_ig_members(project_id: str, zone: str, group_name: str) -> list:
    """Resolve instance group members via Compute API."""
    from google.cloud import compute_v1
    try:
        client = compute_v1.InstanceGroupsClient()
        resp = client.list_instances(
            project=project_id, zone=zone, instance_group=group_name)
        return [_ref(item.instance) for item in resp]
    except Exception as e:
        logger.warning(f"Failed to resolve instance group {group_name}: {e}")
        return []


def _make_node(asset_type: str, name: str, data: dict,
               project: str = "", env: str = "",
               project_id: str = "") -> Node:
    """Create a Node from an asset."""
    st = _short_type(asset_type)
    meta = TYPE_META.get(st, ("lb", "shield", st))
    node_type, icon, prefix = meta
    label = f"{prefix}: {name}" if prefix else name

    status = "healthy"
    metrics = {}
    if st == "Instance":
        status = GCP_STATUS_MAP.get(data.get("status", ""), "unknown")
        metrics = {
            "machine_type": _ref(data.get("machineType", "")),
            "zone": _parse_zone(data),
            "confidential": (
                data.get("confidentialInstanceConfig", {}).get(
                    "confidentialInstanceType") in ("SEV", "SEV_SNP", "TDX")
                or bool(data.get("confidentialInstanceConfig", {}).get(
                    "enableConfidentialCompute"))),
        }
    elif st == "ForwardingRule":
        metrics = {"ip": data.get("IPAddress", ""),
                   "port_range": data.get("portRange", "")}

    return Node(
        id=_node_id(asset_type, name), label=label, type=node_type,
        status=status, icon=icon, metrics=metrics,
        source="discovered", gcp_resource_type=asset_type,
        project=project, env=env, project_id=project_id,
    )


# Relationship rules: (source_type, data_field, target_prefix)
_EDGE_RULES = [
    ("ForwardingRule",    "target",         "proxy", "routes_to"),
    ("TargetHttpsProxy",  "urlMap",         "urlmap", "uses_map"),
    ("UrlMap",            "defaultService", "bs",     "default_backend"),
]


def build_graph(project_id: str = None, project: str = "",
                env: str = "") -> dict:
    """Build topology graph from GCP Cloud Asset Inventory.

    Infers: ForwardingRule -> Proxy -> UrlMap -> BackendService -> IG -> VMs.
    project/env: product name and environment for tagging nodes.
    """
    project_id = project_id or GCP_PROJECT_ID
    if not _check_permissions(project_id):
        return {"nodes": [], "edges": []}

    raw_assets = _list_assets(project_id)

    by_type: dict[str, list] = {}
    for asset in raw_assets:
        by_type.setdefault(_short_type(asset["asset_type"]), []).append(asset)

    nodes = []
    edges = []

    # Process all asset types and create nodes
    for asset in raw_assets:
        data = asset["data"]
        name = data.get("name", _ref(asset["name"]))
        nodes.append(_make_node(asset["asset_type"], name, data,
                                project=project, env=env,
                                project_id=project_id))

    # Infer edges from simple field references
    for src_type, field, tgt_prefix, label in _EDGE_RULES:
        for asset in by_type.get(src_type, []):
            data = asset["data"]
            name = data.get("name", _ref(asset["name"]))
            target = _ref(data.get(field, ""))
            if target:
                edges.append(Edge(
                    source=_node_id(f"compute.googleapis.com/{src_type}", name),
                    target=f"{tgt_prefix}-{target}", label=label))

    # BackendService -> InstanceGroup + SecurityPolicy
    for asset in by_type.get("BackendService", []):
        data = asset["data"]
        name = data.get("name", _ref(asset["name"]))
        src_id = f"bs-{name}"
        for backend in data.get("backends", []):
            group = _ref(backend.get("group", ""))
            if group:
                edges.append(Edge(source=src_id, target=f"ig-{group}",
                                  label="uses_backend"))
        policy = _ref(data.get("securityPolicy", ""))
        if policy:
            edges.append(Edge(source=src_id, target=f"sp-{policy}",
                              label="protected_by"))

    # InstanceGroup -> Instance members (via Compute API)
    for asset in by_type.get("InstanceGroup", []):
        data = asset["data"]
        name = data.get("name", _ref(asset["name"]))
        zone = _parse_zone(data)
        members = _resolve_ig_members(project_id, zone, name)
        for member in members:
            edges.append(Edge(source=f"ig-{name}", target=f"vm-{member}",
                              label="member"))

    return {"nodes": nodes, "edges": edges}


def discover(project_id: str = None) -> dict:
    """Run discovery and cache the result. Thread-safe."""
    global _cached_graph
    project_id = project_id or GCP_PROJECT_ID
    try:
        result = build_graph(project_id)
        with _lock:
            _cached_graph = {
                "nodes": result["nodes"],
                "edges": result["edges"],
                "timestamp": time.time(),
            }
        logger.info(f"Discovery: {len(result['nodes'])} nodes, "
                    f"{len(result['edges'])} edges")
    except Exception as e:
        logger.error(f"Discovery failed: {e}")
    return get_cached_graph()


def get_cached_graph() -> dict:
    """Return last discovered graph."""
    with _lock:
        return dict(_cached_graph)


def discovery_loop(interval: int):
    """Background discovery loop."""
    stop = threading.Event()
    discover()
    while not stop.wait(interval):
        discover()
