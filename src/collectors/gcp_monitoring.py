# File: src/collectors/gcp_monitoring.py
# Purpose: Poll GCP Cloud Monitoring for LB latency and VM CPU

import asyncio
import time
import logging
from datetime import datetime, timezone, timedelta

from src.config.settings import GCP_PROJECT_ID, GCP_POLL_INTERVAL

logger = logging.getLogger(__name__)

_stats: dict = {
    "lb_latency_ms": None,
    "lb_request_count_1h": 0,
    "vm_cpu_percent": None,
    "last_poll": 0,
}


async def poll_once():
    """Query Cloud Monitoring for LB and VM metrics."""
    global _stats
    try:
        from google.cloud.monitoring_v3 import MetricServiceClient, ListTimeSeriesRequest
        from google.protobuf.timestamp_pb2 import Timestamp

        loop = asyncio.get_running_loop()

        def _query():
            client = MetricServiceClient()
            project_name = f"projects/{GCP_PROJECT_ID}"
            now = datetime.now(timezone.utc)
            start = now - timedelta(hours=1)

            start_ts = Timestamp()
            start_ts.FromDatetime(start)
            end_ts = Timestamp()
            end_ts.FromDatetime(now)

            interval = {"start_time": start_ts, "end_time": end_ts}

            stats = {}

            # LB backend latency
            try:
                results = client.list_time_series(
                    request=ListTimeSeriesRequest(
                        name=project_name,
                        filter='metric.type="loadbalancing.googleapis.com/https/backend_latencies"',
                        interval=interval,
                        view="FULL",
                    )
                )
                latencies = []
                for ts in results:
                    for point in ts.points:
                        if point.value.distribution_value.count > 0:
                            latencies.append(point.value.distribution_value.mean)
                if latencies:
                    stats["lb_latency_ms"] = round(sum(latencies) / len(latencies), 1)
            except Exception as e:
                logger.debug(f"LB latency query failed: {e}")

            # LB request count
            try:
                results = client.list_time_series(
                    request=ListTimeSeriesRequest(
                        name=project_name,
                        filter='metric.type="loadbalancing.googleapis.com/https/request_count"',
                        interval=interval,
                        view="FULL",
                    )
                )
                total = 0
                for ts in results:
                    for point in ts.points:
                        total += point.value.int64_value
                stats["lb_request_count_1h"] = total
            except Exception as e:
                logger.debug(f"LB request count query failed: {e}")

            # VM CPU utilization
            try:
                results = client.list_time_series(
                    request=ListTimeSeriesRequest(
                        name=project_name,
                        filter='metric.type="compute.googleapis.com/instance/cpu/utilization"',
                        interval=interval,
                        view="FULL",
                    )
                )
                cpus = []
                for ts in results:
                    for point in ts.points:
                        cpus.append(point.value.double_value * 100)
                if cpus:
                    stats["vm_cpu_percent"] = round(sum(cpus) / len(cpus), 1)
            except Exception as e:
                logger.debug(f"VM CPU query failed: {e}")

            return stats

        result = await loop.run_in_executor(None, _query)
        _stats.update(result)
        _stats["last_poll"] = time.time()

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
