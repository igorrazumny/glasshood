# File: src/analysis/vertex_overview.py
# Purpose: REQ-GHA-024 — brief AI overviews of the whole system and of each part.
# Gemini Flash-Lite on Vertex AI in the monitored project, reached with GlassHood's key-less
# identity. Written at start, then every OVERVIEW_INTERVAL_S; a daily cap on model calls
# bounds the spend. Input is small: status, check result, metrics and selected log lines.
# The model's text is returned as plain data and never triggers any action.

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from src.config.settings import GCP_PROJECT_ID

logger = logging.getLogger(__name__)

MODEL = os.getenv("OVERVIEW_MODEL", "gemini-3.1-flash-lite")
LOCATION = os.getenv("OVERVIEW_LOCATION", "global")
PROJECT = os.getenv("OVERVIEW_PROJECT", GCP_PROJECT_ID)
INTERVAL_S = int(os.getenv("OVERVIEW_INTERVAL_S", str(3 * 3600)))
MANUAL_COOLDOWN_S = 600
DAILY_CALL_CAP = int(os.getenv("OVERVIEW_DAILY_CALL_CAP", "1200"))  # about $2/day at list price
PRICE_IN_PER_M = float(os.getenv("OVERVIEW_PRICE_IN_PER_M", "0.25"))
PRICE_OUT_PER_M = float(os.getenv("OVERVIEW_PRICE_OUT_PER_M", "1.50"))
SYSTEM_WARN_LINES, SYSTEM_SAMPLE_LINES = 60, 20
PART_WARN_LINES, PART_SAMPLE_LINES = 30, 10
LINE_CHARS = 300

SYSTEM_PROMPT = """You write a short health overview of a running cloud system for a business reader.
You get every part with its status, its check result and metrics, plus recent log lines.
Statuses: healthy; degraded; error; "not checked" means an outside service the monitor cannot check
(never call it a problem for that reason alone). Findings in the alerts are configuration notes. Refer to parts by their label, never by their id.
Answer in JSON only:
{"score": 1-10, "summary": "one or two plain sentences on the overall state",
 "issues": ["what needs attention, plain words, empty if nothing"],
 "recommendations": ["at most three short next steps, empty if none"]}"""

PART_PROMPT = """You write a short overview of ONE part of a running cloud system for a business reader.
You get the part's status, check result, metrics, its place in the system and recent log lines.
"not checked" means the monitor cannot check this outside service; say so plainly.
Refer to the part by its label, never by its id.
Answer in JSON only:
{"score": 1-10, "summary": "one or two plain sentences",
 "issues": ["what needs attention, empty if nothing"], "recommendations": ["at most two, empty if none"]}"""

