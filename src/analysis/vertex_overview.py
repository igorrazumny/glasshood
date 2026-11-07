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
_spend: dict = {}  # today's accounting, see refresh_durable_spend
_last_manual = 0.0
_creds = None

# Clause 8: nothing credential-shaped leaves GlassHood. Every payload is sanitised as a whole,
# recursively, before it is serialised: values under sensitive keys are dropped, and strings are
# scrubbed of credential patterns (plain, key=value, and JSON "key": "value" forms).
_SENSITIVE_KEY = re.compile(r"(?i)(pass(word|wd)?|secret|token|api[_-]?key|authori[sz]ation|credential|"
                            r"private[_-]?key|cookie|session|signature|bearer)")
_SECRETS = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+/=\-]+"
    r"|[\"']?(?:pass(?:word|wd)?|secret|token|api[_-]?key|authori[sz]ation|credential|private[_-]?key|cookie)"
    r"[\"']?\s*[=:]\s*[\"']?[^\"'\s,;}&]+"
    r"|sk-[a-z0-9_\-]{16,}|AIza[0-9A-Za-z_\-]{20,}|eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")


_PEM_BLOCK = re.compile(r"-----BEGIN [A-Z0-9 ]*-----.*?(-----END [A-Z0-9 ]*-----|$)", re.S)
# A credential word anywhere in a line, however it is quoted or escaped, or a URL that carries a
# password in its user part (scheme://user:password@host). Such a line is dropped whole.
_CREDENTIAL_WORD = re.compile(r"(?i)(pass(word|wd)|secret|api[_\- ]?key|authori[sz]ation|credential|"
                              r"private[_\- ]?key|cookie|bearer|token\b)")
_URI_USERINFO = re.compile(r"(?i)[a-z][a-z0-9+.\-]*://[^/\s@]*:[^/\s@]*@")


def _credential_line(line: str) -> bool:
    return bool(_SECRETS.search(line) or _CREDENTIAL_WORD.search(line) or _URI_USERINFO.search(line))


def redact(text: str) -> str:
    """Remove credentials from free text. A key block goes whole; any line that carries a
    credential word, pattern or URL password is dropped entirely — its value cannot be told
    from the rest reliably, whatever the quoting or escaping."""
    text = _PEM_BLOCK.sub("[redacted block]", text or "")
    return "\n".join("[redacted line]" if _credential_line(line) else line for line in text.split("\n"))


