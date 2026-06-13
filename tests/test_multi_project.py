# File: tests/test_multi_project.py
# Purpose: Tests for multi-project asset discovery (A.3)

from unittest.mock import patch, MagicMock
import pytest

from src.models.topology import Node, Edge
from src.discovery import multi_project
from src.discovery.multi_project import (
    discover_all, get_project_topology, get_all_topologies,
    get_combined_topology, get_project_count, _discover_project,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear module-level cache between tests."""
    multi_project._cached.clear()
    yield
    multi_project._cached.clear()


def _fake_build_graph(project_id=None, project="", env=""):
    """Return a small fake topology for testing."""
    return {
        "nodes": [
            Node(id=f"vm-{project_id}", label=f"VM {project_id}", type="vm",
                 status="healthy", project=project, env=env),
        ],
        "edges": [
            Edge(source=f"vm-{project_id}", target="nginx", label="contains"),
        ],
    }


class TestDiscoverProject:
    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_returns_project_id_and_result(self, mock_bg):
        info = {"project_id": "nr-cv-prod", "product": "coldvault", "environment": "prod"}
        pid, result = _discover_project(info)
        assert pid == "nr-cv-prod"
        assert len(result["nodes"]) == 1
        assert result["nodes"][0].project == "coldvault"
        mock_bg.assert_called_once_with(
            project_id="nr-cv-prod", project="coldvault", env="prod")

    @patch("src.discovery.multi_project.build_graph",
           side_effect=Exception("IAM denied"))
    def test_handles_failure(self, mock_bg):
        info = {"project_id": "bad-project", "product": "", "environment": ""}
        pid, result = _discover_project(info)
        assert pid == "bad-project"
        assert result["nodes"] == []
        assert result["edges"] == []


class TestDiscoverAll:
    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_parallel_discovery(self, mock_bg):
        infos = [
            {"project_id": "nr-cv-prod", "product": "coldvault", "environment": "prod"},
            {"project_id": "nr-gh-prod", "product": "glasshood", "environment": "prod"},
        ]
        results = discover_all(infos, max_workers=2)
        assert len(results) == 2
        assert "nr-cv-prod" in results
        assert "nr-gh-prod" in results
        assert len(results["nr-cv-prod"]["nodes"]) == 1
        assert results["nr-cv-prod"]["timestamp"] > 0

    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_empty_project_list(self, mock_bg):
        results = discover_all([])
        assert results == {}

    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_single_project(self, mock_bg):
        infos = [{"project_id": "only-one", "product": "test", "environment": "prod"}]
        results = discover_all(infos, max_workers=1)
        assert len(results) == 1
        assert results["only-one"]["nodes"][0].project == "test"


class TestCacheAccess:
    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_get_project_topology(self, mock_bg):
        infos = [
            {"project_id": "nr-cv-prod", "product": "coldvault", "environment": "prod"},
        ]
        discover_all(infos)
        topo = get_project_topology("nr-cv-prod")
        assert len(topo["nodes"]) == 1
        assert topo["nodes"][0].id == "vm-nr-cv-prod"

    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_get_project_topology_missing(self, mock_bg):
        topo = get_project_topology("nonexistent")
        assert topo["nodes"] == []

    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_get_all_topologies(self, mock_bg):
        infos = [
            {"project_id": "a", "product": "x", "environment": "prod"},
            {"project_id": "b", "product": "y", "environment": "val"},
        ]
        discover_all(infos)
        all_topos = get_all_topologies()
        assert "a" in all_topos
        assert "b" in all_topos

    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_get_combined_topology(self, mock_bg):
        infos = [
            {"project_id": "a", "product": "x", "environment": "prod"},
            {"project_id": "b", "product": "y", "environment": "val"},
        ]
        discover_all(infos)
        combined = get_combined_topology()
        assert len(combined["nodes"]) == 2
        assert len(combined["edges"]) == 2

    @patch("src.discovery.multi_project.build_graph", side_effect=_fake_build_graph)
    def test_project_count(self, mock_bg):
        infos = [
            {"project_id": "a", "product": "x", "environment": "prod"},
            {"project_id": "b", "product": "y", "environment": "val"},
            {"project_id": "c", "product": "z", "environment": "prod"},
        ]
        discover_all(infos)
        assert get_project_count() == 3
