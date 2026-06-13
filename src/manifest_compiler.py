# File: src/manifest_compiler.py
# Purpose: Manifest compiler — Inherit → Hydrate → Validate → Verify
# Ensures every node is complete and reachable before reaching dashboard.
# Raw YAML → Compiled manifest with verification status per node.

import ipaddress
import logging
import socket
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# SSRF protection: block probes to internal/metadata URLs
_BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1", "0.0.0.0"}
_BLOCKED_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.",
                     "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.",
                     "172.28.", "172.29.", "172.30.", "172.31.", "192.168.")

# Node-type-registry: default log filters by node type (REQ-212).
# Provides logs for every node by default; manifest authors can override per-node.
_SECRETMANAGER_LOG_FILTER = (
    'resource.type="audited_resource" AND '
    'protoPayload.serviceName="secretmanager.googleapis.com"'
)
LOG_DEFAULTS = {
    "mig": 'resource.type="gce_instance"',
    "load_balancer": 'resource.type="gce_instance"',
    "vm": 'resource.type="gce_instance"',
    "gpu": 'resource.type="gce_instance"',
    "cloud_run": 'resource.type="cloud_run_revision"',
    "secret": _SECRETMANAGER_LOG_FILTER,
    "database": 'resource.type="cloudsql_database"',
    "storage": 'resource.type="gcs_bucket"',
    "cache": 'resource.type="redis_instance"',
    "registry": 'resource.type="cloud_build"',
}

# Verification tiers (REQ-602)
MANDATORY_TYPES = {"load_balancer", "mig", "cloud_run", "secret"}
EXPECTED_OFFLINE_KEY = "expected_offline"  # YAML field: expected_offline: true
OPTIONAL_TYPES = {"storage", "cache", "registry", "database", "provider"}

# Cache: verified solutions don't need re-verification
# Key: "{product}/{solution}/{env}" — includes solution to prevent cross-solution collisions
_verified_solutions = {}


def _is_safe_url(url: str) -> bool:
    """Check URL is not targeting internal/metadata endpoints (SSRF protection).

    Resolves DNS first to prevent rebinding (nip.io), IPv6-mapped IPv4,
    and hex/octal IP encoding bypasses.
    """
    try:
        parsed = urlparse(url)
        # Only allow http/https schemes
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        if not host:
            return False
        if host in _BLOCKED_HOSTS or host.startswith(_BLOCKED_PREFIXES):
            return False
        # Resolve DNS and check ALL resolved IPs — blocks rebinding attacks
        try:
            addrs = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except (socket.gaierror, socket.timeout, OSError):
            return False  # Can't resolve / timeout → block
        if not addrs:
            return False  # Empty resolution → fail-closed
        for family, _, _, _, sockaddr in addrs:
            try:
                ip = ipaddress.ip_address(sockaddr[0])
                # Check IPv6-mapped IPv4 (e.g., ::ffff:10.0.0.1)
                mapped = getattr(ip, 'ipv4_mapped', None)
                if mapped is not None:
                    if mapped.is_private or mapped.is_loopback or mapped.is_link_local or mapped.is_reserved:
                        return False
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False
            except ValueError:
                return False  # Unparseable resolved addr → block
        return True
    except Exception:
        return False


def _verify_http_probe(url: str, timeout_s: int = 10) -> dict:
    """Probe an HTTP endpoint. Returns {ok, latency_ms, error}."""
    if not _is_safe_url(url):
        return {"ok": False, "latency_ms": None, "status_code": None,
                "error": f"URL blocked: {url} targets internal/metadata endpoint"}
    try:
        import httpx
        resp = httpx.get(url, timeout=timeout_s, follow_redirects=False)
        return {"ok": resp.status_code == 200, "latency_ms": round(resp.elapsed.total_seconds() * 1000),
                "status_code": resp.status_code, "error": None}
    except Exception as e:
        return {"ok": False, "latency_ms": None, "status_code": None, "error": str(e)}