def sanitize(obj):
    """Recursively drop sensitive keys and scrub strings, keeping the structure."""
    if isinstance(obj, dict):
        return {k: ("[redacted]" if _SENSITIVE_KEY.search(str(k)) else sanitize(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


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
# The daily count must survive restarts. Google itself counts every call and token per model in
# Cloud Monitoring, which GlassHood may read; that is the durable part. Calls made since the last
# read are counted locally. The total never decreases within a day, so Monitoring's few minutes
# of delay cannot hide calls already made. Only GlassHood calls this model in the project, and
# any other caller would only make the cap stricter. If today's usage cannot be read, no call is
# made: the cap fails closed.

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _new_day() -> dict:
    return {"day": _today(), "durable_calls": 0, "durable_in": 0, "durable_out": 0,
            "local_calls": 0, "local_in": 0, "local_out": 0, "durable_read": False,
            "read_error": None, "capped": False}


def _monitoring_today() -> dict:
    """Today's (UTC) calls and tokens for MODEL in PROJECT, from Cloud Monitoring."""
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period = max(60, int((now - midnight).total_seconds()))
    base = {"interval.startTime": midnight.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "interval.endTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "aggregation.alignmentPeriod": f"{period}s", "aggregation.perSeriesAligner": "ALIGN_SUM",
            "aggregation.crossSeriesReducer": "REDUCE_SUM"}
    url = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries"
    sel = f'resource.labels.model_user_id="{MODEL}"'

    def total(metric, group=None):
        params = {**base, "filter": f'metric.type="aiplatform.googleapis.com/publisher/online_serving/{metric}" AND {sel}'}
        if group:
            params["aggregation.groupByFields"] = group
        r = httpx.get(url, params=params, headers=_headers(), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Cloud Monitoring HTTP {r.status_code}")
        out = {}
        for ts in r.json().get("timeSeries", []):
            key = (ts.get("metric", {}).get("labels", {}) or {}).get("type", "all")
            out[key] = out.get(key, 0) + sum(int(p["value"].get("int64Value", 0)) for p in ts.get("points", []))
        return out
    calls = total("model_invocation_count").get("all", 0)
    tokens = total("token_count", "metric.label.type")
    return {"calls": calls, "in": tokens.get("input", 0), "out": tokens.get("output", 0)}


def refresh_durable_spend() -> None:
    """Fold today's Monitoring totals in; never lowers what is already counted."""
    try:
        mon = _monitoring_today()
        err = None
    except Exception as e:
        mon, err = None, f"today's model usage could not be read ({type(e).__name__})"
    with _lock:
        if _spend.get("day") != _today():
            _spend.clear(); _spend.update(_new_day())
        if mon is None:
            # Fail closed on every failed read, not only on a fresh process.
            _spend["read_error"] = err
            _spend["durable_read"] = False
            return
        _spend["durable_calls"] = max(mon["calls"], _spend["durable_calls"] + _spend["local_calls"])
        _spend["durable_in"] = max(mon["in"], _spend["durable_in"] + _spend["local_in"])
        _spend["durable_out"] = max(mon["out"], _spend["durable_out"] + _spend["local_out"])
        _spend.update(local_calls=0, local_in=0, local_out=0, durable_read=True, read_error=None)


def _reserve_call():
    """Count one call against today's cap. Returns None when reserved, else the reason."""
    with _lock:
        if _spend.get("day") != _today():
            _spend.clear(); _spend.update(_new_day())
        if not _spend["durable_read"]:
            return _spend.get("read_error") or "today's model usage has not been read yet"
        if _spend["durable_calls"] + _spend["local_calls"] >= DAILY_CALL_CAP:
            _spend["capped"] = True
            return f"daily cap of {DAILY_CALL_CAP} model calls reached"
        _spend["local_calls"] += 1
        return None


def _record_usage(usage: dict) -> None:
    tin = int(usage.get("promptTokenCount") or 0)
    tout = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
    with _lock:
        _spend["local_in"] += tin
        _spend["local_out"] += tout


def get_spend() -> dict:
    with _lock:
        sp = dict(_spend) if _spend.get("day") == _today() else _new_day()
    tin, tout = sp["durable_in"] + sp["local_in"], sp["durable_out"] + sp["local_out"]
    return {"day": sp["day"], "calls": sp["durable_calls"] + sp["local_calls"],
            "input_tokens": tin, "output_tokens": tout,
            "cost_usd": round(tin / 1e6 * PRICE_IN_PER_M + tout / 1e6 * PRICE_OUT_PER_M, 4),
            "capped": sp["capped"], "usage_read": sp["durable_read"], "read_error": sp["read_error"],
            "daily_call_cap": DAILY_CALL_CAP, "model": MODEL,
            "price_per_m_tokens_usd": {"input": PRICE_IN_PER_M, "output": PRICE_OUT_PER_M}}


class CapReached(Exception):
    pass


# --- Model call ---

def call_model(system_prompt: str, user_text: str, max_tokens: int = 600,
               search: bool = False) -> tuple[str, list]:
    """One Vertex AI generateContent call within today's cap. Returns the answer's text and,
    when a web search was allowed and used, the pages it drew on ([{title, uri}])."""
    refused = _reserve_call()
    if refused:
        raise CapReached(refused)
    host = "aiplatform.googleapis.com" if LOCATION == "global" else f"{LOCATION}-aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{PROJECT}/locations/{LOCATION}"
           f"/publishers/google/models/{MODEL}:generateContent")
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens,
                             "temperature": 0.2},
    }
    if search:
        body["tools"] = [{"googleSearch": {}}]
    r = httpx.post(url, json=body, headers=_headers(), timeout=120 if search else 60)
    if r.status_code != 200:
        raise RuntimeError(f"Vertex AI HTTP {r.status_code}")
    data = r.json()
    _record_usage(data.get("usageMetadata") or {})
    first = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (first.get("content") or {}).get("parts", []))
    grounding = first.get("groundingMetadata") or {}
    # The searches the model made, then the pages it drew on (often absent with a JSON answer)
    sources = [{"query": str(q)[:200]} for q in (grounding.get("webSearchQueries") or [])[:4]]
    sources += [{"title": str(c["web"].get("title", ""))[:200], "uri": str(c["web"].get("uri", ""))}
                for c in (grounding.get("groundingChunks") or [])[:8]
                if isinstance(c, dict) and isinstance(c.get("web"), dict)
                and str(c["web"].get("uri", "")).startswith("https://")]
    return text, sources


def parse_json(text: str):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0]
    s, e = t.find("{"), t.rfind("}") + 1
    return json.loads(t[s:e] if s >= 0 and e > s else t)


def _generate(system_prompt: str, user_text: str) -> dict:
    """One overview call; returns the parsed JSON answer."""
    text, _ = call_model(system_prompt, user_text)
    return _parse(text)


def _parse(text: str) -> dict:
    obj = parse_json(text)

    def strings(items, n):
        return [str(i.get("description", i)) if isinstance(i, dict) else str(i) for i in (items or [])][:n]
    if not isinstance(obj, dict) or not isinstance(obj.get("summary"), str) or not obj["summary"].strip():
        raise ValueError("the model's answer had no summary")
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
        msg = redact(str(e["textPayload"]))
    else:
        jp = sanitize(e.get("jsonPayload") or {})
        msg = jp.get("message") if isinstance(jp.get("message"), str) else json.dumps(jp)
    return f"{e.get('timestamp', '')[:19]} {e.get('severity', 'DEFAULT')} {str(msg)[:LINE_CHARS]}"


