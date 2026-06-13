# File: src/discovery/diff.py
# Purpose: Topology diff — detect added, removed, changed nodes between cycles

import logging
import threading
from typing import Optional

from src.models.topology import Node

logger = logging.getLogger(__name__)

# Fields that matter for diff (ignore ephemeral GCP metadata)
_CANONICAL_FIELDS = ("id", "type", "status", "label", "gcp_resource_type")

_previous_snapshot: Optional[dict] = None
_current_diff: dict = {"added": [], "removed": [], "changed": [], "first_run": True}
_lock = threading.Lock()


def _canonicalize(node) -> dict:
    """Extract only meaningful fields for comparison."""
    if isinstance(node, Node):
        return {f: getattr(node, f, None) for f in _CANONICAL_FIELDS}
    if isinstance(node, dict):
        return {f: node.get(f) for f in _CANONICAL_FIELDS}
    return {}


def compute_diff(previous_nodes: list, current_nodes: list) -> dict:
    """Compare two node lists. Returns {added, removed, changed}.

    Canonicalizes nodes to ignore ephemeral fields (timestamps, fingerprints,
    selfLink, etags). Compares by node ID.
    """
    prev_map = {_canonicalize(n)["id"]: _canonicalize(n) for n in previous_nodes}
    curr_map = {_canonicalize(n)["id"]: _canonicalize(n) for n in current_nodes}

    prev_ids = set(prev_map.keys())
    curr_ids = set(curr_map.keys())

    added = sorted(curr_ids - prev_ids)
    removed = sorted(prev_ids - curr_ids)
    changed = []
    for nid in sorted(prev_ids & curr_ids):
        if prev_map[nid] != curr_map[nid]:
            changed.append({
                "id": nid,
                "before": prev_map[nid],
                "after": curr_map[nid],
            })

    return {"added": added, "removed": removed, "changed": changed}


def update_snapshot(nodes: list) -> dict:
    """Update the stored snapshot and return diff from previous cycle."""
    global _previous_snapshot, _current_diff

    with _lock:
        if _previous_snapshot is None:
            _previous_snapshot = {_canonicalize(n)["id"]: _canonicalize(n)
                                  for n in nodes}
            _current_diff = {"added": [], "removed": [], "changed": [],
                             "first_run": True}
            return _current_diff

        diff = compute_diff(
            [v for v in _previous_snapshot.values()],
            nodes,
        )
        diff["first_run"] = False
        _current_diff = diff
        _previous_snapshot = {_canonicalize(n)["id"]: _canonicalize(n)
                              for n in nodes}

        if diff["added"] or diff["removed"] or diff["changed"]:
            logger.info(f"Topology diff: +{len(diff['added'])} "
                        f"-{len(diff['removed'])} ~{len(diff['changed'])}")

        return diff


def get_diff() -> dict:
    """Return the latest topology diff."""
    with _lock:
        return dict(_current_diff)
