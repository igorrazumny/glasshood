# File: tests/test_org_projects.py
# Purpose: Tests for GCP org-level project discovery (A.2)

from unittest.mock import patch, MagicMock
import yaml
import pytest

from src.discovery.org_projects import (
    classify_project, _matches_patterns, _load_config, discover_projects,
    get_cached_projects, get_project_ids,
)


class TestMatchesPatterns:
    def test_wildcard_match(self):
        assert _matches_patterns("nr-coldvault-prod", ["nr-*"])

    def test_exact_match(self):
        assert _matches_patterns("example-monitoring-project", ["braintransplant-*"])

    def test_no_match(self):
        assert not _matches_patterns("random-project", ["nr-*", "braintransplant-*"])

    def test_empty_patterns(self):
        assert not _matches_patterns("anything", [])


class TestClassifyProject:
    def test_standard_display_name(self):
        result = classify_project("ColdVault Prod")
        assert result["product"] == "coldvault"
        assert result["environment"] == "prod"

    def test_validation_env(self):
        result = classify_project("GlassHood Val")
        assert result["product"] == "glasshood"
        assert result["environment"] == "val"

    def test_multi_word_name(self):
        result = classify_project("9Robots Platform Prod")
        assert result["product"] == "platform"
        assert result["environment"] == "prod"

    def test_multi_word_name_val(self):
        result = classify_project("9Robots Platform Val")
        assert result["product"] == "platform"
        assert result["environment"] == "val"

    def test_single_word(self):
        result = classify_project("Benchmark")
        assert result["product"] == "benchmark"
        assert result["environment"] == ""

    def test_empty_name(self):
        result = classify_project("")
        assert result["product"] == ""
        assert result["environment"] == ""

    def test_proofbench(self):
        result = classify_project("ProofBench Prod")
        assert result["product"] == "proofbench"
        assert result["environment"] == "prod"

    def test_batchguard(self):
        result = classify_project("BatchGuard Prod")
        assert result["product"] == "batchguard"
        assert result["environment"] == "prod"

    def test_runrobin(self):
        result = classify_project("RunRobin Prod")
        assert result["product"] == "runrobin"
        assert result["environment"] == "prod"

    def test_buildrobin(self):
        result = classify_project("BuildRobin Prod")
        assert result["product"] == "buildrobin"
        assert result["environment"] == "prod"

    def test_case_insensitive_output(self):
        result = classify_project("ColdVault PROD")
        assert result["product"] == "coldvault"
        assert result["environment"] == "prod"

    def test_non_env_last_word(self):
        """Multi-word name where last word is not a known environment."""
        result = classify_project("9Robots Website")
        assert result["product"] == "website"
        assert result["environment"] == ""

    def test_non_env_three_words(self):
        """Three-word name where last word is not a known environment."""
        result = classify_project("9Robots Internal Tools")
        assert result["product"] == "tools"
        assert result["environment"] == ""

    def test_dev_env(self):
        result = classify_project("ColdVault Dev")
        assert result["product"] == "coldvault"
        assert result["environment"] == "dev"

    def test_staging_env(self):
        result = classify_project("Platform Staging")
        assert result["product"] == "platform"
        assert result["environment"] == "staging"


class TestLoadConfig:
    def test_loads_valid_config(self, tmp_path):
        f = tmp_path / "org.yaml"
        f.write_text(yaml.dump({
            "org_discovery": {
                "org_id": "123456",
                "include_patterns": ["nr-*"],
            }
        }))
        result = _load_config(str(f))
        assert result["org_id"] == "123456"
        assert result["include_patterns"] == ["nr-*"]

    def test_missing_file(self):
        result = _load_config("/nonexistent/org.yaml")
        assert result == {}

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        result = _load_config(str(f))
        assert result == {}


