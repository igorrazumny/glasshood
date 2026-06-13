# File: tests/test_projects_api.py
# Purpose: Tests for multi-project API endpoints (A.5)

from unittest.mock import patch, MagicMock
import pytest

from src.models.topology import Node, Edge


class TestListProjects:
    @patch("src.api.routes.projects.verify_token")
    @patch("src.api.routes.projects.get_cached_projects", return_value=[
        {"project_id": "nr-cv-prod", "product": "coldvault",
         "environment": "prod", "state": "ACTIVE", "display_name": "ColdVault Prod"},
        {"project_id": "nr-gh-prod", "product": "glasshood",
         "environment": "prod", "state": "ACTIVE", "display_name": "GlassHood Prod"},
    ])
    def test_returns_projects(self, mock_cached, mock_auth):
        from src.api.routes.projects import list_projects
        result = list_projects(MagicMock())
        assert len(result) == 2
        assert result[0]["product"] == "coldvault"

    @patch("src.api.routes.projects.verify_token")
    @patch("src.api.routes.projects.get_cached_projects", return_value=[])
    def test_fallback_single_project(self, mock_cached, mock_auth):
        from src.api.routes.projects import list_projects
        result = list_projects(MagicMock())
        assert len(result) == 1
        assert result[0]["product"] == "coldvault"


class TestProjectTopology:
    @patch("src.api.routes.projects.verify_token")
    @patch("src.api.routes.projects.get_project_topology", return_value={
        "nodes": [Node(id="vm-1", label="VM", type="vm", project="cv", env="prod")],
        "edges": [Edge(source="vm-1", target="nginx", label="contains")],
    })
    def test_returns_project_topology(self, mock_topo, mock_auth):
        from src.api.routes.projects import get_project_topo
        result = get_project_topo("nr-cv-prod", MagicMock())
        assert result["project_id"] == "nr-cv-prod"
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["project"] == "cv"

    @patch("src.api.routes.projects.verify_token")
    @patch("src.api.routes.projects.get_project_topology",
           return_value={"nodes": [], "edges": []})
    def test_empty_project(self, mock_topo, mock_auth):
        from src.api.routes.projects import get_project_topo
        result = get_project_topo("nonexistent", MagicMock())
        assert result["nodes"] == []


class TestAllTopology:
    @patch("src.api.routes.projects.verify_token")
    @patch("src.api.routes.projects.get_project_count", return_value=2)
    @patch("src.api.routes.projects.get_combined_topology", return_value={
        "nodes": [
            Node(id="vm-1", label="VM1", type="vm", project="cv", env="prod"),
            Node(id="vm-2", label="VM2", type="vm", project="gh", env="prod"),
        ],
        "edges": [],
    })
    def test_combined_topology(self, mock_combined, mock_count, mock_auth):
        from src.api.routes.projects import get_all_topology
        result = get_all_topology(MagicMock())
        assert len(result["nodes"]) == 2
        assert result["project_count"] == 2
        assert result["nodes"][0]["project"] == "cv"


class TestTriggerDiscovery:
    @patch("src.api.routes.projects.verify_token")
    def test_no_scheduler(self, mock_auth):
        from src.api.routes.projects import trigger_discovery
        with patch("src.discovery.scheduler.get_scheduler", return_value=None):
            result = trigger_discovery(MagicMock())
            assert result["status"] == "scheduler_not_running"

    @patch("src.api.routes.projects.verify_token")
    def test_trigger_all(self, mock_auth):
        from src.api.routes.projects import trigger_discovery
        mock_sched = MagicMock()
        with patch("src.discovery.scheduler.get_scheduler", return_value=mock_sched):
            result = trigger_discovery(MagicMock())
            mock_sched.trigger_scan.assert_called_once_with(project_id=None)
            assert result["status"] == "triggered"

    @patch("src.api.routes.projects.verify_token")
    def test_trigger_specific(self, mock_auth):
        from src.api.routes.projects import trigger_discovery
        mock_sched = MagicMock()
        with patch("src.discovery.scheduler.get_scheduler", return_value=mock_sched):
            result = trigger_discovery(MagicMock(), project_id="nr-cv-prod")
            mock_sched.trigger_scan.assert_called_once_with(project_id="nr-cv-prod")
            assert result["project_id"] == "nr-cv-prod"
