# File: tests/test_diff.py
# Purpose: Tests for topology diff and change detection

import pytest

from src.models.topology import Node


def _reset_module():
    import src.discovery.diff as mod
    mod._previous_snapshot = None
    mod._current_diff = {"added": [], "removed": [], "changed": [], "first_run": True}


class TestComputeDiff:
    def test_added_node(self):
        from src.discovery.diff import compute_diff
        prev = [Node(id="a", label="A", type="vm", status="healthy")]
        curr = [Node(id="a", label="A", type="vm", status="healthy"),
                Node(id="b", label="B", type="lb", status="healthy")]
        diff = compute_diff(prev, curr)
        assert diff["added"] == ["b"]
        assert diff["removed"] == []
        assert diff["changed"] == []

    def test_removed_node(self):
        from src.discovery.diff import compute_diff
        prev = [Node(id="a", label="A", type="vm"),
                Node(id="b", label="B", type="lb")]
        curr = [Node(id="a", label="A", type="vm")]
        diff = compute_diff(prev, curr)
        assert diff["removed"] == ["b"]

    def test_changed_status(self):
        from src.discovery.diff import compute_diff
        prev = [Node(id="a", label="A", type="vm", status="healthy")]
        curr = [Node(id="a", label="A", type="vm", status="error")]
        diff = compute_diff(prev, curr)
        assert len(diff["changed"]) == 1
        assert diff["changed"][0]["id"] == "a"
        assert diff["changed"][0]["before"]["status"] == "healthy"
        assert diff["changed"][0]["after"]["status"] == "error"

    def test_empty_diff(self):
        from src.discovery.diff import compute_diff
        nodes = [Node(id="a", label="A", type="vm", status="healthy")]
        diff = compute_diff(nodes, nodes)
        assert diff == {"added": [], "removed": [], "changed": []}

    def test_ignores_ephemeral_fields(self):
        from src.discovery.diff import compute_diff
        prev = [Node(id="a", label="A", type="vm", status="healthy",
                      metrics={"timestamp": 1000, "fingerprint": "abc"})]
        curr = [Node(id="a", label="A", type="vm", status="healthy",
                      metrics={"timestamp": 2000, "fingerprint": "xyz"})]
        diff = compute_diff(prev, curr)
        assert diff["changed"] == []

    def test_both_empty(self):
        from src.discovery.diff import compute_diff
        diff = compute_diff([], [])
        assert diff == {"added": [], "removed": [], "changed": []}


class TestUpdateSnapshot:
    def setup_method(self):
        _reset_module()

    def test_first_run(self):
        from src.discovery.diff import update_snapshot
        diff = update_snapshot([Node(id="a", label="A", type="vm")])
        assert diff["first_run"] is True
        assert diff["added"] == []

    def test_second_run_detects_change(self):
        from src.discovery.diff import update_snapshot
        update_snapshot([Node(id="a", label="A", type="vm", status="healthy")])
        diff = update_snapshot([Node(id="a", label="A", type="vm", status="error"),
                                Node(id="b", label="B", type="lb")])
        assert diff["first_run"] is False
        assert diff["added"] == ["b"]
        assert len(diff["changed"]) == 1

    def test_get_diff_returns_latest(self):
        from src.discovery.diff import update_snapshot, get_diff
        update_snapshot([Node(id="a", label="A", type="vm")])
        update_snapshot([Node(id="a", label="A", type="vm"),
                         Node(id="b", label="B", type="lb")])
        diff = get_diff()
        assert "b" in diff["added"]
