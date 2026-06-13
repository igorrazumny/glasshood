# File: src/discovery/scheduler.py
# Purpose: Schedule discovery scans at configurable intervals

import logging
import threading
import time

from src.config.settings import (
    DISCOVERY_INTERVAL, ORG_DISCOVERY_ENABLED, ORG_DISCOVERY_CONFIG_PATH,
)
from src.discovery.gcp_assets import discover as discover_single
from src.discovery.org_projects import discover_projects, get_cached_projects
from src.discovery.multi_project import discover_all

logger = logging.getLogger(__name__)


class DiscoveryScheduler:
    """Schedule org and project discovery scans."""

    def __init__(self, org_interval_hours: int = 24,
                 project_interval_seconds: int = DISCOVERY_INTERVAL):
        self._org_interval = org_interval_hours * 3600
        self._project_interval = project_interval_seconds
        self._last_org_scan: float = 0
        self._last_project_scan: float = 0
        self._stop = threading.Event()

    def run(self):
        """Main loop: org scan daily, per-project scan per interval."""
        # Initial scan immediately
        self._run_org_scan()
        self._run_project_scan()

        while not self._stop.wait(min(60, self._project_interval)):
            now = time.time()
            if now - self._last_org_scan > self._org_interval:
                self._run_org_scan()
            if now - self._last_project_scan > self._project_interval:
                self._run_project_scan()

    def _run_org_scan(self):
        """Discover new/removed projects at org level."""
        if not ORG_DISCOVERY_ENABLED:
            return
        try:
            projects = discover_projects(ORG_DISCOVERY_CONFIG_PATH)
            self._last_org_scan = time.time()
            logger.info(f"Scheduler: org scan complete — {len(projects)} projects")
        except Exception as e:
            logger.error(f"Scheduler: org scan failed — {e}")

    def _run_project_scan(self):
        """Scan all known projects for asset changes."""
        try:
            if ORG_DISCOVERY_ENABLED:
                projects = get_cached_projects()
                if projects:
                    discover_all(projects)
                else:
                    # No cached projects yet — single project fallback
                    discover_single()
            else:
                # Single-project mode (backward compatible)
                discover_single()
            self._last_project_scan = time.time()
        except Exception as e:
            logger.error(f"Scheduler: project scan failed — {e}")

    def trigger_scan(self, project_id: str = None):
        """Manual trigger (from API endpoint)."""
        if project_id:
            # Look up cached classification for this project
            cached = get_cached_projects()
            info = next((p for p in cached if p["project_id"] == project_id),
                        {"project_id": project_id, "product": "", "environment": ""})
            try:
                discover_all([info])
                logger.info(f"Scheduler: manual scan for {project_id} complete")
            except Exception as e:
                logger.error(f"Scheduler: manual scan failed for {project_id}: {e}")
        else:
            self._run_org_scan()
            self._run_project_scan()

    def stop(self):
        """Signal the scheduler to stop."""
        self._stop.set()


# Module-level singleton for API access
_scheduler: DiscoveryScheduler = None


def get_scheduler() -> DiscoveryScheduler:
    """Return the global scheduler instance."""
    return _scheduler


def start_scheduler(org_interval_hours: int = 24,
                    project_interval_seconds: int = DISCOVERY_INTERVAL):
    """Create and start the scheduler in a daemon thread."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("Scheduler already running — ignoring duplicate start")
        return _scheduler
    _scheduler = DiscoveryScheduler(
        org_interval_hours=org_interval_hours,
        project_interval_seconds=project_interval_seconds,
    )
    thread = threading.Thread(target=_scheduler.run, daemon=True)
    thread.start()
    logger.info("Discovery scheduler started")
    return _scheduler
