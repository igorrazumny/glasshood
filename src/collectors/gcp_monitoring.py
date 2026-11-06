# File: src/collectors/gcp_monitoring.py
# Purpose: Poll GCP Cloud Monitoring for LB latency and VM CPU

import asyncio
import time
import logging
from datetime import datetime, timezone, timedelta

from src.collectors import alarm_sources
from src.config.settings import GCP_POLL_INTERVAL

logger = logging.getLogger(__name__)

# Reads only the load balancer and VMs the manifest's alarm_sources select, and records
# the part each metric belongs to (REQ-GHA-027). A metric stays None while it was not
# read, so an alarm on it is "not checked".
_stats: dict = {
    "lb_latency_ms": None,
    "lb_request_count_1h": None,
    "vm_cpu_percent": None,
    "parts": {},
    "last_poll": 0,
    "read_at": None,  # time of the last successful reading (failed polls leave it unchanged)
}

_LB_METRICS = ("lb_latency_ms", "lb_request_count_1h")


def _bucket_bounds(kind: str, params: dict, n: int) -> list[tuple]:
    """(lower, upper) of each of n buckets of a Cloud Monitoring distribution: an
    underflow bucket, the finite buckets, then an overflow bucket."""
    inf = float("inf")
    if kind == "explicit_buckets":
        b = list(params["bounds"])
        edges = [-inf] + b + [inf]
    else:
        finite = int(params["num_finite_buckets"])
        if kind == "linear_buckets":
            edges = [params["offset"] + params["width"] * i for i in range(finite + 1)]
        else:  # exponential_buckets
            edges = [params["scale"] * params["growth_factor"] ** i for i in range(finite + 1)]
        edges = [-inf] + edges + [inf]
    return [(edges[i], edges[i + 1]) for i in range(min(n, len(edges) - 1))]


def _options(bucket_options) -> tuple:
    kind = type(bucket_options).pb(bucket_options).WhichOneof("options")
    o = getattr(bucket_options, kind)
    if kind == "explicit_buckets":
        return kind, {"bounds": list(o.bounds)}
    if kind == "linear_buckets":
        return kind, {"num_finite_buckets": o.num_finite_buckets, "width": o.width, "offset": o.offset}
    return kind, {"num_finite_buckets": o.num_finite_buckets, "growth_factor": o.growth_factor,
                  "scale": o.scale}


def median_from_buckets(counts: dict) -> float | None:
    """Median of a merged distribution {(lower, upper): count}, interpolated inside the
    bucket that holds the middle request (REQ-GHA-028 clause 3: typical response time,
    so one long chat answer does not move it)."""
    total = sum(counts.values())
    if total <= 0:
        return None
    target, seen = total / 2, 0
    for (lower, upper), c in sorted(counts.items()):
        if c <= 0:
            continue
        if seen + c >= target:
            lo = max(lower, 0.0)
            if upper == float("inf"):
                return lo
            return lo + (upper - lo) * (target - seen) / c
        seen += c
    return None


def _series(client, request_cls, project: str, metric_type: str, scope: str, interval):
    return client.list_time_series(request=request_cls(
        name=f"projects/{project}",
        filter=f'metric.type="{metric_type}" AND ({scope})',
        interval=interval,
        view="FULL",
    ))


async def poll_once():
    """Query Cloud Monitoring for the monitored system's LB and VM metrics."""
    global _stats
    sources = alarm_sources.load()
    lb, cpu = sources.get("load_balancer"), sources.get("cpu")
    if not lb and not cpu:
        _stats = {"lb_latency_ms": None, "lb_request_count_1h": None, "vm_cpu_percent": None,
                  "parts": {}, "last_poll": time.time(), "read_at": None}
        return
    try:
        from google.cloud.monitoring_v3 import MetricServiceClient, ListTimeSeriesRequest
        from google.protobuf.timestamp_pb2 import Timestamp

        loop = asyncio.get_running_loop()

        def _query():
            client = MetricServiceClient()
            now = datetime.now(timezone.utc)
            start = now - timedelta(hours=1)

            start_ts = Timestamp()
            start_ts.FromDatetime(start)
            end_ts = Timestamp()
            end_ts.FromDatetime(now)

            interval = {"start_time": start_ts, "end_time": end_ts}

            stats = {"lb_latency_ms": None, "lb_request_count_1h": None, "vm_cpu_percent": None,
                     "parts": {}}

            if lb:
                stats["parts"].update({m: lb["part"] for m in _LB_METRICS})
                # LB backend latency: the median request of the hour, from the
                # per-minute distributions merged bucket by bucket (REQ-GHA-028)
                try:
                    merged: dict = {}
                    for ts in _series(client, ListTimeSeriesRequest, lb["project"],
                                      "loadbalancing.googleapis.com/https/backend_latencies",
                                      lb["filter"], interval):
                        for point in ts.points:
                            dist = point.value.distribution_value
                            if dist.count <= 0 or not dist.bucket_counts:
                                continue
                            kind, params = _options(dist.bucket_options)
                            bounds = _bucket_bounds(kind, params, len(dist.bucket_counts))
                            for b, c in zip(bounds, dist.bucket_counts):
                                merged[b] = merged.get(b, 0) + int(c)
                    median = median_from_buckets(merged)
                    if median is not None:
                        stats["lb_latency_ms"] = round(median, 1)
                except Exception as e:
                    logger.debug(f"LB latency query failed: {e}")

                # LB request count
                try:
                    total = 0
                    for ts in _series(client, ListTimeSeriesRequest, lb["project"],
                                      "loadbalancing.googleapis.com/https/request_count",
                                      lb["filter"], interval):
                        for point in ts.points:
                            total += point.value.int64_value
                    stats["lb_request_count_1h"] = total
                except Exception as e:
                    logger.debug(f"LB request count query failed: {e}")

            if cpu:
                stats["parts"]["vm_cpu_percent"] = cpu["part"]
                # VM CPU utilization
                try:
                    cpus = []
                    for ts in _series(client, ListTimeSeriesRequest, cpu["project"],
                                      "compute.googleapis.com/instance/cpu/utilization",
                                      cpu["filter"], interval):
                        for point in ts.points:
                            cpus.append(point.value.double_value * 100)
                    if cpus:
                        stats["vm_cpu_percent"] = round(sum(cpus) / len(cpus), 1)
                except Exception as e:
                    logger.debug(f"VM CPU query failed: {e}")

            return stats

        result = await loop.run_in_executor(None, _query)
        _stats.update(result)
        _stats["last_poll"] = _stats["read_at"] = time.time()
        # Judge this reading now, not when someone opens the page (REQ-GHA-026)
        from src.security.anomaly_detector import judge_fresh_readings
        judge_fresh_readings()

    except Exception as e:
        logger.warning(f"GCP Monitoring poll failed: {e}")
        _stats["last_poll"] = time.time()


async def poll_loop():
    """Background polling loop."""
    while True:
        try:
            await poll_once()
        except Exception as e:
            logger.error(f"GCP Monitoring poll loop error: {e}")
        await asyncio.sleep(GCP_POLL_INTERVAL)


def get_stats() -> dict:
    return _stats
