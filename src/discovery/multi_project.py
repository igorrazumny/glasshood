# File: src/discovery/multi_project.py
# Purpose: Orchestrate asset discovery across multiple GCP projects

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.discovery.gcp_assets import build_graph
from src.discovery.org_projects import get_cached_projects

logger = logging.getLogger(__name__)

_cached: dict = {}  # {project_id: {"nodes": [], "edges": [], "timestamp": float}}
_lock = threading.Lock()


def _discover_project(project_info: dict) -> tuple:
    """Discover assets for a single project. Returns (project_id, result)."""
    project_id = project_info["project_id"]
    product = project_info.get("product", "")
    env = project_info.get("environment", "")
    try:
        result = build_graph(project_id=project_id, project=product, env=env)
        logger.info(f"Multi-project discovery: {project_id} → "
                    f"{len(result['nodes'])} nodes, {len(result['edges'])} edges")
        return project_id, result
    except Exception as e:
        logger.error(f"Discovery failed for {project_id}: {e}")
        return project_id, {"nodes": [], "edges": []}


def discover_all(project_infos: list, max_workers: int = 4) -> dict:
    """Discover assets across all projects in parallel.

    Args:
        project_infos: list of {"project_id", "product", "environment"} dicts
        max_workers: ThreadPoolExecutor concurrency

    Returns:
        {project_id: {"nodes": [...], "edges": [...], "timestamp": float}}
    """
    global _cached
    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_discover_project, p): p for p in project_infos}
        try:
            for future in as_completed(futures, timeout=120):
                try:
                    project_id, result = future.result()
                    results[project_id] = {
                        "nodes": result["nodes"],
                        "edges": result["edges"],
                        "timestamp": time.time(),
                    }
                except Exception as e:
                    info = futures[future]
                    logger.error(f"Discovery thread failed for {info['project_id']}: {e}")
        except TimeoutError:
            logger.warning(f"Discovery timed out — {len(results)}/{len(project_infos)} "
                           f"projects completed")

    with _lock:
        _cached.update(results)

    total_nodes = sum(len(r["nodes"]) for r in results.values())
    logger.info(f"Multi-project discovery complete: {len(results)} projects, "
                f"{total_nodes} total nodes")
    return results


def get_project_topology(project_id: str) -> dict:
    """Return cached topology for one project."""
    with _lock:
        entry = _cached.get(project_id)
        if entry:
            return {"nodes": list(entry["nodes"]), "edges": list(entry["edges"])}
        return {"nodes": [], "edges": []}


def get_all_topologies() -> dict:
    """Return all cached project topologies."""
    with _lock:
        return {pid: {"nodes": list(e["nodes"]), "edges": list(e["edges"])}
                for pid, e in _cached.items()}


def get_combined_topology() -> dict:
    """Return merged topology across all projects ('See All' view)."""
    with _lock:
        all_nodes = []
        all_edges = []
        for entry in _cached.values():
            all_nodes.extend(entry["nodes"])
            all_edges.extend(entry["edges"])
        return {"nodes": all_nodes, "edges": all_edges}


def get_project_count() -> int:
    """Return number of cached projects."""
    with _lock:
        return len(_cached)