class TestDiscoverProjects:
    @patch("src.discovery.org_projects._list_org_projects")
    def test_discovers_and_classifies(self, mock_list, tmp_path):
        mock_list.return_value = [
            {"project_id": "example-legacy-project", "display_name": "ColdVault Prod",
             "state": "ACTIVE", "labels": {}, "parent": ""},
            {"project_id": "nr-100k1n991455-prod", "display_name": "GlassHood Val",
             "state": "ACTIVE", "labels": {}, "parent": ""},
        ]
        f = tmp_path / "org.yaml"
        f.write_text(yaml.dump({
            "org_discovery": {
                "org_id": "000000000000",
                "include_patterns": ["nr-*"],
                "exclude_patterns": [],
            }
        }))

        result = discover_projects(str(f))
        assert len(result) == 2
        # Sorted by project_id: nr-100k... (glasshood) before nr-1c3... (coldvault)
        assert result[0]["product"] == "glasshood"
        assert result[0]["environment"] == "val"
        assert result[0]["project_id"] == "nr-100k1n991455-prod"
        assert result[1]["product"] == "coldvault"
        assert result[1]["environment"] == "prod"

    @patch("src.discovery.org_projects._list_org_projects")
    def test_excludes_patterns(self, mock_list, tmp_path):
        mock_list.return_value = [
            {"project_id": "example-legacy-project", "display_name": "ColdVault Prod",
             "state": "ACTIVE", "labels": {}, "parent": ""},
            {"project_id": "nr-test-sandbox", "display_name": "Test Sandbox",
             "state": "ACTIVE", "labels": {}, "parent": ""},
        ]
        f = tmp_path / "org.yaml"
        f.write_text(yaml.dump({
            "org_discovery": {
                "org_id": "123",
                "include_patterns": ["nr-*"],
                "exclude_patterns": ["*-sandbox"],
            }
        }))
        result = discover_projects(str(f))
        assert len(result) == 1
        assert result[0]["project_id"] == "example-legacy-project"

    @patch("src.discovery.org_projects._list_org_projects")
    def test_skips_inactive(self, mock_list, tmp_path):
        mock_list.return_value = [
            {"project_id": "nr-old-prod", "display_name": "OldProject Prod",
             "state": "DELETE_REQUESTED", "labels": {}, "parent": ""},
        ]
        f = tmp_path / "org.yaml"
        f.write_text(yaml.dump({
            "org_discovery": {
                "org_id": "123",
                "include_patterns": ["nr-*"],
                "exclude_patterns": [],
            }
        }))
        result = discover_projects(str(f))
        assert len(result) == 0

    @patch("src.discovery.org_projects.GCP_PROJECT_DISPLAY_NAME", "ColdVault Prod")
    @patch("src.discovery.org_projects.GCP_PROJECT_ID", "example-monitoring-project")
    @patch("src.discovery.org_projects._list_org_projects")
    def test_fallback_single_project(self, mock_list, tmp_path):
        mock_list.return_value = []  # Org discovery fails
        f = tmp_path / "org.yaml"
        f.write_text(yaml.dump({
            "org_discovery": {
                "org_id": "123",
                "include_patterns": ["*"],
                "exclude_patterns": [],
            }
        }))
        result = discover_projects(str(f))
        assert len(result) == 1
        assert result[0]["project_id"] == "example-monitoring-project"
        assert result[0]["display_name"] == "ColdVault Prod"
        assert result[0]["product"] == "coldvault"
        assert result[0]["environment"] == "prod"

    @patch("src.discovery.org_projects._list_org_projects")
    def test_cached_projects(self, mock_list, tmp_path):
        mock_list.return_value = [
            {"project_id": "example-legacy-project", "display_name": "ColdVault Prod",
             "state": "ACTIVE", "labels": {}, "parent": ""},
        ]
        f = tmp_path / "org.yaml"
        f.write_text(yaml.dump({
            "org_discovery": {
                "org_id": "123",
                "include_patterns": ["nr-*"],
                "exclude_patterns": [],
            }
        }))
        discover_projects(str(f))
        cached = get_cached_projects()
        assert len(cached) == 1
        ids = get_project_ids()
        assert "example-legacy-project" in ids

    @patch("src.discovery.org_projects._list_org_projects")
    def test_multi_word_platform_name(self, mock_list, tmp_path):
        mock_list.return_value = [
            {"project_id": "example-platform-project",
             "display_name": "9Robots Platform Prod",
             "state": "ACTIVE", "labels": {}, "parent": ""},
        ]
        f = tmp_path / "org.yaml"
        f.write_text(yaml.dump({
            "org_discovery": {
                "org_id": "123",
                "include_patterns": ["nr-*"],
                "exclude_patterns": [],
            }
        }))
        result = discover_projects(str(f))
        assert len(result) == 1
        assert result[0]["product"] == "platform"
        assert result[0]["environment"] == "prod"