_lock = threading.Lock()
_system: dict = {}
_parts: dict = {}          # part id -> overview
_spend = {"day": "", "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "capped": False}
_last_manual = 0.0
_creds = None

# Redact anything shaped like a credential before a log line leaves GlassHood (clause 8).
_SECRETS = re.compile(
    r"(?i)(bearer\s+[a-z0-9._\-]+|(?:api[_-]?key|token|secret|password|passwd|authorization)\s*[=:]\s*\S+"
    r"|sk-[a-z0-9]{16,}|AIza[0-9A-Za-z_\-]{20,}|eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+)")


def redact(text: str) -> str:
    return _SECRETS.sub("[redacted]", text or "")


def _token() -> str:
    global _creds
    import google.auth
    import google.auth.transport.requests
    if _creds is None:
        _creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not _creds.valid:
        _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


def _headers() -> dict:
    h = {"Authorization": f"Bearer {_token()}"}
    quota = getattr(_creds, "quota_project_id", None)
    if quota:
        h["x-goog-user-project"] = quota
    return h


# --- Spend (clause 6) ---

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _reserve_call() -> bool:
    """Count one call against today's cap; False when the cap is reached."""
    with _lock:
        if _spend["day"] != _today():
            _spend.update(day=_today(), calls=0, input_tokens=0, output_tokens=0, cost_usd=0.0, capped=False)
        if _spend["calls"] >= DAILY_CALL_CAP:
            _spend["capped"] = True
            return False
        _spend["calls"] += 1
        return True


def _record_usage(usage: dict) -> None:
    tin = int(usage.get("promptTokenCount") or 0)
    tout = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
    with _lock:
        _spend["input_tokens"] += tin
        _spend["output_tokens"] += tout
        _spend["cost_usd"] = round(_spend["input_tokens"] / 1e6 * PRICE_IN_PER_M
                                   + _spend["output_tokens"] / 1e6 * PRICE_OUT_PER_M, 4)


def get_spend() -> dict:
    with _lock:
        return {**_spend, "daily_call_cap": DAILY_CALL_CAP, "model": MODEL,
                "price_per_m_tokens_usd": {"input": PRICE_IN_PER_M, "output": PRICE_OUT_PER_M}}


class CapReached(Exception):
    pass


# --- Model call ---

def _generate(system_prompt: str, user_text: str) -> dict:
    """One Vertex AI generateContent call; returns the parsed JSON answer."""
    if not _reserve_call():
        raise CapReached(f"daily cap of {DAILY_CALL_CAP} model calls reached")
    host = "aiplatform.googleapis.com" if LOCATION == "global" else f"{LOCATION}-aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{PROJECT}/locations/{LOCATION}"
           f"/publishers/google/models/{MODEL}:generateContent")
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 600, "temperature": 0.2},
    }
    r = httpx.post(url, json=body, headers=_headers(), timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Vertex AI HTTP {r.status_code}")
    data = r.json()
    _record_usage(data.get("usageMetadata") or {})
    text = "".join(p.get("text", "") for c in data.get("candidates", [])[:1]
                   for p in (c.get("content") or {}).get("parts", []))
    return _parse(text)


def _parse(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0]
    s, e = t.find("{"), t.rfind("}") + 1
    obj = json.loads(t[s:e] if s >= 0 and e > s else t)

    def strings(items, n):
        return [str(i.get("description", i)) if isinstance(i, dict) else str(i) for i in (items or [])][:n]
    score = obj.get("score")
    return {
        "score": score if isinstance(score, (int, float)) and 1 <= score <= 10 else None,
        "summary": str(obj.get("summary", ""))[:600],
        "issues": strings(obj.get("issues"), 5),
        "recommendations": strings(obj.get("recommendations"), 3),
    }


# --- Logs (clause 5: small input) ---

def _entry_text(e: dict) -> str:
    if e.get("textPayload"):
        msg = e["textPayload"]
    else:
        jp = e.get("jsonPayload") or {}
        msg = jp.get("message") or json.dumps(jp)[:LINE_CHARS]
    return f"{e.get('timestamp', '')[:19]} {e.get('severity', 'DEFAULT')} {redact(str(msg))[:LINE_CHARS]}"


def _log_lines(log_filter: str, warn_n: int, sample_n: int, project: str = "") -> list:
    """Recent warning/error lines plus a small sample of other lines, newest first."""
    since = (datetime.now(timezone.utc) - timedelta(seconds=INTERVAL_S)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = f'timestamp>="{since}"' + (f" AND ({log_filter})" if log_filter else "")
    out = []
    for flt, n in ((f"{base} AND severity>=WARNING", warn_n), (f"{base} AND severity<WARNING", sample_n)):
        try:
            r = httpx.post("https://logging.googleapis.com/v2/entries:list", headers=_headers(), timeout=30,
                           json={"resourceNames": [f"projects/{project or PROJECT}"], "filter": flt,
                                 "orderBy": "timestamp desc", "pageSize": n})
            if r.status_code == 200:
                out += [_entry_text(e) for e in r.json().get("entries", [])]
        except httpx.HTTPError as e:
            logger.debug(f"log read failed: {e}")
    return out


# --- Parts ---

def _part_record(node: dict, parent: dict = None) -> dict:
    m = node.get("metrics") or {}
    return {
        "id": node.get("id"), "label": node.get("label"), "type": node.get("type"),
        "status": node.get("status"),
        "check": m.get("_check_description") or node.get("check_description"),
        "metrics": {k: v for k, v in m.items() if not k.startswith("_")},
        "inside": parent.get("label") if parent else None,
    }


def _manifest_info():
    """(part id -> first log filter, part id -> label) from the manifests (top-level nodes)."""
    filters, labels = {}, {}
    try:
        from src.api.routes.manifests import _load_manifests
        for m in _load_manifests():
            for n in m.get("nodes", []):
                if not n.get("id"):
                    continue
                if n.get("label"):
                    labels[n["id"]] = n["label"]
                logs = ((n.get("monitoring") or {}).get("logs") or [])
                if logs and logs[0].get("filter"):
                    filters[n["id"]] = logs[0]["filter"]
    except Exception as e:
        logger.debug(f"manifest info unavailable: {e}")
    return filters, labels


def _walk_parts(topology: dict):
    """(record, log filter) for every top-level node and every nested child."""
    filters, labels = _manifest_info()
    for n in topology.get("nodes", []):
        logs = ((n.get("monitoring") or {}).get("logs") or [])
        parent_filter = filters.get((n.get("metrics") or {}).get("_parent") or "", "")
        rec = _part_record(n)
        rec["label"] = labels.get(n.get("id")) or rec["label"]  # the name the reader sees on the canvas
        yield rec, (logs[0].get("filter") if logs else filters.get(n.get("id"), parent_filter))

        def kids(children, parent):
            for c in children or []:
                if isinstance(c, dict) and c.get("id"):
                    cl = ((c.get("monitoring") or {}).get("logs") or [])
                    yield _part_record(c, parent), (cl[0].get("filter") if cl else "")
                    yield from kids(c.get("children"), c)
        yield from kids(n.get("children"), n)


def _now_entry(result: dict, error: str = None) -> dict:
    return {**result, "analyzed_at": time.time(), "timestamp": time.time(), "model": MODEL,
            "stale": False, "error": error}


def _keep_last_good(previous: dict, error: str) -> dict:
    """Clause 7: say why, keep the last good overview with its age."""
    if previous and previous.get("summary") and not previous.get("error_only"):
        return {**previous, "error": error}
    return {"score": None, "summary": "", "issues": [], "recommendations": [], "analyzed_at": None,
            "timestamp": None, "model": MODEL, "stale": True, "error": error, "error_only": True}


def run_system(topology: dict, alerts: list = None) -> None:
    global _system
    parts = [rec for rec, _ in _walk_parts(topology)]
    text = json.dumps({
        "overall_status": topology.get("overall_status"),
        "parts": parts,
        "alerts": [a.get("message") for a in (alerts or topology.get("alerts") or [])][:30],
        "recent_logs": _log_lines("", SYSTEM_WARN_LINES, SYSTEM_SAMPLE_LINES),
    }, default=str)
    try:
        result = _generate(SYSTEM_PROMPT, text)
        with _lock:
            _system = _now_entry(result)
    except Exception as e:
        why = str(e) if isinstance(e, CapReached) else f"overview could not be written ({str(e)[:120]})"
        logger.warning(f"system overview failed: {why}")
        with _lock:
            _system = _keep_last_good(_system, why)


def _run_part(rec: dict, log_filter: str, edges: list) -> None:
    pid = rec["id"]
    links = [f"-> {e.get('target')}" for e in edges if e.get("source") == pid] + \
            [f"<- {e.get('source')}" for e in edges if e.get("target") == pid]
    text = json.dumps({"part": rec, "connections": links[:20],
                       "recent_logs": _log_lines(log_filter, PART_WARN_LINES, PART_SAMPLE_LINES) if log_filter else []},
                      default=str)
    try:
        result = _generate(PART_PROMPT, text)
        with _lock:
            _parts[pid] = _now_entry(result)
    except Exception as e:
        why = str(e) if isinstance(e, CapReached) else f"overview could not be written ({str(e)[:120]})"
        with _lock:
            _parts[pid] = _keep_last_good(_parts.get(pid), why)


def run_all(topology: dict) -> None:
    run_system(topology)
    edges = topology.get("edges", [])
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="overview") as ex:
        for rec, flt in _walk_parts(topology):
            ex.submit(_run_part, rec, flt, edges)
    logger.info(f"AI overviews written: system + {len(_parts)} parts; spend today {get_spend()}")


def _with_staleness(entry: dict) -> dict:
    out = dict(entry or {})
    ts = out.get("analyzed_at")
    out["stale"] = (ts is None) or (time.time() - ts > INTERVAL_S + 600)
    out["interval_s"] = INTERVAL_S
    return out


def get_system() -> dict:
    with _lock:
        return _with_staleness(_system)


def get_part(part_id: str):
    with _lock:
        entry = _parts.get(part_id)
    return _with_staleness(entry) if entry else None


def manual_refresh_allowed() -> int:
    """Seconds until a person may ask again (0 = now). Clause 4."""
    return max(0, int(MANUAL_COOLDOWN_S - (time.time() - _last_manual)))


def manual_refresh(topology: dict) -> None:
    global _last_manual
    _last_manual = time.time()
    run_system(topology)


def overview_loop(get_topology_fn, ready_fn=None):
    """Clause 4: first overviews as soon as the parts are known, then every INTERVAL_S."""
    stop = threading.Event()
    for _ in range(60):  # wait for the first poll of the parts, at most ~5 minutes
        if ready_fn is None or ready_fn():
            break
        stop.wait(5)
    while True:
        try:
            run_all(get_topology_fn())
        except Exception as e:
            logger.error(f"overview loop error: {e}")
        if stop.wait(INTERVAL_S):
            break
