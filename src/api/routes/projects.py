# File: src/api/routes/projects.py
# Purpose: Multi-project API endpoints

from fastapi import APIRouter, Request

from src.api.routes.auth import verify_token
from src.config.settings import GCP_PROJECT_ID, GCP_PROJECT_DISPLAY_NAME
from src.discovery.org_projects import get_cached_projects
from src.discovery.multi_project import (
    get_project_topology, get_all_topologies, get_combined_topology,
    get_project_count,
)

router = APIRouter(tags=["projects"])


@router.get("/api/projects")
def list_projects(request: Request):
    """Return all discovered GCP projects with classification."""
    verify_token(request)
    projects = get_cached_projects()
    if not projects:
        # Single-project fallback — classify from display name
        from src.discovery.org_projects import classify_project
        display_name = GCP_PROJECT_DISPLAY_NAME or GCP_PROJECT_ID
        classification = classify_project(display_name)
        return [{"project_id": GCP_PROJECT_ID,
                 "display_name": display_name,
                 "product": classification["product"],
                 "environment": classification["environment"],
                 "state": "ACTIVE"}]
    return projects


@router.get("/api/projects/{project_id}/topology")
def get_project_topo(project_id: str, request: Request):
    """Return topology for a specific project."""
    verify_token(request)
    topo = get_project_topology(project_id)
    return {
        "project_id": project_id,
        "nodes": [n.to_dict() if hasattr(n, "to_dict") else n for n in topo["nodes"]],
        "edges": [e.to_dict() if hasattr(e, "to_dict") else e for e in topo["edges"]],
    }


@router.get("/api/topology/all")
def get_all_topology(request: Request):
    """Return combined topology across all projects ('See All' view)."""
    verify_token(request)
    combined = get_combined_topology()
    return {
        "nodes": [n.to_dict() if hasattr(n, "to_dict") else n
                  for n in combined["nodes"]],
        "edges": [e.to_dict() if hasattr(e, "to_dict") else e
                  for e in combined["edges"]],
        "project_count": get_project_count(),
    }


@router.post("/api/discovery/trigger")
def trigger_discovery(request: Request, project_id: str = None):
    """Manually trigger a discovery scan."""
    verify_token(request)
    from src.discovery.scheduler import get_scheduler
    scheduler = get_scheduler()
    if scheduler:
        scheduler.trigger_scan(project_id=project_id)
        return {"status": "triggered", "project_id": project_id or "all"}
    return {"status": "scheduler_not_running"}
