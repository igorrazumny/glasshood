# File: src/discovery/org_projects.py
# Purpose: GCP org-level project discovery via Cloud Resource Manager API

import fnmatch
import logging
import threading
import time
from pathlib import Path

import yaml

from src.config.settings import GCP_ORG_ID, GCP_PROJECT_ID, GCP_PROJECT_DISPLAY_NAME

logger = logging.getLogger(__name__)

_cached_projects: list = []
_lock = threading.Lock()
_last_scan: float = 0


def _load_config(config_path: str) -> dict:
    """Load org_discovery.yaml config."""
    p = Path(config_path)
    if not p.exists():
        logger.warning(f"Org discovery config not found: {config_path}")
        return {}
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        return data.get("org_discovery", {})
    except Exception as e:
        logger.error(f"Failed to load org discovery config: {e}")
        return {}


def _matches_patterns(name: str, patterns: list) -> bool:
    """Check if name matches any of the glob patterns."""
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def _list_org_projects(org_id: str) -> list:
    """List all GCP projects under the org using Resource Manager API."""
    try:
        from google.cloud import resourcemanager_v3
        client = resourcemanager_v3.ProjectsClient()
        # Empty query returns all projects the SA has access to (including nested in folders).
        # parent:organizations/ only returns direct children, missing folder-nested projects.
        request = resourcemanager_v3.SearchProjectsRequest()
        projects = []
        for project in client.search_projects(request=request):
            projects.append({
                "project_id": project.project_id,
                "display_name": project.display_name,
                "state": project.state.name if project.state else "UNKNOWN",
                "labels": dict(project.labels) if project.labels else {},
                "parent": project.parent,
            })
        logger.info(f"Org discovery: found {len(projects)} projects under org {org_id}")
        return projects
    except Exception as e:
        logger.error(f"Org project discovery failed: {e}")
        return []


_KNOWN_ENVS = {"prod", "val", "dev", "staging", "test", "qa", "uat"}


def classify_project(display_name: str) -> dict:
    """Classify a GCP project into product/environment from its display name.

    Display names follow the pattern "{Product} {Environment}", e.g.:
      "ColdVault Prod" -> product=coldvault, env=prod
      "9Robots Platform Val" -> product=platform, env=val
      "ProofBench Prod" -> product=proofbench, env=prod
      "9Robots Website" -> product=website, env="" (no known env suffix)

    Only recognized environment names (prod/val/dev/staging/test/qa/uat) are
    treated as environments. Otherwise the full name is the product.
    Returns {"product": str, "environment": str}.
    """
    parts = display_name.strip().split()
    if len(parts) >= 2:
        last = parts[-1].lower()
        if last in _KNOWN_ENVS:
            product = parts[-2].lower()
            return {"product": product, "environment": last}
        # Last word is not a known env — use last word as product, no environment
        product = parts[-1].lower()
        return {"product": product, "environment": ""}
    elif len(parts) == 1:
        return {"product": parts[0].lower(), "environment": ""}
    return {"product": "", "environment": ""}


def discover_projects(config_path: str) -> list:
    """Discover and classify all GCP projects under the org.

    Falls back to single configured project if org-level discovery fails.
    Returns list of {"project_id", "display_name", "product", "environment", "state"}.
    """
    global _cached_projects, _last_scan
    config = _load_config(config_path)
    org_id = config.get("org_id", GCP_ORG_ID)
    include = config.get("include_patterns", ["*"])
    exclude = config.get("exclude_patterns", [])

    raw_projects = _list_org_projects(org_id)

    # Fallback: if org discovery fails, use single configured project
    if not raw_projects:
        logger.warning("Org discovery returned empty — falling back to single project")
        display_name = GCP_PROJECT_DISPLAY_NAME or GCP_PROJECT_ID
        classification = classify_project(display_name)
        fallback = [{
            "project_id": GCP_PROJECT_ID,
            "display_name": display_name,
            "product": classification.get("product", ""),
            "environment": classification.get("environment", ""),
            "state": "ACTIVE",
        }]
        with _lock:
            _cached_projects = fallback
            _last_scan = time.time()
        return fallback

    # Filter by include/exclude patterns
    filtered = []
    for proj in raw_projects:
        pid = proj["project_id"]
        if proj["state"] != "ACTIVE":
            continue
        if not _matches_patterns(pid, include):
            continue
        if _matches_patterns(pid, exclude):
            continue
        classification = classify_project(proj["display_name"] or pid)
        filtered.append({
            "project_id": pid,
            "display_name": proj["display_name"],
            "product": classification.get("product", ""),
            "environment": classification.get("environment", ""),
            "state": proj["state"],
        })

    # Sort: nr-* canonical IDs first so deduplication keeps them over legacy IDs
    filtered.sort(key=lambda p: (0 if p["project_id"].startswith("nr-") else 1, p["project_id"]))

    logger.info(f"Org discovery: {len(filtered)} projects after filtering "
                f"(from {len(raw_projects)} total)")

    with _lock:
        _cached_projects = filtered
        _last_scan = time.time()
    return filtered


def get_cached_projects() -> list:
    """Return last discovered project list."""
    with _lock:
        return list(_cached_projects)


def get_project_ids() -> list:
    """Return list of active project IDs."""
    with _lock:
        return [p["project_id"] for p in _cached_projects]