def _log_lines(log_filter: str, warn_n: int, sample_n: int, project: str = "",
               since_s: int = None) -> list:
    """Recent warning/error lines plus a small sample of other lines, newest first."""
    since = (datetime.now(timezone.utc) - timedelta(seconds=since_s or INTERVAL_S)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = f'timestamp>="{since}"' + (f" AND ({log_filter})" if log_filter else "")
    out = []
    for flt, n in ((f"{base} AND severity>=WARNING", warn_n), (f"{base} AND severity<WARNING", sample_n)):
        if n <= 0:
            continue
        # Errors (unreachable API, credential refresh) propagate to the overview's own error boundary.
        r = httpx.post("https://logging.googleapis.com/v2/entries:list", headers=_headers(), timeout=30,
                       json={"resourceNames": [f"projects/{project or PROJECT}"], "filter": flt,
                             "orderBy": "timestamp desc", "pageSize": n})
        if r.status_code != 200:
            raise RuntimeError(f"Cloud Logging HTTP {r.status_code}")
        out += [_entry_text(e) for e in r.json().get("entries", [])]
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


def _outside_products() -> set:
    try:
        from src.api.routes.manifests import _load_manifests
        return {m.get("product") for m in _load_manifests() if m.get("kind") == "outside_view"}
    except Exception:
        return set()


def _walk_parts(topology: dict):
    """(record, log filter) for every top-level node and every nested child. Boxes of a
    public system's outside view are left out: their state is the provider's own, and an
    AI call per box would cost hundreds of calls for nothing new (REQ-GHA-036)."""
    filters, labels = _manifest_info()
    outside = _outside_products()
    for n in topology.get("nodes", []):
        if outside and n.get("project") in outside:
            continue
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


def _failure(e: Exception) -> str:
    return str(e) if isinstance(e, CapReached) else f"overview could not be written ({type(e).__name__}: {str(e)[:120]})"


def run_system(topology: dict) -> None:
    global _system
    try:
        parts = [rec for rec, _ in _walk_parts(topology)]
        payload = sanitize({"overall_status": topology.get("overall_status"), "parts": parts,
                            "recent_logs": _log_lines("", SYSTEM_WARN_LINES, SYSTEM_SAMPLE_LINES)})
        result = _generate(SYSTEM_PROMPT, json.dumps(payload, default=str))
        with _lock:
            _system = _now_entry(result)
    except Exception as e:
        why = _failure(e)
        logger.warning(f"system overview failed: {why}")
        with _lock:
            _system = _keep_last_good(_system, why)


def _run_part(rec: dict, log_filter: str, edges: list) -> None:
    pid = rec["id"]
    try:
        links = [f"-> {e.get('target')}" for e in edges if e.get("source") == pid] + \
                [f"<- {e.get('source')}" for e in edges if e.get("target") == pid]
        payload = sanitize({"part": rec, "connections": links[:20],
                            "recent_logs": _log_lines(log_filter, PART_WARN_LINES, PART_SAMPLE_LINES) if log_filter else []})
        result = _generate(PART_PROMPT, json.dumps(payload, default=str))
        with _lock:
            _parts[pid] = _now_entry(result)
    except Exception as e:
        why = _failure(e)
        logger.warning(f"part overview failed for {pid}: {why}")
        with _lock:
            _parts[pid] = _keep_last_good(_parts.get(pid), why)


def run_all(topology: dict) -> None:
    refresh_durable_spend()
    run_system(topology)
    edges = topology.get("edges", [])
    failed = 0
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="overview") as ex:
        futures = [ex.submit(_run_part, rec, flt, edges) for rec, flt in _walk_parts(topology)]
        for f in futures:
            try:
                f.result()
            except Exception as e:  # _run_part records its own failures; this is a last resort
                failed += 1
                logger.error(f"part overview worker failed: {e}")
    logger.info(f"AI overviews written: system + {len(futures) - failed} parts; spend today {get_spend()}")


def _with_staleness(entry: dict) -> dict:
    out = dict(entry or {})
    ts = out.get("analyzed_at")
    out["stale"] = (ts is None) or (time.time() - ts > INTERVAL_S)
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
    """Seconds until a person may ask again (0 = now). Display only — see reserve_manual_refresh."""
    return max(0, int(MANUAL_COOLDOWN_S - (time.time() - _last_manual)))


def reserve_manual_refresh() -> int:
    """Clause 4, enforced: atomically take the ten-minute slot. Returns 0 when taken, else the wait."""
    global _last_manual
    with _lock:
        wait = max(0, int(MANUAL_COOLDOWN_S - (time.time() - _last_manual)))
        if wait == 0:
            _last_manual = time.time()
        return wait


def manual_refresh(topology: dict) -> None:
    refresh_durable_spend()
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
        try:  # REQ-GHA-029 clause 1: the AI log review, on the same 3-hour beat
            from src.analysis import ai_review
            ai_review.run(get_topology_fn())
        except Exception as e:
            logger.error(f"AI log review error: {e}")
        if stop.wait(INTERVAL_S):
            break