def _verify_gcp_secret(project: str, secret_name: str) -> dict:
    """Verify Secret Manager is accessible (metadata only)."""
    try:
        import google.auth
        import google.auth.transport.requests
        import httpx
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        url = f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{secret_name}"
        resp = httpx.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=10)
        return {"ok": resp.status_code == 200, "error": None if resp.status_code == 200 else f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _verify_gcp_resource_exists(project: str, zone_or_region: str, resource_name: str,
                                resource_type: str = "instances",
                                regional: bool = False) -> dict:
    """Verify a GCP Compute resource exists (even if TERMINATED). REQ-602.

    Supports zonal (instances, instanceGroupManagers) and regional resources.
    """
    try:
        import google.auth
        import google.auth.transport.requests
        import httpx
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        scope = "regions" if regional else "zones"
        url = (f"https://compute.googleapis.com/compute/v1/projects/{project}"
               f"/{scope}/{zone_or_region}/{resource_type}/{resource_name}")
        resp = httpx.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=10)
        return {"ok": resp.status_code == 200, "error": None if resp.status_code == 200
                else f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _verify_logs_accessible(project: str, log_filter: str) -> dict:
    """Verify Cloud Logging filter is valid and IAM allows access."""
    try:
        from google.cloud.logging_v2 import Client
        from datetime import datetime, timezone, timedelta
        client = Client(project=project)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        filter_str = f'({log_filter}) AND timestamp>="{cutoff.isoformat()}"'
        # Just try to list — if IAM or filter is wrong, this throws
        entries = list(client.list_entries(filter_=filter_str, max_results=1))
        return {"ok": True, "has_data": len(entries) > 0, "error": None}
    except Exception as e:
        return {"ok": False, "has_data": False, "error": str(e)}


def _verify_node(node: dict) -> dict:
    """Verify a single node's reachability. Returns verification result."""
    node_id = node.get("id", "unknown")
    node_type = node.get("type", "infra")
    monitoring = node.get("monitoring") or {}
    probe = monitoring.get("probe") or {}
    logs = monitoring.get("logs") or []
    project_id = node.get("project_id", "")
    expected_offline = node.get(EXPECTED_OFFLINE_KEY, False)

    result = {
        "node_id": node_id,
        "tier": "optional",
        "probe_result": None,
        "logs_result": None,
        "status": "skipped",
        "errors": [],
    }

    # Determine tier
    if node_type in MANDATORY_TYPES:
        result["tier"] = "mandatory"
    elif expected_offline:
        result["tier"] = "expected_offline"
    elif node_type in OPTIONAL_TYPES:
        result["tier"] = "optional"

    # --- Probe verification ---
    probe_type = probe.get("type", "")
    if probe_type == "http":
        url = probe.get("url", "")
        if url:
            result["probe_result"] = _verify_http_probe(url, probe.get("timeout_s", 10))
    elif probe_type == "gcp_secret":
        result["probe_result"] = _verify_gcp_secret(
            probe.get("project", project_id), probe.get("secret_name", ""))
    elif probe_type == "gcp_vm_status":
        # VM/MIG existence check — verify resource exists in GCP (even if TERMINATED)
        result["probe_result"] = _verify_gcp_resource_exists(
            probe.get("project", project_id),
            probe.get("zone", probe.get("region", "")),
            probe.get("resource_name", node_id),
            probe.get("resource_type", "instances"),
            regional=probe.get("regional", False),
        )
    elif probe_type == "log_accessibility":
        # 4th probe type: verify logs are accessible (REQ-601)
        log_project = probe.get("project", project_id)
        log_filter = probe.get("filter", "")
        if log_filter and log_project:
            result["probe_result"] = _verify_logs_accessible(log_project, log_filter)
    elif probe_type in ("platform_provider", "platform_inference"):
        # Providers are probed at runtime by manifest_metrics (REQ-219 platform_inference;
        # platform_provider retained for backwards compat with any unmigrated manifests).
        result["probe_result"] = {"ok": True, "error": None}

    # --- Log verification (auto-check from monitoring.logs if no explicit log probe) ---
    if not (probe_type == "log_accessibility") and logs:
        log_cfg = logs[0]
        log_project = log_cfg.get("project", project_id)
        log_filter = log_cfg.get("filter", "")
        if log_filter and log_project:
            result["logs_result"] = _verify_logs_accessible(log_project, log_filter)

    # --- Determine status (collect ALL errors, not short-circuit) ---
    if result["tier"] == "mandatory":
        errors = []
        # Check probe
        if not result["probe_result"]:
            errors.append("No probe configured for mandatory node")
        elif not result["probe_result"]["ok"]:
            errors.append(f"Probe failed: {result['probe_result'].get('error', 'unreachable')}")
        # Check logs (REQ-602: mandatory nodes require discoverable logs)
        if not result["logs_result"]:
            errors.append("No logs configured or discoverable for mandatory node (REQ-602)")
        elif not result["logs_result"]["ok"]:
            errors.append(f"Logs inaccessible: {result['logs_result'].get('error', 'unknown')}")
        elif not result["logs_result"].get("has_data", False):
            errors.append("Logs filter valid but no log entries found (mandatory node requires discoverable logs)")
        # Determine status — report, not gate (REQ-603)
        if errors:
            result["status"] = "failed"
            result["errors"] = errors
        else:
            result["status"] = "verified"
    elif result["tier"] == "expected_offline":
        # REQ-602: declared capability — resource may not exist yet (e.g. on-demand GPU)
        # If probe is configured and passes, great. If not, that's fine — it's declared.
        if result["probe_result"] and result["probe_result"]["ok"]:
            result["status"] = "confirmed_exists"
        else:
            result["status"] = "declared"  # on-demand, not yet provisioned
    elif result["tier"] == "optional":
        if result["probe_result"] and result["probe_result"]["ok"]:
            result["status"] = "verified"
        else:
            result["status"] = "unverified"

    return result


def _compile_node(node: dict, header: dict, connected_ids: set,
                  warnings: list, verification_report: list,
                  verify: bool, solution_key: str) -> dict:
    """Compile a single node: inherit → hydrate → validate → verify → recurse children."""
    node = dict(node)
    node_id = node.get("id", "unknown")
    node_type = node.get("type", "infra")

    # === STEP 1: INHERIT ===
    node.setdefault("project_id", header["project_id"])
    node.setdefault("project", header["product"])
    node.setdefault("env", header["environment"])
    node.setdefault("environment", header["environment"])
    node.setdefault("solution", header["solution"])
    node.setdefault("company", header["company"])

    # === STEP 2: HYDRATE (REQ-212) ===
    # When YAML omits monitoring.logs for a typed node, fill from LOG_DEFAULTS so
    # logs are visible everywhere by default. Explicit YAML declarations are preserved.
    monitoring = node.get("monitoring") or {}
    if not monitoring.get("logs") and node_type in LOG_DEFAULTS:
        log_filter = LOG_DEFAULTS[node_type]
        if node_type == "cloud_run":
            service_name = node_id.replace("gh-", "").replace("tr-", "")
            log_filter += f' AND resource.labels.service_name="{service_name}"'
        monitoring["logs"] = [{"project": header["project_id"], "filter": log_filter}]
        node["monitoring"] = monitoring

    # === STEP 3: VALIDATE ===
    if node_id not in connected_ids and node_type not in ("provider",):
        warnings.append(f"WARN: {node_id} has no edges (orphaned)")
    if not monitoring.get("probe") and not monitoring.get("metrics") and not monitoring.get("logs"):
        if node_type not in ("provider", "storage", "cache", "registry", "database", "container", "application"):
            warnings.append(f"WARN: {node_id} has no monitoring configured")
    if node.get("cost_yearly_usd") is None and node_type not in ("provider", "container", "application"):
        warnings.append(f"INFO: {node_id} has no cost_yearly_usd")

    # === STEP 4: VERIFY ===
    if verify and solution_key not in _verified_solutions:
        vr = _verify_node(node)
        verification_report.append(vr)
        node["_verification"] = vr["status"]

    # === STEP 5: RECURSE CHILDREN ===
    if "children" in node:
        compiled_children = []
        for child in node["children"]:
            compiled_child = _compile_node(
                child, header, connected_ids, warnings,
                verification_report, verify, solution_key)
            compiled_children.append(compiled_child)
        node["children"] = compiled_children

    # Preserve children_template as-is (resolved at discovery time)
    return node


def compile_manifest(manifest: dict, verify: bool = False) -> dict:
    """Compile a single flattened manifest: inherit → hydrate → validate → verify.

    Args:
        manifest: flattened manifest dict (one environment)
        verify: if True, probe endpoints (REQ-601). False = skip probing.
    """
    manifest = dict(manifest)
    project_id = manifest.get("project_id", "")
    environment = manifest.get("environment", "")
    solution = manifest.get("solution", "")
    company = manifest.get("company", "")
    product = manifest.get("product", "")
    solution_key = f"{product}/{solution}/{environment}"

    header = {
        "project_id": project_id, "product": product, "environment": environment,
        "solution": solution, "company": company,
    }

    nodes = manifest.get("nodes", [])
    edges = manifest.get("edges", [])
    edge_sources = {e.get("source") for e in edges}
    edge_targets = {e.get("target") for e in edges}
    connected_ids = edge_sources | edge_targets

    compiled_nodes = []
    warnings = []
    verification_report = []

    for node in nodes:
        compiled = _compile_node(node, header, connected_ids, warnings,
                                 verification_report, verify, solution_key)
        compiled_nodes.append(compiled)

    # Log warnings
    for w in warnings:
        logger.info(f"Manifest compiler [{solution_key}]: {w}")

    # Build verification report summary (REQ-603: informational, not a gate)
    report_summary = {"verified": 0, "failed": 0, "declared": 0, "unverified": 0}
    if verify and verification_report:
        for vr in verification_report:
            s = vr["status"]
            if s == "verified":
                report_summary["verified"] += 1
            elif s == "failed":
                report_summary["failed"] += 1
                logger.warning(f"FAILED [{solution_key}]: {vr['node_id']} — {', '.join(vr['errors'])}")
            elif s in ("declared", "confirmed_exists"):
                report_summary["declared"] += 1
            else:
                report_summary["unverified"] += 1
        # Cache report for subsequent lookups
        _verified_solutions[solution_key] = {
            "verified_at": time.time(),
            "report": verification_report,
            "summary": report_summary,
        }
        logger.info(f"REPORT [{solution_key}]: {report_summary}")

    manifest["nodes"] = compiled_nodes
    manifest["_compiled"] = True
    manifest["_warnings"] = warnings
    manifest["_verification_report"] = verification_report
    manifest["_report_summary"] = report_summary if verification_report else {}

    return manifest


def compile_all(manifests: list, verify: bool = False) -> list:
    """Compile all manifests. If verify=True, probe endpoints on first upload."""
    return [compile_manifest(m, verify=verify) for m in manifests]


def get_verification_status(product: str, solution: str, environment: str) -> dict:
    """Check if a solution has been verified."""
    key = f"{product}/{solution}/{environment}"
    return _verified_solutions.get(key)


def reset_verification(product: str = None, solution: str = None, environment: str = None):
    """Reset verification cache — forces re-verification on next compile."""
    if product and solution and environment:
        _verified_solutions.pop(f"{product}/{solution}/{environment}", None)
    elif product:
        # Reset all envs for a product
        to_remove = [k for k in _verified_solutions if k.startswith(f"{product}/")]
        for k in to_remove:
            _verified_solutions.pop(k, None)
    else:
        _verified_solutions.clear()
