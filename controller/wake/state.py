# File: controller/wake/state.py
# Purpose: REQ-GHA-018 — the one state entity (intent + reconciler control fields)
# and the event record. Every write is conditional on the ETag read with it, so a
# decision based on older state never overwrites newer state.

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, fields
from typing import Callable, Protocol

from .core import Intent

PARTITION, ROW = "state", "main"


class Conflict(Exception):
    """The entity changed since it was read."""


class Store(Protocol):
    def read(self) -> tuple[dict, str]: ...
    def write(self, entity: dict, etag: str) -> str: ...
    def record(self, kind: str, detail: dict) -> None: ...


def intent_of(entity: dict) -> Intent:
    names = {f.name for f in fields(Intent)}
    return Intent(**{k: v for k, v in entity.items() if k in names})


def control_of(entity: dict) -> dict:
    return {"epoch": int(entity.get("epoch", 0)), "op": json.loads(entity.get("op") or "null")}


def entity_of(intent: Intent, control: dict) -> dict:
    return {**asdict(intent), "epoch": control["epoch"], "op": json.dumps(control["op"])}


def update_intent(store: Store, change: Callable[[Intent], Intent], tries: int = 10) -> Intent:
    """Apply an intent change with a conditional write, retrying on conflict."""
    for _ in range(tries):
        entity, etag = store.read()
        before = intent_of(entity)
        after = change(before)
        if after == before:
            return before
        try:
            store.write(entity_of(after, control_of(entity)), etag)
            return after
        except Conflict:
            continue
    raise Conflict("state kept changing")


class TableStore:
    """Azure Table storage implementation."""

    def __init__(self, service, state_table: str = "wakestate", events_table: str = "wakeevents"):
        from azure.core import MatchConditions
        self._mc = MatchConditions
        self._state = service.get_table_client(state_table)
        self._events = service.get_table_client(events_table)

    def read(self) -> tuple[dict, str]:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            e = self._state.get_entity(PARTITION, ROW)
        except ResourceNotFoundError:
            self._state.create_entity({"PartitionKey": PARTITION, "RowKey": ROW,
                                       **entity_of(Intent(), {"epoch": 0, "op": None})})
            e = self._state.get_entity(PARTITION, ROW)
        etag = e.metadata["etag"]
        return {k: v for k, v in e.items() if k not in ("PartitionKey", "RowKey")}, etag

    def write(self, entity: dict, etag: str) -> str:
        from azure.core.exceptions import ResourceModifiedError
        from azure.data.tables import UpdateMode
        try:
            meta = self._state.update_entity(
                {"PartitionKey": PARTITION, "RowKey": ROW, **entity},
                mode=UpdateMode.REPLACE, etag=etag, match_condition=self._mc.IfNotModified)
        except ResourceModifiedError as e:
            raise Conflict(str(e))
        return meta["etag"]

    def record(self, kind: str, detail: dict) -> None:
        now = time.time()
        self._events.create_entity({
            "PartitionKey": time.strftime("%Y-%m", time.gmtime(now)),
            "RowKey": f"{9999999999 - int(now):010d}-{secrets.token_hex(4)}",
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "kind": kind, "detail": json.dumps(detail)[:30000],
        })

    def recent_events(self, limit: int = 20) -> list[dict]:
        month = time.strftime("%Y-%m", time.gmtime())
        rows = self._events.query_entities(f"PartitionKey eq '{month}'", results_per_page=limit)
        out = []
        for r in rows:
            out.append({"at": r["at"], "kind": r["kind"], "detail": json.loads(r["detail"])})
            if len(out) >= limit:
                break
        return out
