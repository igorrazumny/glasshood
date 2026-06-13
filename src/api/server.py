# File: src/api/server.py
# Purpose: FastAPI app entry point — lifecycle, middleware, static files

import asyncio
import logging
import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.api.routes.auth import router as auth_router
from src.api.routes.topology import router as topology_router, get_topology_data
from src.api.routes.analysis import router as analysis_router
from src.api.routes.demo import router as demo_router
from src.api.routes.logs import router as logs_router
from src.api.routes.report import router as report_router
from src.api.routes.alerts import router as alerts_router
from src.api.routes.audit import router as audit_router
from src.api.routes.security import router as security_router
from src.api.routes.anomalies import router as anomalies_router
from src.api.routes.compliance import router as compliance_router
from src.api.routes.integrations import router as integrations_router
from src.api.routes.ingest import router as ingest_router
from src.api.routes.storage import router as storage_router
from src.api.routes.customers import router as customers_router
from src.api.routes.projects import router as projects_router
from src.api.routes.manifests import router as manifests_router
from src.collectors import coldvault, gcp_logging, gcp_monitoring, gcs_bucket, manifest_metrics
from src.security import cve_scanner
from src.analysis.coldvault_client import analysis_loop
from src.integrations.sync import sync_loop
from src.config.settings import (
    DISCOVERY_ENABLED, DISCOVERY_INTERVAL, SECURITY_SCAN_ENABLED, SNOW_ENABLED,
    STORAGE_ENABLED, RETENTION_ENABLED, STORAGE_FLUSH_INTERVAL,
    ORG_DISCOVERY_ENABLED,
)
from src.discovery.gcp_assets import discovery_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GlassHood")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth_router)
app.include_router(topology_router)
app.include_router(analysis_router)
app.include_router(demo_router)
app.include_router(logs_router)
app.include_router(report_router)
app.include_router(alerts_router)
app.include_router(audit_router)
app.include_router(security_router)
app.include_router(anomalies_router)
app.include_router(compliance_router)
app.include_router(integrations_router)
app.include_router(ingest_router)
app.include_router(storage_router)
app.include_router(customers_router)
app.include_router(projects_router)
app.include_router(manifests_router)


# Frontend crash reporting — no auth required (fire-and-forget from ErrorBoundary)
@app.post("/api/frontend-error")
def frontend_error(body: dict):
    logger.error(f"FRONTEND CRASH: error={body.get('error')} "
                 f"component={body.get('componentStack', '')[:200]} "
                 f"uptime={body.get('uptime_ms')}ms "
                 f"stack={body.get('stack', '')[:300]}")
    return {"status": "logged"}


@app.on_event("startup")
async def startup():
    """Start background polling loops."""
    asyncio.create_task(coldvault.poll_loop())
    asyncio.create_task(gcp_logging.poll_loop())
    asyncio.create_task(gcp_monitoring.poll_loop())
    # Discovery runs in background thread (sync GCP API calls)
    if DISCOVERY_ENABLED:
        if ORG_DISCOVERY_ENABLED:
            from src.discovery.scheduler import start_scheduler
            start_scheduler(project_interval_seconds=DISCOVERY_INTERVAL)
            logger.info("Multi-project discovery scheduler started")
        else:
            threading.Thread(target=discovery_loop, args=(DISCOVERY_INTERVAL,), daemon=True).start()
            logger.info("Single-project discovery loop started")
    # GCS bucket monitoring (sync, runs in thread)
    threading.Thread(target=gcs_bucket.poll_loop, daemon=True).start()
    logger.info("GCS bucket monitor started")
    # CVE scanner (sync, runs in thread — default: every 6h)
    if SECURITY_SCAN_ENABLED:
        threading.Thread(target=cve_scanner.poll_loop, daemon=True).start()
        logger.info("CVE scanner started")
    # ServiceNow sync (sync, runs in thread)
    if SNOW_ENABLED:
        threading.Thread(target=sync_loop, daemon=True).start()
        logger.info("ServiceNow sync loop started")
    # Manifest metrics poller (sync, polls GCP metrics per YAML config)
    threading.Thread(target=manifest_metrics.metrics_loop, daemon=True).start()
    logger.info("Manifest metrics poller started")
    # Analysis runs in background thread (sync, uses ThreadPoolExecutor internally)
    threading.Thread(target=analysis_loop, args=(get_topology_data,), daemon=True).start()
    # Storage pipeline (sync, runs in thread)
    if STORAGE_ENABLED:
        from src.storage.pipeline import flush_loop, ensure_table
        ensure_table()
        threading.Thread(target=flush_loop, args=(STORAGE_FLUSH_INTERVAL,), daemon=True).start()
        logger.info("Storage pipeline started")
    # Retention archiver (sync, runs in thread)
    if RETENTION_ENABLED:
        from src.storage.retention import archive_loop
        threading.Thread(target=archive_loop, args=(3600,), daemon=True).start()
        logger.info("Retention archiver started")
    logger.info("GlassHood started — polling loops active")

    # Run initial polls immediately
    asyncio.create_task(coldvault.poll_once())


@app.on_event("shutdown")
async def shutdown():
    """F-007: Stop background threads on shutdown."""
    if STORAGE_ENABLED:
        from src.storage import pipeline
        pipeline.stop()
        logger.info("Storage pipeline stopped")
    if RETENTION_ENABLED:
        from src.storage import retention
        retention.stop()
        logger.info("Retention archiver stopped")


@app.get("/api/health")
async def health():
    return {"status": "healthy", "service": "GlassHood"}


def _read_version() -> str:
    """Read version from VERSION file (Docker: /app/VERSION, local: repo root)."""
    for p in [Path("/app/VERSION"), Path(__file__).resolve().parents[2] / "VERSION"]:
        if p.exists():
            return p.read_text().strip()
    return "unknown"


@app.get("/api/version")
async def version():
    return {"version": _read_version(), "service": "GlassHood"}


# Static file serving (production: React build in /app/static)
static_path = Path("/app/static")
if static_path.exists():
    if (static_path / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(static_path / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")

        static_file = static_path / full_path
        if static_file.exists() and static_file.is_file():
            return FileResponse(str(static_file))

        index = static_path / "index.html"
        if index.exists():
            return FileResponse(str(index))

        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=8080, reload=True)
