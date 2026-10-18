# File: controller/wake/azure_ops.py
# Purpose: REQ-GHA-018 — the Azure side effects, each one small and idempotent:
# the container app's ingress restriction and revision state (ARM), the wake queue
# (Storage), and the app's health. Every ARM request has a hard 30 s client timeout.

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from .core import Actual

ARM = "https://management.azure.com"
API_VERSION = "2024-03-01"
CLIENT_TIMEOUT = 30.0
HEALTH_TIMEOUT = 3.0
RESTRICTION = {"name": "asleep", "ipAddressRange": "127.0.0.1/32", "action": "Allow",
               "description": "REQ-GHA-018: asleep, refuse all outside traffic"}
SCAN_VISIBILITY = 30


@dataclass
class OpHandle:
    """An accepted ARM operation: where to ask about it until it is terminal."""
    url: str | None       # None when ARM finished it synchronously


class AzureOps:
    def __init__(self, credential, app_id: str, fqdn: str, queue_client):
        self._cred = credential
        self._app = app_id               # /subscriptions/.../containerApps/glasshood
        self._fqdn = fqdn
        self._queue = queue_client

    # ---- ARM plumbing ----
    def _headers(self) -> dict:
        token = self._cred.get_token("https://management.azure.com/.default").token
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _get(self, path: str) -> dict:
        r = httpx.get(f"{ARM}{path}", params={"api-version": API_VERSION},
                      headers=self._headers(), timeout=CLIENT_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _write(self, method: str, path: str, body: dict | None = None) -> OpHandle:
        r = httpx.request(method, f"{ARM}{path}", params={"api-version": API_VERSION},
                          headers=self._headers(), timeout=CLIENT_TIMEOUT,
                          content=json.dumps(body) if body is not None else None)
        r.raise_for_status()
        if r.status_code in (201, 202):
            return OpHandle(r.headers.get("Azure-AsyncOperation") or r.headers.get("Location"))
        return OpHandle(None)

    def op_status(self, url: str) -> str:
        """InProgress | Succeeded | Failed | Canceled (ARM async-operation contract)."""
        r = httpx.get(url, headers=self._headers(), timeout=CLIENT_TIMEOUT)
        if r.status_code == 202:
            return "InProgress"
        r.raise_for_status()
        body = r.json() if r.content else {}
        return body.get("status") or body.get("properties", {}).get("provisioningState") or "Succeeded"

    def app(self) -> dict:
        return self._get(self._app)

    def provisioning_state(self) -> str:
        return self.app()["properties"].get("provisioningState", "Succeeded")

    # ---- reads ----
    def read_actual(self) -> tuple[Actual, str]:
        app = self.app()["properties"]
        revision = app["latestRevisionName"]
        rev = self._get(f"{self._app}/revisions/{revision}")["properties"]
        # Stopped replicas stay listed for a while as "NotRunning"; they do not count.
        replicas = [r for r in self._get(f"{self._app}/revisions/{revision}/replicas").get("value", [])
                    if r.get("properties", {}).get("runningState") != "NotRunning"]
        restrictions = (app["configuration"].get("ingress") or {}).get("ipSecurityRestrictions") or []
        restricted = any(r.get("name") == RESTRICTION["name"] for r in restrictions)
        healthy = (not restricted) and bool(replicas) and self.health()
        return Actual(
            ingress_restricted=restricted, revision_active=bool(rev.get("active")),
            replicas=len(replicas), healthy=healthy,
            queue_generations=self.peek_generations(),
        ), revision

    def health(self) -> bool:
        try:
            return httpx.get(f"https://{self._fqdn}/api/health", timeout=HEALTH_TIMEOUT).status_code == 200
        except httpx.HTTPError:
            return False

    # ---- ARM writes ----
    def set_restricted(self, restricted: bool) -> OpHandle:
        ingress = self.app()["properties"]["configuration"]["ingress"]
        others = [r for r in (ingress.get("ipSecurityRestrictions") or [])
                  if r.get("name") != RESTRICTION["name"]]
        ingress["ipSecurityRestrictions"] = others + ([RESTRICTION] if restricted else [])
        return self._write("PATCH", self._app,
                           {"properties": {"configuration": {"ingress": ingress}}})

    def set_revision_active(self, revision: str, active: bool) -> OpHandle:
        verb = "activate" if active else "deactivate"
        return self._write("POST", f"{self._app}/revisions/{revision}/{verb}")

    # ---- the wake queue ----
    def peek_generations(self) -> list[int]:
        """Generations of the visible messages (peek: no receipts, used only to decide)."""
        return [int(json.loads(m.content)["generation"])
                for m in self._queue.peek_messages(max_messages=32)]

    def put_message(self, generation: int) -> None:
        self._queue.send_message(json.dumps({"generation": generation}), time_to_live=-1)

    def scan_and_delete(self, should_delete) -> int:
        """Receive messages with fresh receipts and decide each with them, once: delete
        if should_delete(generation), otherwise make it visible again at once. Receipts
        are never stored. Returns how many were deleted."""
        from azure.core.exceptions import ResourceNotFoundError
        deleted = 0
        for m in self._queue.receive_messages(messages_per_page=32, visibility_timeout=SCAN_VISIBILITY,
                                              max_messages=32):
            try:
                if should_delete(int(json.loads(m.content)["generation"])):
                    self._queue.delete_message(m.id, m.pop_receipt)
                    deleted += 1
                else:
                    self._queue.update_message(m.id, m.pop_receipt, visibility_timeout=0)
            except ResourceNotFoundError:
                pass     # receipt no longer valid: the next scan decides afresh, never "empty"
        return deleted
