# File: src/discovery/model_discovery.py
# Purpose: Auto-discover LLM models from ColdVault configuration
# Changelog:
#   v2026-03-06.1 - Initial: read model_settings.yaml, generate topology nodes

import logging
import re
import threading
from pathlib import Path

import yaml

from src.models.topology import Node, Edge

logger = logging.getLogger(__name__)

# Cached model topology — refreshed on each discovery cycle
_cache_lock = threading.Lock()
_cached_nodes: list = []
_cached_edges: list = []

# Provider → mode mapping
_VAULT_PROVIDERS = {"redpill", "vllm"}
_SELF_HOSTED_PROVIDERS = {"vllm"}


def _slugify(name: str) -> str:
    """Convert display name to a stable node ID slug."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _load_model_config(path: str) -> dict:
    """Load model_settings.yaml and return model dict."""
    p = Path(path)
    if not p.exists():
        logger.warning(f"Model config not found: {path}")
        return {}
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        # Filter out non-dict entries (comments become None)
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception as e:
        logger.error(f"Failed to load model config: {e}")
        return {}


def _models_to_topology(models: dict) -> tuple:
    """Convert model settings dict to (nodes, edges) lists."""
    nodes = []
    edges = []
    seen_ids = set()

    for model_id, config in models.items():
        provider = config.get("provider", "unknown")
        display_name = config.get("display_name", model_id)
        node_id = _slugify(display_name)

        # Avoid duplicates (e.g. vLLM + RedPill versions of same model)
        if node_id in seen_ids:
            node_id = f"{node_id}_{provider}"
        seen_ids.add(node_id)

        # Determine mode from provider
        if provider in _SELF_HOSTED_PROVIDERS:
            mode = "self-hosted"
        elif provider in _VAULT_PROVIDERS:
            mode = "vault"
        else:
            mode = "partner"

        node = Node(
            id=node_id,
            label=display_name,
            type="llm",
            status="auto",
            icon="brain",
            source="model-discovery",
            metrics={
                "provider": provider,
                "mode": mode,
                "model_id": model_id,
            },
            project="coldvault",
            env="prod",
        )

        if mode == "self-hosted":
            node.metrics["runtime"] = "vLLM"
            node.metrics["gpu"] = "H100 80GB CC"
            # Empty health_url signals "configured but not deployed" —
            # topology enrichment resolves to "offline" when GPU is down
            node.metrics["health_url"] = ""

        nodes.append(node)

        # Edge from llm_router to this model
        edge_label = ""
        if mode == "vault":
            edge_label = "RedPill TEE"
        elif mode == "self-hosted":
            edge_label = "vLLM"

        edges.append(Edge(
            source="llm_router",
            target=node_id,
            label=edge_label,
            status="unknown",
        ))

    logger.info(f"Model discovery: {len(nodes)} models ({sum(1 for n in nodes if n.metrics.get('mode') == 'vault')} vault, "
                f"{sum(1 for n in nodes if n.metrics.get('mode') == 'self-hosted')} self-hosted, "
                f"{sum(1 for n in nodes if n.metrics.get('mode') == 'partner')} partner)")
    return nodes, edges


def discover_models(config_path: str = "config/model_settings.yaml") -> tuple:
    """Discover LLM models and return (nodes, edges).

    Reads from local model_settings.yaml (synced from ColdVault).
    Future: fetch from ColdVault API when endpoint available.
    """
    models = _load_model_config(config_path)
    if not models:
        return [], []
    return _models_to_topology(models)


def get_discovered_models() -> tuple:
    """Return cached discovered model nodes and edges."""
    with _cache_lock:
        return list(_cached_nodes), list(_cached_edges)


def refresh_model_cache(config_path: str = "config/model_settings.yaml"):
    """Refresh the model cache. Called during discovery cycle."""
    nodes, edges = discover_models(config_path)
    with _cache_lock:
        global _cached_nodes, _cached_edges
        _cached_nodes = nodes
        _cached_edges = edges
