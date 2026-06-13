# File: src/collectors/manifest_metrics.py
# Purpose: Poll GCP Cloud Monitoring based on YAML manifest monitoring config
# REQ-203: Each node declares metrics/thresholds in YAML — no hardcoded logic

import copy
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_metrics_cache: dict = {}  # node_id -> {status, metrics, last_poll}
_lock = threading.Lock()
_POLL_INTERVAL = 60  # seconds
_client = None  # singleton MetricServiceClient


def _get_client():
    """Get or create a singleton MetricServiceClient (thread-safe)."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:  # double-check after acquiring lock
                from google.cloud.monitoring_v3 import MetricServiceClient
                _client = MetricServiceClient()
    return _client


def _parse_threshold(threshold_str: str, value: float) -> bool:
    """Evaluate a threshold like '< 500' or '>= 2000' against a value."""
    if not threshold_str or not isinstance(threshold_str, str):
        return False
    threshold_str = threshold_str.strip()
    try:
        if threshold_str.startswith("<= "):
            return value <= float(threshold_str[3:])
        elif threshold_str.startswith("< "):
            return value < float(threshold_str[2:])
        elif threshold_str.startswith(">= "):
            return value >= float(threshold_str[3:])
        elif threshold_str.startswith("> "):
            return value > float(threshold_str[2:])
        elif threshold_str.startswith("== "):
            return value == float(threshold_str[3:])
    except (ValueError, TypeError):
        pass
    return False


def _evaluate_status(value: float, thresholds: dict) -> str:
    """Determine status from value and threshold config.

    Check healthy FIRST (most specific/narrow range), then degraded, then error.
    A 200ms latency with healthy="< 500", degraded="< 2000" correctly returns
    "healthy" instead of "degraded".
    """
    if not thresholds:
        return None  # informational metric — no status contribution
    if thresholds.get("healthy") and _parse_threshold(thresholds["healthy"], value):
        return "healthy"
    if thresholds.get("degraded") and _parse_threshold(thresholds["degraded"], value):
        return "degraded"
    if thresholds.get("error") and _parse_threshold(thresholds["error"], value):
        return "error"
    return "unknown"


def _poll_metric(project: str, metric_type: str, resource_filter: str,
                 aggregation: str, multiplier: float = 1.0):
    """Query Cloud Monitoring for a single metric type with resource-level filter."""
    try:
        from google.cloud.monitoring_v3 import MetricServiceClient, ListTimeSeriesRequest
        from google.protobuf.timestamp_pb2 import Timestamp
        from datetime import datetime, timezone, timedelta

        client = _get_client()
        project_name = f"projects/{project}"
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)

        start_ts = Timestamp()
        start_ts.FromDatetime(start)
        end_ts = Timestamp()
        end_ts.FromDatetime(now)

        # Build filter: metric type + optional resource-level filter
        metric_filter = f'metric.type="{metric_type}"'
        if resource_filter:
            metric_filter += f" AND {resource_filter}"

        results = client.list_time_series(
            request=ListTimeSeriesRequest(
                name=project_name,
                filter=metric_filter,
                interval={"start_time": start_ts, "end_time": end_ts},
                view="FULL",
            )
        )

        values = []
        for ts in results:
            for point in ts.points:
                pv = point.value
                if pv.distribution_value and pv.distribution_value.count > 0:
                    v = pv.distribution_value.mean
                elif pv.double_value != 0.0 or not pv.int64_value:
                    v = pv.double_value  # use double_value (0.0 is valid)
                else:
                    v = float(pv.int64_value)
                values.append(v * multiplier)

        if not values:
            return None

        if aggregation == "sum":
            return sum(values)
        elif aggregation == "max":
            return max(values)
        elif aggregation == "min":
            return min(values)
        else:  # mean
            return sum(values) / len(values)

    except Exception as e:
        logger.debug(f"Metric poll failed for {metric_type} in {project}: {e}")
        return None


def _read_env_var(name: str) -> str:
    """Read an env var from os.environ, falling back to ~/.env (single key=value lines).

    9r-review fix: use a context manager so the file descriptor is closed
    deterministically instead of relying on GC.
    """
    import os
    value = os.environ.get(name, "")
    if value:
        return value
    env_path = os.path.expanduser("~/.env")
    if not os.path.exists(env_path):
        return ""
    prefix = f"{name}="
    with open(env_path) as fp:
        for line in fp:
            if line.startswith(prefix):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _get_platform_key() -> str:
    """Read NINE_ROBOTS_PLATFORM_KEY from env or ~/.env."""
    return _read_env_var("NINE_ROBOTS_PLATFORM_KEY")


def _get_platform_inference_url() -> str:
    """REQ-401: Platform inference URL is env-configurable; empty default
    keeps local/dev/CI from hitting prod every 60s. Cloud Run sets the env
    var via the Makefile deploy target."""
    return _read_env_var("PLATFORM_INFERENCE_URL")


def _probe_platform_inference(model: str, timeout_s: int = 30) -> dict:
    """REQ-219: send a tiny test inference to verify a provider end-to-end.

    Status is independent of any other GlassHood traffic — provider liveness
    is measured by an explicit probe through GlassHood → Platform → upstream
    provider, not inferred from whether the model has been recently called.

    REQ-401: the inference URL comes from the PLATFORM_INFERENCE_URL env var.
    When unset (local, dev, CI), short-circuit before any HTTP call so we
    don't silently hammer prod with synthetic traffic.
    """
    try:
        import httpx
        url = _get_platform_inference_url()
        if not url:
            return {"ok": False,
                    "desc": "PLATFORM_INFERENCE_URL not configured"}
        key = _get_platform_key()
        if not key:
            return {"ok": False, "desc": "NINE_ROBOTS_PLATFORM_KEY not configured"}
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "."}],
                "max_tokens": 5,
            },
            timeout=timeout_s,
        )
        if resp.status_code != 200:
            err = ""
            try:
                err = resp.json().get("error", resp.text[:80]) or ""
            except Exception:
                err = resp.text[:80]
            return {"ok": False, "desc": f"HTTP {resp.status_code}: {err[:80]}"}
        data = resp.json()
        text = (data.get("response") or "").strip()
        elapsed = data.get("elapsed_s", 0)
        if not text:
            return {"ok": False, "degraded": True,
                    "desc": f"Empty response from {model} ({elapsed:.1f}s)"}
        return {"ok": True,
                "desc": f"inference OK via {model} ({elapsed:.1f}s, {len(text)} chars)",
                "elapsed_s": elapsed}
    except httpx.TimeoutException:
        return {"ok": False, "desc": f"Timeout after {timeout_s}s"}
    except Exception as e:
        return {"ok": False, "desc": f"Probe error: {str(e)[:80]}"}


_vm_cache = {}  # cache_key -> [{id, label, status, health}]
_vm_cache_times = {}  # cache_key -> last_refresh_time


def _probe_gcp_vm_status(project: str, zone: str, instance_name: str) -> dict:
    """Check if a GCP VM is RUNNING or TERMINATED."""
    try:
        import google.auth
        import google.auth.transport.requests
        import httpx

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        url = (f"https://compute.googleapis.com/compute/v1/projects/{project}"
               f"/zones/{zone}/instances/{instance_name}")
        resp = httpx.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            vm_status = data.get("status", "UNKNOWN")
            machine = data.get("machineType", "").split("/")[-1]
            return {"ok": vm_status == "RUNNING", "status": vm_status, "machine": machine}
        return {"ok": False, "status": "NOT_FOUND", "machine": ""}
    except Exception as e:
        logger.debug(f"VM status probe failed for {instance_name}: {e}")
        return {"ok": False, "status": "ERROR", "machine": ""}


def _discover_mig_vms(project: str, zone: str, instance_group: str) -> list:
    """Discover VMs in a MIG via GCP Compute API."""
    cache_key = f"{project}/{zone}/{instance_group}"
    if time.time() - _vm_cache_times.get(cache_key, 0) < 30 and cache_key in _vm_cache:
        return _vm_cache[cache_key]
    try:
        import google.auth
        import google.auth.transport.requests
        import httpx

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        url = (f"https://compute.googleapis.com/compute/v1/projects/{project}"
               f"/zones/{zone}/instanceGroupManagers/{instance_group}/listManagedInstances")
        resp = httpx.post(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=15)
        if resp.status_code != 200:
            return []
        vms = []
        for inst in resp.json().get("managedInstances", []):
            instance_url = inst.get("instance", "")
            vm_full = instance_url.split("/")[-1] if instance_url else "unknown"
            vm_short = vm_full.split("-")[-1] if "-" in vm_full else vm_full
            vm_name = vm_full
            vm_status = inst.get("instanceStatus", "UNKNOWN")
            health_list = inst.get("instanceHealth", [])
            health = health_list[0].get("detailedHealthState", "UNKNOWN") if health_list else "UNKNOWN"
            # Extract numeric instance ID from the instance URL
            instance_id = str(inst.get("id", ""))
            vms.append({
                "id": f"vm-{vm_name}",
                "label": f"VM: {vm_short}",
                "status": "healthy" if health == "HEALTHY" else ("degraded" if vm_status == "RUNNING" else "error"),
                "vm_status": vm_status,
                "health_state": health,
                "instance_id": instance_id,
            })
        _vm_cache[cache_key] = vms
        _vm_cache_times[cache_key] = time.time()
        logger.info(f"MIG discovery [{instance_group}]: {len(vms)} VMs found")
        return vms
    except Exception as e:
        logger.warning(f"MIG VM discovery failed [{instance_group}]: {e}")
        return []


def _probe_http(url: str, timeout_s: int = 10) -> tuple:
    """Probe an HTTP endpoint. Returns (ok, latency_ms)."""
    try:
        import httpx
        resp = httpx.get(url, timeout=timeout_s)
        latency_ms = round(resp.elapsed.total_seconds() * 1000)
        return resp.status_code == 200, latency_ms
    except Exception as e:
        logger.debug(f"HTTP probe failed for {url}: {e}")
        return False, None


def _probe_gcp_secret(project: str, secret_name: str) -> bool:
    """Probe Secret Manager via REST API (metadata only, no payload)."""
    try:
        import google.auth
        import google.auth.transport.requests
        import httpx

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        url = f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{secret_name}"
        resp = httpx.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f"SM probe failed for {secret_name}: {e}")
        return False


def _poll_node(node_config: dict) -> dict:
    """Poll all metrics for a single node based on its YAML monitoring config."""
    node_id = node_config["id"]
    monitoring = node_config.get("monitoring", {})
    metrics_config = monitoring.get("metrics", [])
    probe_config = monitoring.get("probe", {})

    # Probe check (synthetic): call an endpoint to verify accessibility
    if probe_config and not metrics_config:
        probe_type = probe_config.get("type", "")
        if probe_type == "http":
            url = probe_config.get("url", "")
            ok, latency_ms = _probe_http(url, probe_config.get("timeout_s", 10))
            desc = f"HTTP probe → {url} — {'200 OK' if ok else 'FAILED'}"
            if latency_ms is not None:
                desc += f" ({latency_ms}ms)"
            return {
                "node_id": node_id,
                "status": "healthy" if ok else "error",
                "metrics": {"reachable": 1 if ok else 0, "probe_latency_ms": latency_ms},
                "check_description": desc,
            }
        if probe_type == "gcp_secret":
            sname = probe_config.get("secret_name", "")
            ok = _probe_gcp_secret(probe_config.get("project", ""), sname)
            desc = f"Secret Manager API — {sname} {'accessible' if ok else 'UNREACHABLE'}"
            return {
                "node_id": node_id,
                "status": "healthy" if ok else "error",
                "metrics": {"accessible": 1 if ok else 0},
                "check_description": desc,
            }
        if probe_type == "gcp_vm_status":
            expected_offline = node_config.get("expected_offline", False)
            result = _probe_gcp_vm_status(
                probe_config.get("project", ""),
                probe_config.get("zone", ""),
                probe_config.get("instance_name", probe_config.get("resource_name", "")),
            )
            vm_status = result["status"]
            # Expected-offline nodes (on-demand GPU): gray when not running, green when running
            if result["ok"]:
                status = "healthy"
            elif expected_offline:
                status = "disabled"  # gray — declared capability, not yet provisioned
            elif vm_status in ("TERMINATED", "STOPPED", "SUSPENDED", "STAGING"):
                status = "disabled"  # gray — offline but exists
            else:
                status = "error"
            desc = f"VM {probe_config.get('instance_name','')} — {vm_status}"
            if result["machine"]:
                desc += f" ({result['machine']})"
            return {
                "node_id": node_id,
                "status": status,
                "metrics": {"vm_status": vm_status, "machine_type": result["machine"]},
                "check_description": desc,
            }
        if probe_type == "platform_inference":
            # REQ-219: provider liveness via explicit test inference. Independent of
            # application traffic — status reflects what the probe just observed.
            model = probe_config.get("model", "")
            timeout_s = probe_config.get("timeout_s", 30)
            result = _probe_platform_inference(model, timeout_s)
            status = "healthy" if result["ok"] else ("degraded" if result.get("degraded") else "error")
            return {
                "node_id": node_id,
                "status": status,
                "metrics": {
                    "reachable": 1 if result["ok"] else 0,
                    "probe_latency_s": result.get("elapsed_s"),
                    "model": model,
                },
                "check_description": result.get("desc", ""),
            }

    if not metrics_config:
        # Nodes with logs-only monitoring are still monitored
        logs_config = monitoring.get("logs", [])
        if logs_config:
            return {"node_id": node_id, "status": "healthy", "metrics": {},
                    "check_description": "Logs configured — monitoring via log analysis"}
        return {"node_id": node_id, "status": "not monitored", "metrics": {}}

    node_metrics = {}
    has_data = False
    worst_status = "unknown"  # default when no data; only "healthy" if real data
    status_priority = {"healthy": 0, "unknown": 1, "degraded": 2, "error": 3}

    for mc in metrics_config:
        metric_type = mc.get("metric_type", "")
        project = mc.get("project", "")
        resource_filter = mc.get("filter", "")
        aggregation = mc.get("aggregation", "mean")
        multiplier = mc.get("multiplier", 1.0)
        name = mc.get("name", metric_type.split("/")[-1])
        thresholds = mc.get("thresholds", {})

        # Resolve mig_scoped filter — only include VMs from THIS node's MIG
        if resource_filter == "mig_scoped":
            # Build cache key from node's discover config
            discover = monitoring.get("discover", {})
            cache_key = f"{discover.get('project','')}/{discover.get('zone','')}/{discover.get('instance_group','')}"
            with _lock:
                mig_ids = []
                for vm in _vm_cache.get(cache_key, []):
                    iid = vm.get("instance_id", "")
                    if iid:
                        mig_ids.append(iid)
            if not mig_ids:
                # VMs discovered but no instance IDs yet — check if VMs exist in cache
                with _lock:
                    cached_vms = _vm_cache.get(cache_key, [])
                if cached_vms:
                    # VMs are discovered and running — treat MIG as healthy
                    worst_status = "healthy"
                    has_data = True
                node_metrics[name] = None
                continue
            resource_filter = "(" + " OR ".join(
                f'resource.labels.instance_id="{iid}"' for iid in mig_ids) + ")"

        value = _poll_metric(project, metric_type, resource_filter,
                             aggregation, multiplier)

        if value is not None:
            node_metrics[name] = round(value, 1)
            status = _evaluate_status(value, thresholds)
            if status is not None:  # None = informational metric, no thresholds
                if not has_data:
                    worst_status = status
                    has_data = True
                elif status_priority.get(status, 0) > status_priority.get(worst_status, 0):
                    worst_status = status
        else:
            node_metrics[name] = None

    # Build human-readable check description
    checks = []
    for mc in metrics_config:
        name = mc.get("name", "")
        val = node_metrics.get(name)
        unit = mc.get("unit", "")
        if unit == "percent":
            unit = "%"
        elif unit == "count":
            unit = ""
        elif unit == "ms":
            unit = "ms"
        thresholds = mc.get("thresholds", {})
        if val is not None:
            status = _evaluate_status(val, thresholds)
            status_label = status if status else "ok"
            checks.append(f"{name.replace('_', ' ')}: {val}{unit} — {status_label}")
        else:
            checks.append(f"{name.replace('_', ' ')}: no data")

    # MIG with discovered healthy VMs should be healthy even if metrics query returns no data
    if worst_status == "unknown" and monitoring.get("discover", {}).get("type") == "gcp_mig":
        discover = monitoring["discover"]
        cache_key = f"{discover.get('project','')}/{discover.get('zone','')}/{discover.get('instance_group','')}"
        with _lock:
            cached_vms = _vm_cache.get(cache_key, [])
        if cached_vms and any(v.get("status") == "healthy" for v in cached_vms):
            worst_status = "healthy"

    return {
        "node_id": node_id,
        "status": worst_status,
        "metrics": node_metrics,
        "check_description": " | ".join(checks) if checks else None,
    }


def poll_all_manifest_nodes(manifests_dir: str = "config/manifests") -> None:
    """Poll metrics for all manifest nodes that have monitoring config."""
    manifests_path = Path(manifests_dir)
    if not manifests_path.exists():
        return

    nodes_to_poll = []
    discover_configs = []  # (parent_node_id, discover_config)
    children_templates = {}  # parent_node_id → children_template list
    for f in manifests_path.glob("*.yaml"):
        if f.name.startswith("_"):
            continue
        try:
            with open(f) as fp:
                data = yaml.safe_load(fp)
            if not data:
                continue
            for env in data.get("environments", []):
                for node in env.get("nodes", []):
                    mon = node.get("monitoring", {})
                    if mon.get("metrics") or mon.get("probe") or mon.get("logs"):
                        nodes_to_poll.append(node)
                    if mon.get("discover"):
                        discover_configs.append((node["id"], mon["discover"]))
                    if node.get("children_template"):
                        children_templates[node["id"]] = node["children_template"]
        except Exception as e:
            logger.warning(f"Failed to read manifest {f}: {e}")

    if not nodes_to_poll:
        return

    # Discover MIG VMs FIRST so mig_scoped filter has cached instance IDs
    for parent_id, disc in discover_configs:
        if disc.get("type") == "gcp_mig":
            _discover_mig_vms(
                disc.get("project", ""), disc.get("zone", ""), disc.get("instance_group", "")
            )

    with ThreadPoolExecutor(max_workers=min(len(nodes_to_poll), 5)) as executor:
        results = list(executor.map(_poll_node, nodes_to_poll))

    now = time.time()
    with _lock:
        for result in results:
            _metrics_cache[result["node_id"]] = {
                "status": result["status"],
                "metrics": result["metrics"],
                "check_description": result.get("check_description"),
                "last_poll": now,
                "poll_interval_s": _POLL_INTERVAL,
            }

    # Store discovered VM data in cache (for topology injection)
    # Remove stale VMs first — MIG may have scaled down since last poll
    for parent_id, disc in discover_configs:
        if disc.get("type") == "gcp_mig":
            vms = _discover_mig_vms(
                disc.get("project", ""), disc.get("zone", ""), disc.get("instance_group", "")
            )
            current_vm_ids = {vm["id"] for vm in vms}
            with _lock:
                # Remove old VMs for this parent that no longer exist
                stale = [nid for nid, d in _metrics_cache.items()
                         if d.get("_parent") == parent_id and nid not in current_vm_ids]
                for nid in stale:
                    del _metrics_cache[nid]
                for vm in vms:
                    _metrics_cache[vm["id"]] = {
                        "status": vm["status"],
                        "metrics": {"vm_status": vm["vm_status"], "health": vm["health_state"]},
                        "check_description": f"VM {vm['label']} — {vm['vm_status']} / {vm['health_state']}",
                        "last_poll": now,
                        "poll_interval_s": _POLL_INTERVAL,
                        "_parent": parent_id,
                        "_label": vm["label"],
                        "_type": "vm",
                    }

    # Store children templates for topology assembly
    with _lock:
        _children_templates_cache.update(children_templates)

    if children_templates:
        logger.info(f"Children templates cached: {list(children_templates.keys())}")
    logger.info(f"Manifest metrics polled: {len(results)} nodes, {sum(len(v) for v in _vm_cache.values())} discovered VMs")


# Children template cache
_children_templates_cache = {}


def get_children_template(parent_id: str) -> list:
    """Get children_template for a parent node (e.g., MIG with nested layers)."""
    with _lock:
        return _children_templates_cache.get(parent_id, [])


def resolve_children_template(template: list, vm_name: str, vm_id: str) -> list:
    """Resolve a children_template for a specific discovered VM.

    Replaces {vm_name} and {vm_id} in id_suffix, labels, and log filters.
    """
    resolved = []
    for tmpl in template:
        child = copy.deepcopy(tmpl)
        suffix = child.pop("id_suffix", "")
        child["id"] = f"vm-{vm_name}{suffix}"
        # Resolve template variables in label
        child["label"] = child.get("label", "").replace("{vm_name}", vm_name).replace("{vm_id}", vm_id)
        # Resolve in monitoring log filters
        mon = child.get("monitoring", {})
        if mon.get("logs"):
            for log_cfg in mon["logs"]:
                if "filter" in log_cfg:
                    log_cfg["filter"] = log_cfg["filter"].replace("{vm_name}", vm_name).replace("{vm_id}", vm_id)
        # Recurse for nested children
        if "children" in child:
            child["children"] = resolve_children_template(child["children"], vm_name, vm_id)
        resolved.append(child)
    return resolved


def get_discovered_children(parent_id: str) -> list:
    """Get dynamically discovered child nodes for a parent."""
    with _lock:
        return [
            {"id": nid, **data}
            for nid, data in _metrics_cache.items()
            if data.get("_parent") == parent_id
        ]


def get_node_status(node_id: str):
    """Get cached metrics for a manifest node."""
    with _lock:
        return _metrics_cache.get(node_id)


def get_all_statuses() -> dict:
    """Get all cached manifest node statuses."""
    with _lock:
        return dict(_metrics_cache)


def metrics_loop(interval: int = _POLL_INTERVAL):
    """Background polling loop for manifest metrics."""
    stop = threading.Event()
    while True:
        try:
            poll_all_manifest_nodes()
        except Exception as e:
            logger.error(f"Manifest metrics poll failed: {e}")
        if stop.wait(interval):
            break
