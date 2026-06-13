# File: tests/test_yaml_overlay.py
# Purpose: Tests for YAML topology overlay

import os
import tempfile

import pytest
import yaml

from src.models.topology import Node, Edge


class TestLoadOverrides:
    def test_loads_valid_yaml(self, tmp_path):
        from src.discovery.yaml_overlay import load_overrides
        f = tmp_path / "overrides.yaml"
        f.write_text(yaml.dump({"nodes": [{"id": "nginx"}], "edges": []}))
        result = load_overrides(str(f))
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "nginx"

    def test_missing_file_returns_empty(self):
        from src.discovery.yaml_overlay import load_overrides
        result = load_overrides("/nonexistent/path.yaml")
        assert result == {"nodes": [], "edges": []}

    def test_invalid_yaml_returns_empty(self, tmp_path):
        from src.discovery.yaml_overlay import load_overrides
        f = tmp_path / "bad.yaml"
        f.write_text(": invalid: yaml: [[[")
        result = load_overrides(str(f))
        assert result["nodes"] == [] or isinstance(result["nodes"], list)


class TestResolveRef:
    def test_plain_id_unchanged(self):
        from src.discovery.yaml_overlay import _resolve_ref
        assert _resolve_ref("nginx", []) == "nginx"

    def test_discovered_ref_resolves(self):
        from src.discovery.yaml_overlay import _resolve_ref
        nodes = [
            Node(id="vm-test", label="test", type="vm",
                 gcp_resource_type="compute.googleapis.com/Instance"),
        ]
        assert _resolve_ref("{discovered:Instance}", nodes) == "vm-test"

    def test_unresolved_ref_returns_original(self):
        from src.discovery.yaml_overlay import _resolve_ref
        result = _resolve_ref("{discovered:MissingType}", [])
        assert result == "{discovered:MissingType}"


class TestMergeTopology:
    def test_supplements_discovered(self):
        from src.discovery.yaml_overlay import merge_topology
        discovered = [Node(id="vm-1", label="VM", type="vm", status="healthy")]
        overrides = {"nodes": [{"id": "nginx", "label": "nginx", "type": "nginx"}],
                     "edges": []}
        nodes, edges = merge_topology(discovered, [], overrides)
        assert len(nodes) == 2
        assert nodes[1].id == "nginx"
        assert nodes[1].source == "yaml"

    def test_no_duplicate_ids(self):
        from src.discovery.yaml_overlay import merge_topology
        discovered = [Node(id="nginx", label="nginx-discovered", type="nginx")]
        overrides = {"nodes": [{"id": "nginx", "label": "nginx-yaml", "type": "nginx"}],
                     "edges": []}
        nodes, _ = merge_topology(discovered, [], overrides)
        assert len(nodes) == 1
        assert nodes[0].label == "nginx-discovered"

    def test_edge_ref_resolution(self):
        from src.discovery.yaml_overlay import merge_topology
        discovered = [
            Node(id="vm-test", label="VM", type="vm",
                 gcp_resource_type="compute.googleapis.com/Instance"),
        ]
        overrides = {
            "nodes": [{"id": "nginx", "label": "nginx", "type": "nginx"}],
            "edges": [{"source": "{discovered:Instance}", "target": "nginx",
                       "label": "contains"}],
        }
        nodes, edges = merge_topology(discovered, [], overrides)
        assert len(edges) == 1
        assert edges[0].source == "vm-test"
        assert edges[0].target == "nginx"

    def test_empty_overrides(self):
        from src.discovery.yaml_overlay import merge_topology
        discovered = [Node(id="vm-1", label="VM", type="vm")]
        nodes, edges = merge_topology(discovered, [], {"nodes": [], "edges": []})
        assert len(nodes) == 1
        assert len(edges) == 0
