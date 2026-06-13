# File: src/api/routes/manifests.py
# Purpose: GET /api/manifests — topology manifest files for config-driven rendering

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Request

from src.api.routes.auth import verify_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["manifests"])

MANIFEST_DIR = Path("config/manifests")


def _load_manifests() -> list:
    """Load all YAML manifests from config/manifests/.

    Supports both legacy per-env files (product+environment+groups at top level)
    and multi-env files (environments[] list). Multi-env files are flattened
    into one manifest per environment for the frontend.
    """
    manifests = []
    if not MANIFEST_DIR.exists():
        return manifests
    for f in sorted(MANIFEST_DIR.glob("*.yaml")):
        try:
            with open(f) as fp:
                data = yaml.safe_load(fp)
            if not data or not isinstance(data, dict):
                continue
            # Multi-env format: flatten environments[] into separate manifests
            if "environments" in data and isinstance(data["environments"], list):
                for env in data["environments"]:
                    manifest = {
                        "schema_version": data.get("schema_version", 1),
                        "company": data.get("company", ""),
                        "solution": data.get("solution", ""),
                        "product": data.get("product", ""),
                        "project_id": data.get("project_id", ""),
                        "region": data.get("region", ""),
                        "environment": env.get("environment", ""),
                        "display_name": env.get("display_name", ""),
                        "order": env.get("order", 0),
                        "groups": env.get("groups", []),
                        "nodes": env.get("nodes", []),
                        "edges": env.get("edges", []),
                    }
                    manifests.append(manifest)
            else:
                # Legacy per-env format: use as-is
                manifests.append(data)
        except Exception as e:
            logger.warning(f"Failed to load manifest {f}: {e}")
    return manifests


@router.get("/api/manifests")
def get_manifests(request: Request):
    """Return all compiled topology manifests. Requires auth token."""
    verify_token(request)
    from src.manifest_compiler import compile_all
    return compile_all(_load_manifests())


@router.post("/api/manifests/verify")
def verify_manifests(request: Request):
    """Verify all manifests — produce verification report (REQ-603).

    Probes endpoints, checks logs, returns report per solution.
    Report is informational — user decides whether to proceed.
    """
    verify_token(request)
    from src.manifest_compiler import compile_all
    results = compile_all(_load_manifests(), verify=True)
    return {
        "manifests": results,
        "reports": [
            {"product": r.get("product"), "solution": r.get("solution"),
             "environment": r.get("environment"),
             "summary": r.get("_report_summary", {}),
             "nodes": r.get("_verification_report", [])}
            for r in results if r.get("_verification_report")
        ],
    }


@router.post("/api/manifests/reset-verification")
def reset_manifest_verification(request: Request, product: str = None,
                                solution: str = None, environment: str = None):
    """Reset verification cache — forces re-verification on next /verify call.

    Optional params to scope the reset:
      - product + solution + environment: reset one specific solution
      - product only: reset all environments for that product
      - no params: reset ALL solutions (global clear)
    """
    verify_token(request)
    from src.manifest_compiler import reset_verification
    reset_verification(product=product, solution=solution, environment=environment)
    scope = f"{product}/{solution}/{environment}" if product else "all"
    return {"status": "reset", "scope": scope}
