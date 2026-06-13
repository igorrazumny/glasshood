# File: src/api/routes/topology.py
# Purpose: GET /api/topology — assembled from discovery + YAML + collector enrichment

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

from src.api.routes.auth import verify_token
from src.collectors import coldvault, gcp_logging, gcp_monitoring, gcs_bucket, manifest_metrics
from src.config.settings import TOPOLOGY_OVERRIDES_PATH, DISCOVERY_ENABLED, ORG_DISCOVERY_ENABLED
from src.discovery.gcp_assets import get_cached_graph
from src.discovery.yaml_overlay import load_overrides, merge_topology
from src.discovery.diff import update_snapshot, get_diff
from src.models.topology import Node, Edge, Topology

router = APIRouter(tags=["topology"])

_probe_timeout = 5  # seconds


def _probe_health(url: str) -> str:
    """Probe a health URL. Returns 'healthy' or 'offline'."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        import httpx
        resp = httpx.get(url, timeout=_probe_timeout)
        return "healthy" if resp.status_code == 200 else "degraded"
    except Exception as e:
        logger.debug(f"Health probe failed for {url}: {e}")
        return "offline"


def _enrich_nodes(nodes: list, edges: list) -> None:
    """Enrich nodes in-place with live data from collectors.

    Hardware-only: enrich VMs with system metrics, LB with latency,
    GPUs with health probes. Software components removed.
    """
    health = coldvault.get_health()
    metrics = coldvault.get_metrics()
    monitoring_stats = gcp_monitoring.get_stats()
    stale = coldvault.is_stale()
    now_iso = datetime.now(timezone.utc).isoformat()

    cv_status = health.get("status", "unknown")
    if cv_status == "unreachable":
        cv_status = "error"
    elif cv_status != "healthy":
        cv_status = "unknown"

    system = metrics.get("system", {})
    lb_latency = monitoring_stats.get("lb_latency_ms")
    lb_reqs = monitoring_stats.get("lb_request_count_1h", 0)

    for node in nodes:
        node.last_checked = now_iso

        # Discovered VM nodes — enrich with system metrics
        if node.type == "vm" and node.source == "discovered":
            if stale:
                node.status = "stale"
            elif node.status == "healthy":
                node.status = cv_status
            node.metrics.update({
                "ram_percent": system.get("ram_used_percent", health.get("ram_percent")),
                "disk_percent": system.get("disk_used_percent"),
                "uptime_s": metrics.get("uptime_seconds", health.get("uptime_seconds")),
                "version": metrics.get("version", health.get("version")),
                "cpu_percent": monitoring_stats.get("vm_cpu_percent"),
            })
            continue

        # Discovered LB / ForwardingRule nodes
        if node.type == "lb" and node.source == "discovered" and node.id.startswith("fr-"):
            lb_status = "degraded" if lb_latency and lb_latency > 1000 else "healthy"
            node.status = lb_status
            node.metrics.update({"latency_ms": lb_latency, "requests_1h": lb_reqs})
            continue

        # GPU nodes with health probing
        if node.type == "gpu" and node.status == "auto":
            health_url = node.metrics.get("health_url")
            if health_url:
                node.status = _probe_health(health_url)
            else:
                node.status = "offline"
            continue

    # Enrich edge statuses
    node_status = {n.id: n.status for n in nodes}
    for edge in edges:
        if edge.status in ("auto", "unknown"):
            edge.status = node_status.get(edge.target, "unknown")


def inherit_parent_status(children, parent_status: str):
    """Recursively set each child's status to parent_status if unset (REQ-702).

    Template children (Docker, Application) have no direct monitoring —
    they inherit the VM's health because they live inside it.
    """
    if not children:
        return
    for child in children:
        if isinstance(child, dict):
            if not child.get("status") or child.get("status") == "unknown":
                child["status"] = parent_status
            inherit_parent_status(child.get("children"), parent_status)


def walk_children_connects_to(children, child_ids: set, edges_out: list):
    """Walk resolved children tree: collect IDs and create edges from connects_to (REQ-702)."""
    if not children:
        return
    for child in children:
        child_id = child.get("id") if isinstance(child, dict) else None
        if child_id:
            child_ids.add(child_id)
        targets = child.get("connects_to") if isinstance(child, dict) else None
        if child_id and isinstance(targets, list):
            for target in targets:
                edges_out.append(Edge(
                    source=child_id, target=target,
                    label="", status="healthy",
                ))
        # receives_from: incoming edges TO this child from declared sources
        sources = child.get("receives_from") if isinstance(child, dict) else None
        if child_id and isinstance(sources, list):
            for source in sources:
                edges_out.append(Edge(
                    source=source, target=child_id,
                    label="", status="healthy",
                ))
        nested = child.get("children") if isinstance(child, dict) else None
        walk_children_connects_to(nested, child_ids, edges_out)


def _build_topology() -> dict:
    """Assemble topology: discovered + YAML + collector enrichment."""
    logging_stats = gcp_logging.get_stats()
    metrics = coldvault.get_metrics()
    security = metrics.get("security", {})
    user_stats = metrics.get("user_stats", {})

    # Get discovered graph — multi-project when org discovery enabled
    if ORG_DISCOVERY_ENABLED:
        from src.discovery.multi_project import get_combined_topology
        graph = get_combined_topology()
    else:
        graph = get_cached_graph()
    discovered_nodes = graph.get("nodes", [])
    discovered_edges = graph.get("edges", [])

    # Merge with YAML overrides (infrastructure nodes)
    overrides = load_overrides(TOPOLOGY_OVERRIDES_PATH)
    nodes, edges = merge_topology(discovered_nodes, discovered_edges, overrides)

    # HARD FILTER: Strip org-discovery VMs that aren't MIG-managed.
    # Both org-discovery and MIG-discovery create vm-* IDs (gcp_assets.py line 44).
    # Only keep: non-discovered nodes + MIG-discovered VMs (have _parent in cache)
    mig_vm_ids = {nid for nid, d in manifest_metrics.get_all_statuses().items()
                  if d.get("_parent")}
    nodes = [n for n in nodes
             if n.source != "discovered"
             or n.type != "vm"
             or n.id in mig_vm_ids]

    existing_ids = {n.id for n in nodes}

    # Inject project nodes from org discovery (all discovered projects, even empty)
    if ORG_DISCOVERY_ENABLED:
        from src.discovery.org_projects import get_cached_projects
        from src.discovery.multi_project import get_project_topology
        seen_products = set()  # deduplicate legacy vs new project IDs
        for proj in get_cached_projects():
            proj_node_id = f"proj_{proj['project_id']}"
            if proj_node_id in existing_ids:
                continue
            # Deduplicate: skip legacy project if canonical nr-* exists for same product+env
            product_env = (proj.get("product", ""), proj.get("environment", ""))
            if product_env[0] and product_env in seen_products:
                continue
            if product_env[0]:
                seen_products.add(product_env)
            topo = get_project_topology(proj["project_id"])
            node_count = len(topo["nodes"])
            # ACTIVE projects are healthy (green) — they exist and are monitored
            is_active = proj.get("state", "") == "ACTIVE"
            nodes.append(Node(
                id=proj_node_id,
                label=proj.get("display_name") or proj["project_id"],
                type="project",
                status="healthy" if is_active else "unknown",
                source="org_discovery",
                project=proj.get("product", ""),
                env=proj.get("environment", ""),
                project_id=proj["project_id"],
                metrics={"node_count": node_count, "state": proj.get("state", "ACTIVE")},
            ))
            existing_ids.add(proj_node_id)

    # Enrich with live collector data
    _enrich_nodes(nodes, edges)

    # Inject manifest metric data for frontend enrichment
    # manifestLayout.js looks up topology nodes by ID (topoMap) to merge status/metrics
    manifest_statuses = manifest_metrics.get_all_statuses()
    node_by_id = {n.id: n for n in nodes}
    for node_id, mdata in manifest_statuses.items():
        # Timing + description data for frontend display
        extra_metrics = {
            **mdata.get("metrics", {}),
            "_check_description": mdata.get("check_description"),
            "_last_poll": mdata.get("last_poll"),
            "_poll_interval_s": mdata.get("poll_interval_s"),
            "_parent": mdata.get("_parent"),
        }
        if node_id in node_by_id:
            node = node_by_id[node_id]
            mstatus = mdata.get("status", "unknown")
            if mstatus and mstatus != "unknown":
                node.status = mstatus
            node.metrics.update(extra_metrics)
        else:
            # Skip discovered children (VMs) — they're injected below
            if mdata.get("_parent"):
                continue
            nodes.append(Node(
                id=node_id,
                label=node_id,
                type="infra",
                status=mdata.get("status", "unknown"),
                source="manifest",
                metrics=extra_metrics,
            ))
            existing_ids.add(node_id)

    # Inject discovered VMs as children of MIG nodes (with nested children from template)
    for node_id, mdata in manifest_statuses.items():
        if not mdata.get("_parent"):
            continue
        # Resolve children_template for this VM
        parent_id = mdata["_parent"]
        template = manifest_metrics.get_children_template(parent_id)
        vm_name = node_id.replace("vm-", "")
        vm_id = str(mdata.get("metrics", {}).get("instance_id", ""))
        resolved_children = manifest_metrics.resolve_children_template(template, vm_name, vm_id) if template else []
        # Children inherit VM status — they have no direct monitoring (REQ-702)
        vm_status = mdata.get("status", "unknown")
        inherit_parent_status(resolved_children, vm_status)
        # If VM already exists (from org discovery), attach children + parent metadata
        if node_id in existing_ids:
            if node_id in node_by_id:
                existing_node = node_by_id[node_id]
                if resolved_children:
                    existing_node.children = resolved_children
                existing_node.metrics["_parent"] = parent_id
                existing_node.metrics["_label"] = mdata.get("_label", node_id)
                existing_node.status = mdata.get("status", existing_node.status)
            continue
        nodes.append(Node(
            id=node_id,
            label=mdata.get("_label", node_id),
            type=mdata.get("_type", "vm"),
            status=mdata.get("status", "unknown"),
            source="discovered",
            children=resolved_children if resolved_children else None,
            metrics={
                **mdata.get("metrics", {}),
                "_check_description": mdata.get("check_description"),
                "_last_poll": mdata.get("last_poll"),
                "_poll_interval_s": mdata.get("poll_interval_s"),
                "_parent": mdata.get("_parent"),
            },
        ))
        existing_ids.add(node_id)
        # Add edge from parent (MIG) to VM
        edges.append(Edge(
            source=mdata["_parent"], target=node_id, label="", status="healthy"
        ))

    # Create edges from connects_to declarations on children (REQ-702)
    child_ids = set()
    for node in nodes:
        walk_children_connects_to(node.children, child_ids, edges)

    # Defense-in-depth: filter edges to known IDs (top-level + children + @group refs)
    allowed_ids = {n.id for n in nodes} | child_ids
    edges = [e for e in edges
             if (e.source in allowed_ids or e.source.startswith("@"))
             and (e.target in allowed_ids or e.target.startswith("@"))]

    # Layer 1: evaluate deterministic rules against enriched state
    monitoring_stats = gcp_monitoring.get_stats()
    from src.security.cve_scanner import get_stats as get_security_stats
    security_stats = get_security_stats()
    from src.security.anomaly_detector import update_baselines, detect_anomalies
    from src.security.anomaly_detector import get_stats as get_anomaly_stats
    from src.config.settings import ANOMALY_DETECTION_ENABLED
    anomaly_list = []
    if ANOMALY_DETECTION_ENABLED:
        update_baselines(monitoring_stats, logging_stats)
        anomaly_list = detect_anomalies(monitoring_stats, logging_stats, security_stats)
    anomaly_stats = get_anomaly_stats()
    from src.rules.engine import evaluate_rules
    alerts = evaluate_rules(nodes, {
        "monitoring": monitoring_stats,
        "logging": logging_stats,
        "security": security_stats,
        "anomaly": anomaly_stats,
    })

    # Correlate operational alerts with anomalies (pharma data integrity)
    from src.security.correlator import correlate
    correlated = correlate(alerts, anomaly_list)
    all_alerts = alerts + correlated

    # Propagate alert severity to project nodes (green → yellow/red based on alerts)
    if all_alerts:
        node_project = {n.id: n.project for n in nodes if n.project}
        project_worst = {}  # project_field → worst severity
        for alert in all_alerts:
            nid = alert.node_id if hasattr(alert, 'node_id') else alert.get("node_id", "")
            proj = node_project.get(nid or "", "")
            if not proj:
                continue
            sev = alert.severity if hasattr(alert, 'severity') else alert.get("severity", "info")
            if sev == "critical":
                project_worst[proj] = "error"
            elif sev == "warning" and project_worst.get(proj) != "error":
                project_worst[proj] = "degraded"
        for node in nodes:
            if node.type == "project" and node.project in project_worst:
                node.status = project_worst[node.project]

    # Compute diff from previous snapshot
    update_snapshot(nodes)

    topology = Topology(nodes=nodes, edges=edges)
    topology.update_overall_status()
    result = topology.to_dict()

    result["topology_diff"] = get_diff()
    result["logging"] = {
        "error_count_15m": logging_stats.get("error_count_15m", 0),
        "recent_errors": logging_stats.get("recent_errors", []),
    }
    result["security"] = security
    result["user_stats"] = user_stats
    result["alerts"] = [a.to_dict() for a in all_alerts]
    result["anomalies"] = anomaly_list
    _apply_anomaly_classification(result, anomaly_list)

    return result


def _apply_anomaly_classification(result: dict, anomaly_list: list) -> None:
    """REQ-004: attach a topology-level classification summary in a way that
    cannot crash /api/topology. A malformed anomaly is logged and the field
    is omitted; per-alert classifications still travel on each Alert."""
    if not anomaly_list:
        return
    try:
        from src.security.anomaly_detector import classify_anomalies
        result["anomaly_classification"] = classify_anomalies(anomaly_list)
    except Exception as e:
        logger.warning(f"REQ-004: classify_anomalies failed in topology build: {e}")


@router.get("/api/topology")
def get_topology(request: Request):
    """Return full topology state. Requires auth token."""
    verify_token(request)
    return _build_topology()


def get_topology_data() -> dict:
    """Get topology data for internal use (analysis)."""
    return _build_topology()
