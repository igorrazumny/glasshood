# File: tests/test_scheduler.py
# Purpose: Tests for discovery scheduler (A.4)

from unittest.mock import patch, MagicMock, call
import threading
import time
import pytest

from src.discovery.scheduler import DiscoveryScheduler


class TestDiscoveryScheduler:
    @patch("src.discovery.scheduler.ORG_DISCOVERY_ENABLED", False)
    @patch("src.discovery.scheduler.discover_single")
    def test_single_project_mode(self, mock_discover):
        """When org discovery is off, uses single-project discover."""
        sched = DiscoveryScheduler(project_interval_seconds=1)
        sched._run_project_scan()
        mock_discover.assert_called_once()

    @patch("src.discovery.scheduler.ORG_DISCOVERY_ENABLED", True)
    @patch("src.discovery.scheduler.discover_all")
    @patch("src.discovery.scheduler.get_cached_projects",
           return_value=[{"project_id": "nr-cv-prod", "product": "cv", "environment": "prod"}])
    def test_multi_project_mode(self, mock_cached, mock_discover_all):
        """When org discovery is on, uses multi-project discover_all."""
        sched = DiscoveryScheduler()
        sched._run_project_scan()
        mock_discover_all.assert_called_once()
        args = mock_discover_all.call_args[0][0]
        assert args[0]["project_id"] == "nr-cv-prod"

    @patch("src.discovery.scheduler.ORG_DISCOVERY_ENABLED", True)
    @patch("src.discovery.scheduler.discover_projects",
           return_value=[{"project_id": "test"}])
    def test_org_scan(self, mock_discover_projects):
        sched = DiscoveryScheduler()
        sched._run_org_scan()
        mock_discover_projects.assert_called_once()
        assert sched._last_org_scan > 0

    @patch("src.discovery.scheduler.ORG_DISCOVERY_ENABLED", False)
    def test_org_scan_disabled(self):
        sched = DiscoveryScheduler()
        sched._run_org_scan()
        assert sched._last_org_scan == 0

    def test_stop(self):
        sched = DiscoveryScheduler()
        assert not sched._stop.is_set()
        sched.stop()
        assert sched._stop.is_set()

    @patch("src.discovery.scheduler.ORG_DISCOVERY_ENABLED", False)
    @patch("src.discovery.scheduler.discover_single")
    def test_trigger_scan_all(self, mock_discover):
        sched = DiscoveryScheduler()
        sched.trigger_scan()
        mock_discover.assert_called()

    @patch("src.discovery.scheduler.discover_all")
    @patch("src.discovery.scheduler.get_cached_projects", return_value=[])
    def test_trigger_scan_specific_project(self, mock_cached, mock_discover_all):
        sched = DiscoveryScheduler()
        sched.trigger_scan(project_id="nr-cv-prod")
        mock_discover_all.assert_called_once()
        args = mock_discover_all.call_args[0][0]
        assert args[0]["project_id"] == "nr-cv-prod"

    @patch("src.discovery.scheduler.ORG_DISCOVERY_ENABLED", False)
    @patch("src.discovery.scheduler.discover_single")
    def test_run_loop_stops(self, mock_discover):
        """Scheduler run() respects stop signal."""
        sched = DiscoveryScheduler(project_interval_seconds=60)
        # Stop immediately after starting
        threading.Timer(0.1, sched.stop).start()
        sched.run()  # Should return quickly
        assert sched._stop.is_set()
