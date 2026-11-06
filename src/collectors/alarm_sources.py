# File: src/collectors/alarm_sources.py
# Purpose: Where the alarm collectors read, and which part each alarm belongs to (REQ-GHA-027)
#
# An environment in a manifest declares, for each signal, the part on the canvas it
# concerns and a filter that selects only that system's own resources:
#
#   alarm_sources:
#     errors:         {part, project, filter}   # Cloud Logging filter of real failures
#     load_balancer:  {part, project, filter}   # Cloud Monitoring filter (LB metrics)
#     cpu:            {part, project, filter}   # Cloud Monitoring filter (VM CPU)
#
# A signal with no declaration is not read at all: there is no project-wide default.
#
# REQ-GHA-028: the environment also lists its own alarms (same fields as
# config/rules.yaml, plus `part` and `kind`); GlassHood never expects the monitored
# system to define them.

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

SIGNALS = ("errors", "load_balancer", "cpu")


def _manifest_dir() -> Path:
    from src.api.routes.manifests import MANIFEST_DIR
    return MANIFEST_DIR


def _valid(entry) -> bool:
    return isinstance(entry, dict) and all(isinstance(entry.get(k), str) and entry.get(k)
                                           for k in ("part", "project", "filter"))


def _environments():
    d = _manifest_dir()
    if not d.exists():
        return
    for f in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or {}
        except Exception as e:
            logger.warning(f"alarms: cannot read {f.name}: {e}")
            continue
        envs = data.get("environments") if isinstance(data.get("environments"), list) else [data]
        for env in envs:
            if isinstance(env, dict):
                yield f.name, env


def alarms() -> Optional[list]:
    """REQ-GHA-028: the alarms each system's landscape file defines, with their parts
    and thresholds. None when no landscape file declares any (the general rules file
    then applies); a rule without an id or condition is left out and logged."""
    found, declared = [], False
    for name, env in _environments():
        rules = env.get("alarms")
        if not isinstance(rules, list):
            continue
        declared = True
        for r in rules:
            if isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("condition"), dict):
                found.append(r)
            else:
                logger.warning(f"alarms: invalid entry in {name} left out: {r!r:.120}")
    return found if declared else None


def load() -> dict:
    """{signal: {part, project, filter}} from the first environment that declares
    alarm_sources; an invalid or missing entry is left out (that signal is not read)."""
    for _, env in _environments():
        declared = env.get("alarm_sources")
        if isinstance(declared, dict):
            return {s: dict(declared[s]) for s in SIGNALS if _valid(declared.get(s))}
    return {}
