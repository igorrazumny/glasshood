# File: tests/test_node_project_tagging.py
# Purpose: Tests for Node project/env tagging (A.1)

import tempfile
from pathlib import Path

import yaml
import pytest

from src.models.topology import Node, Edge, Topology


class TestNodeProjectFields:
    def test_default_empty(self):
        node = Node(id="test", label="Test", type="vm")
        assert node.project == ""
        assert node.env == ""

    def test_explicit_values(self):
        node = Node(id="test", label="Test", type="vm",
                    project="coldvault", env="prod")
        assert node.project == "coldvault"
        assert node.env == "prod"

    def test_to_dict_includes_project_env(self):
        node = Node(id="test", label="Test", type="vm",
                    project="glasshood", env="val")
        d = node.to_dict()
        assert d["project"] == "glasshood"
        assert d["env"] == "val"

    def test_to_dict_empty_project_env(self):
        node = Node(id="test", label="Test", type="vm")
        d = node.to_dict()
        assert d["project"] == ""
        assert d["env"] == ""

    def test_topology_to_dict_preserves_project(self):
        topo = Topology(nodes=[
            Node(id="n1", label="N1", type="vm", project="coldvault", env="prod"),
            Node(id="n2", label="N2", type="lb", project="platform", env="prod"),
        ])
        d = topo.to_dict()
        assert d["nodes"][0]["project"] == "coldvault"
        assert d["nodes"][1]["project"] == "platform"


class TestYamlOverlayProjectTags:
    def test_yaml_nodes_get_project_env(self):
        from src.discovery.yaml_overlay import merge_topology
        discovered = []
        overrides = {
            "nodes": [{"id": "nginx", "label": "nginx", "type": "nginx",
                       "project": "coldvault", "env": "prod"}],
            "edges": [],
        }
        nodes, _ = merge_topology(discovered, [], overrides)
        assert len(nodes) == 1
        assert nodes[0].project == "coldvault"
        assert nodes[0].env == "prod"

    def test_yaml_nodes_default_empty_project(self):
        from src.discovery.yaml_overlay import merge_topology
        overrides = {
            "nodes": [{"id": "test", "label": "test", "type": "vm"}],
            "edges": [],
        }
        nodes, _ = merge_topology([], [], overrides)
        assert nodes[0].project == ""
        assert nodes[0].env == ""

    def test_overrides_file_with_project_tags(self, tmp_path):
        from src.discovery.yaml_overlay import load_overrides, merge_topology
        f = tmp_path / "overrides.yaml"
        f.write_text(yaml.dump({
            "nodes": [
                {"id": "nginx", "label": "nginx", "type": "nginx",
                 "project": "coldvault", "env": "prod"},
                {"id": "gpu", "label": "H100", "type": "gpu",
                 "project": "platform", "env": "prod"},
            ],
            "edges": [],
        }))
        overrides = load_overrides(str(f))
        nodes, _ = merge_topology([], [], overrides)
        assert nodes[0].project == "coldvault"
        assert nodes[1].project == "platform"


class TestGcpAssetsProjectTags:
    def test_make_node_with_project_env(self):
        from src.discovery.gcp_assets import _make_node
        node = _make_node(
            "compute.googleapis.com/Instance", "test-vm",
            {"status": "RUNNING", "machineType": "zones/us-central1-a/machineTypes/n1-standard-4",
             "zone": "zones/us-central1-a"},
            project="coldvault", env="prod",
        )
        assert node.project == "coldvault"
        assert node.env == "prod"
        assert node.id == "vm-test-vm"

    def test_make_node_default_empty(self):
        from src.discovery.gcp_assets import _make_node
        node = _make_node(
            "compute.googleapis.com/ForwardingRule", "test-fr",
            {"IPAddress": "1.2.3.4"},
        )
        assert node.project == ""
        assert node.env == ""


class TestModelDiscoveryProjectTags:
    def test_model_nodes_tagged_coldvault(self, tmp_path):
        from src.discovery.model_discovery import discover_models
        f = tmp_path / "models.yaml"
        f.write_text(yaml.dump({
            "test-model": {
                "provider": "openai",
                "display_name": "GPT Test",
            },
        }))
        nodes, edges = discover_models(str(f))
        assert len(nodes) == 1
        assert nodes[0].project == "coldvault"
        assert nodes[0].env == "prod"
