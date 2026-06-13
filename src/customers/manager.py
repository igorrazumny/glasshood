# File: src/customers/manager.py
# Purpose: Load, list, get, create customer configurations from YAML files

import logging
import os
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CUSTOMERS_DIR = os.getenv("CUSTOMERS_CONFIG_DIR", "config/customers")
_VALID_ID = re.compile(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$")
_VALID_TIERS = {"standard", "professional", "enterprise"}

_REQUIRED_FIELDS = {"customer_id", "display_name", "tier", "region"}


def _customers_path() -> Path:
    return Path(CUSTOMERS_DIR)


def validate_customer_id(customer_id: str) -> bool:
    """Check customer_id is lowercase alphanumeric + hyphens, 3-64 chars."""
    return bool(_VALID_ID.match(customer_id))


def validate_config(config: dict) -> list[str]:
    """Return list of validation errors (empty = valid)."""
    errors = []
    for field in _REQUIRED_FIELDS:
        if not config.get(field):
            errors.append(f"Missing required field: {field}")
    cid = config.get("customer_id", "")
    if cid and not validate_customer_id(cid):
        errors.append(
            f"Invalid customer_id '{cid}': must be 3-64 chars, "
            "lowercase alphanumeric + hyphens, no leading/trailing hyphen"
        )
    tier = config.get("tier", "")
    if tier and tier not in _VALID_TIERS:
        errors.append(f"Invalid tier '{tier}': must be one of {sorted(_VALID_TIERS)}")
    return errors


def list_customers() -> list[dict]:
    """Return list of all customer configs (excluding _example.yaml)."""
    path = _customers_path()
    if not path.exists():
        return []
    customers = []
    for f in sorted(path.glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        try:
            config = _load_file(f)
            if config:
                customers.append(config)
        except Exception as e:
            logger.warning(f"Failed to load customer config {f.name}: {e}")
    return customers


def get_customer(customer_id: str) -> dict | None:
    """Load a single customer config by ID. Returns None if not found."""
    if not validate_customer_id(customer_id):
        return None
    filepath = _customers_path() / f"{customer_id}.yaml"
    if not filepath.exists():
        return None
    return _load_file(filepath)


def create_customer(config: dict) -> dict:
    """Write a new customer config YAML. Returns the written config.

    Raises ValueError on validation failure or if customer already exists.
    """
    errors = validate_config(config)
    if errors:
        raise ValueError(f"Invalid config: {'; '.join(errors)}")

    customer_id = config["customer_id"]
    filepath = _customers_path() / f"{customer_id}.yaml"
    if filepath.exists():
        raise ValueError(f"Customer '{customer_id}' already exists")

    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Apply defaults
    config.setdefault("bigquery_dataset", f"glasshood_{customer_id.replace('-', '_')}")
    config.setdefault("gcs_archive_bucket", f"glasshood-archive-{customer_id}")
    config.setdefault("retention_days", 365)
    config.setdefault("monitored_systems", [])
    config.setdefault("alert_overrides", {})
    config.setdefault("features", {
        "ai_analysis": True,
        "compliance_reports": True,
        "servicenow_integration": False,
        "cve_scanning": True,
    })

    with open(filepath, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Created customer config: {customer_id}")
    return config


def delete_customer(customer_id: str) -> bool:
    """Delete a customer config file. Returns True if deleted."""
    if not validate_customer_id(customer_id):
        return False
    filepath = _customers_path() / f"{customer_id}.yaml"
    if not filepath.exists():
        return False
    filepath.unlink()
    logger.info(f"Deleted customer config: {customer_id}")
    return True


def _load_file(filepath: Path) -> dict | None:
    """Load and validate a single YAML file."""
    with open(filepath) as f:
        config = yaml.safe_load(f)
    if not config or not isinstance(config, dict):
        return None
    return config
