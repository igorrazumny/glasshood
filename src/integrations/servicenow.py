# File: src/integrations/servicenow.py
# Purpose: ServiceNow Table API client — incidents, changes, bi-directional sync
#
# Auth: Basic auth (user/password).
# Pattern: httpx + module globals + deque audit trail (mirrors cve_scanner.py).
# Graceful degradation: all public functions return valid results when SNOW unavailable.

import collections
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

# ALCOA+ audit trail
_audit_log: collections.deque = collections.deque(maxlen=500)

_CONFIG_PATH = "config/integrations/servicenow.yaml"


def _load_config() -> dict:
    """Load ServiceNow config from YAML. Returns empty dict on error."""
    p = Path(_CONFIG_PATH)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        return data.get("servicenow", {})
    except Exception as e:
        logger.error(f"Failed to load ServiceNow config: {e}")
        return {}


class ServiceNowClient:
    """Thin wrapper around ServiceNow Table API.

    Fully injectable for testing — pass instance_url="" to get a no-op client.
    All methods return empty lists / None / False on connection failure.
    """

    def __init__(self, instance_url: str, username: str, password: str,
                 timeout: int = 30):
        self.base_url = instance_url.rstrip("/") if instance_url else ""
        self._username = username
        self._password = password
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.base_url and self._username)

    def _get_table(self, table: str, params: dict) -> list[dict]:
        """Query a ServiceNow table. Returns [] on any error."""
        if not self.available:
            return []
        url = f"{self.base_url}/api/now/table/{table}"
        try:
            resp = httpx.get(
                url, params=params, timeout=self._timeout,
                auth=(self._username, self._password),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json().get("result", [])
        except Exception as e:
            logger.warning(f"ServiceNow GET {table} failed: {e}")
            return []

    def fetch_incidents(self, since_iso: str, fields: list[str],
                        limit: int = 100) -> list[dict]:
        """Fetch incidents opened since given ISO timestamp."""
        params = {
            "sysparm_query": f"opened_at>={since_iso}^ORDERBYDESCopened_at",
            "sysparm_fields": ",".join(fields),
            "sysparm_limit": limit,
        }
        return self._get_table("incident", params)

    def fetch_changes(self, since_iso: str, fields: list[str],
                      limit: int = 100) -> list[dict]:
        """Fetch change requests with start_date since given timestamp."""
        params = {
            "sysparm_query": f"start_date>={since_iso}^ORDERBYDESCstart_date",
            "sysparm_fields": ",".join(fields),
            "sysparm_limit": limit,
        }
        return self._get_table("change_request", params)

    def create_incident(self, payload: dict) -> Optional[str]:
        """Create an incident. Returns sys_id on success, None on failure."""
        if not self.available:
            return None
        url = f"{self.base_url}/api/now/table/incident"
        try:
            resp = httpx.post(
                url, json=payload, timeout=self._timeout,
                auth=(self._username, self._password),
                headers={"Accept": "application/json",
                          "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            sys_id = resp.json().get("result", {}).get("sys_id")
            if sys_id:
                _audit_log.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": "create_incident",
                    "snow_sys_id": sys_id,
                })
            return sys_id
        except Exception as e:
            logger.warning(f"ServiceNow create_incident failed: {e}")
            return None

    def resolve_incident(self, sys_id: str, close_notes: str) -> bool:
        """Set incident state to Resolved (state=6). Returns True on success."""
        if not self.available:
            return False
        url = f"{self.base_url}/api/now/table/incident/{sys_id}"
        try:
            resp = httpx.patch(
                url,
                json={"state": "6", "close_notes": close_notes,
                      "close_code": "Solved (Permanently)"},
                timeout=self._timeout,
                auth=(self._username, self._password),
                headers={"Accept": "application/json",
                          "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            _audit_log.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "resolve_incident",
                "snow_sys_id": sys_id,
            })
            return True
        except Exception as e:
            logger.warning(f"ServiceNow resolve_incident {sys_id} failed: {e}")
            return False


def get_audit_log() -> list[dict]:
    """Return ALCOA+ audit trail entries (most recent first)."""
    return list(reversed(_audit_log))
