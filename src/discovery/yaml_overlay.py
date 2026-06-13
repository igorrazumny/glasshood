# File: src/discovery/yaml_overlay.py
# Purpose: YAML fallback for nodes GCP APIs can't discover

import logging
from pathlib import Path

import yaml

from src.models.topology import Node, Edge

logger = logging.getLogger(__name__)


def load_overrides(path: str) -> dict:
    """Load topology overrides from YAML file. Returns empty on missing/invalid."""
    p = Path(path)
    if not p.exists():
        logger.warning(f"Overrides file not found: {path}")
        return {"nodes": [], "edges": []}
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        nodes = list(data.get("nodes", []))
        edges = list(data.get("edges", []))

        # Load active infrastructure profile (planned/expected nodes)
        active = data.get("active_profile", "")
        profiles = data.get("profiles", {})
        if active and active in profiles:
            profile = profiles[active]
            nodes.extend(profile.get("nodes", []))
            edges.extend(profile.get("edges", []))
            logger.info(f"Loaded profile '{active}': "
                        f"{len(profile.get('nodes', []))} nodes, "
                        f"{len(profile.get('edges', []))} edges")

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.error(f"Failed to load overrides: {e}")
        return {"nodes": [], "edges": []}


def _resolve_ref(ref: str, discovered_nodes: list) -> str:
    """Resolve {discovered:ResourceType} to the first matching discovered node ID."""
    if not ref.startswith("{discovered:"):
        return ref
    resource_type = ref[len("{discovered:"):-1]
    for node in discovered_nodes:
        gcp_type = node.gcp_resource_type or ""
        if gcp_type.endswith(f"/{resource_type}"):
            return node.id
    logger.warning(f"No discovered node for ref: {ref}")
    return ref


def merge_topology(discovered_nodes: list, discovered_edges: list,
                   overrides: dict) -> tuple:
    """Merge discovered topology with YAML overrides.

    Override nodes supplement discovered (no duplicates by ID).
    Override edges get {discovered:Type} refs resolved.
    Returns (merged_nodes, merged_edges).
    """
    existing_ids = {n.id for n in discovered_nodes}
    merged_nodes = list(discovered_nodes)
    merged_edges = list(discovered_edges)

    for node_dict in overrides.get("nodes", []):
        nid = node_dict.get("id", "")
        if nid and nid not in existing_ids:
            merged_nodes.append(Node(
                id=nid,
                label=node_dict.get("label", nid),
                type=node_dict.get("type", "unknown"),
                status=node_dict.get("status", "unknown"),
                icon=node_dict.get("icon", ""),
                metrics=node_dict.get("metrics", {}),
                source="yaml",
                project=node_dict.get("project", ""),
                env=node_dict.get("env", ""),
            ))
            existing_ids.add(nid)

    for edge_dict in overrides.get("edges", []):
        src = _resolve_ref(edge_dict.get("source", ""), merged_nodes)
        tgt = _resolve_ref(edge_dict.get("target", ""), merged_nodes)
        if src and tgt:
            merged_edges.append(Edge(
                source=src, target=tgt,
                label=edge_dict.get("label", ""),
                status=edge_dict.get("status", "unknown"),
            ))

    return merged_nodes, merged_edges
