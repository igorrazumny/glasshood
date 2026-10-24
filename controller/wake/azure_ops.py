# File: controller/wake/azure_ops.py
# Purpose: REQ-GHA-018 — the Azure side effects, each one small and idempotent:
# the container app's ingress restriction and revision state (ARM), the wake queue
# (Storage), and the app's health. Every ARM request has a hard 30 s client timeout.

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from .core import SCAN_VISIBILITY, Actual, QueueView, queue_plan

ARM = "https://management.azure.com"
API_VERSION = "2024-03-01"
CLIENT_TIMEOUT = 30.0
HEALTH_TIMEOUT = 3.0
RESTRICTION = {"name": "asleep", "ipAddressRange": "127.0.0.1/32", "action": "Allow",
               "description": "REQ-GHA-018: asleep, refuse all outside traffic"}
SCAN_BATCHES = 4          # up to 128 messages per scan, all decided within one visibility


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
        """Succeeded | Failed | Canceled, or any other value while still pending (the
        ARM async-operation contract allows provider-specific pending states)."""
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
    def put_message(self, generation: int) -> None:
        self._queue.send_message(json.dumps({"generation": generation}), time_to_live=-1)

    def scan_queue(self, read_intent, now: float) -> QueueView:
        """One fresh-receipt scan (design v6): receive every visible message (each now
        invisible for SCAN_VISIBILITY s), re-read the intent, then decide each message
        once with the receipt just returned: delete it, or make it visible again at
        once. Receipts are never stored. A 404 makes the scan unclean (the next scan
        decides afresh); it is never read as "empty"."""
        from azure.core.exceptions import ResourceNotFoundError
        received, complete = [], False
        for _ in range(SCAN_BATCHES):
            batch = list(self._queue.receive_messages(messages_per_page=32, max_messages=32,
                                                      visibility_timeout=SCAN_VISIBILITY))
            received += batch
            if len(batch) < 32:
                complete = True
                break
        desired, g = read_intent()
        gens = [_generation(m.content) for m in received]
        view = QueueView(desired=desired, generation=g, at=now, clean=complete)
        for m, x, delete in zip(received, gens, queue_plan(desired, g, gens)):
            try:
                if delete:
                    self._queue.delete_message(m.id, m.pop_receipt)
                    continue
                self._queue.update_message(m.id, m.pop_receipt, visibility_timeout=0)
            except ResourceNotFoundError:
                view.clean = False
                continue
            if x == g:
                view.current += 1
            elif x < g:
                view.older += 1
            else:
                view.newer += 1
        view.approx = self._queue.get_queue_properties().approximate_message_count
        return view


def _generation(content: str) -> int:
    try:
        return int(json.loads(content)["generation"])
    except (ValueError, KeyError, TypeError):
        return -1                       # unreadable: older than any intent
