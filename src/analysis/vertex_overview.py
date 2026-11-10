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

from src.analysis import ai_budget
from src.config.settings import GCP_PROJECT_ID

logger = logging.getLogger(__name__)

# REQ-GHA-024 (amended 2026-11-08): the AI runs on OpenAI with the key from GlassHood's Key
# Vault; Gemini on Vertex stays available by setting AI_PROVIDER=vertex.
PROVIDER = os.getenv("AI_PROVIDER", "vertex").lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")            # overviews (almost all calls)
OPENAI_MODEL_DEEP = os.getenv("OPENAI_MODEL_DEEP", "gpt-5.4-mini")  # AI log review, Investigate deeper
OPENAI_PRICES = {  # USD per million tokens (input, output, cached input), list prices 2026-11
    "gpt-5.4-nano": (0.20, 1.25, 0.02), "gpt-5.4-mini": (0.75, 4.50, 0.075),
}
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")        # answers when OpenAI fails
CLAUDE_PRICES = {"claude-haiku-5-5": (0.10, 0.50, 0.10), "claude-sonnet-5-5": (2.00, 10.00, 0.20),
                 "claude-opus-5-5": (4.00, 20.00, 0.20)}            # USD per million tokens, list prices 2026-11
SEARCH_CALLS_ALLOWANCE, SEARCH_INPUT_ALLOWANCE = 20, 200_000  # most a web-searching call is held at
OPENAI_SEARCH_PRICE = float(os.getenv("OPENAI_SEARCH_PRICE", "0.01"))  # USD per web search call
MODEL = OPENAI_MODEL if PROVIDER == "openai" else os.getenv("OVERVIEW_MODEL", "gemini-3.1-flash-lite")
LOCATION = os.getenv("OVERVIEW_LOCATION", "global")
PROJECT = os.getenv("OVERVIEW_PROJECT", GCP_PROJECT_ID)
INTERVAL_S = int(os.getenv("OVERVIEW_INTERVAL_S", str(3 * 3600)))
MANUAL_COOLDOWN_S = 600
PENDING_SCAN_S = 15
CHANGE_SCAN_S = 120
CONDITIONS = ("normal", "attention", "failing")
DAILY_CALL_CAP = int(os.getenv("OVERVIEW_DAILY_CALL_CAP", "1200"))  # about $2/day at list price
PRICE_IN_PER_M = float(os.getenv("OVERVIEW_PRICE_IN_PER_M", "0.25"))
PRICE_OUT_PER_M = float(os.getenv("OVERVIEW_PRICE_OUT_PER_M", "1.50"))
SYSTEM_WARN_LINES, SYSTEM_SAMPLE_LINES = 60, 20
PART_WARN_LINES, PART_SAMPLE_LINES = 30, 10
LINE_CHARS = 300

SYSTEM_PROMPT = """You write a short health overview of a running cloud system for a business reader.
You get every part with its status, its check result and metrics, plus recent log lines.
Statuses: healthy; degraded; error; "not checked" means the state of that part is unknown
(never call it a problem for that reason alone, and never say it is working). Findings in the alerts are configuration notes.
Weigh what you report by importance: real faults first. A minor observation or configuration note is never a main issue, and one finding is mentioned once, however many parts it touches. The things inside the system are its components: call them so, by their label or function, never by their id.
"condition" is "normal" when nothing needs attention, "attention" when the system works but something needs attention, "failing" when an essential function is not working. It must agree with your summary.
Answer in JSON only:
{"score": 1-10, "condition": "normal, attention or failing", "summary": "one or two plain sentences on the overall state",
 "issues": ["what needs attention, plain words, empty if nothing"],
 "recommendations": ["at most three short next steps, empty if none"]}"""

PART_PROMPT = """You write a short overview of ONE component of a running cloud system for a business reader.
You get the component's status, check result, metrics, its place in the system and recent log lines.
"not checked" means the state of this component is unknown; say so plainly and never say it is working.
Call it a component and refer to it by its label or function, never by its id.
Answer in JSON only:
{"score": 1-10, "summary": "one or two plain sentences",
 "issues": ["what needs attention, empty if nothing"], "recommendations": ["at most two, empty if none"]}"""

# REQ-GHA-036 clause 7: external systems, seen only through what their provider publishes
OUTSIDE_SYSTEM_PROMPT = """You write a short overview of an EXTERNAL service for a business reader whose
organisation depends on it. You only have what the provider publishes on its public status page:
each component's state and last update, and open incidents and maintenance with the provider's updates.
Say what the current state means for people who use this service, what the provider has said, and what
cannot be known from outside. Never invent an internal cause or internal parts; quote or paraphrase the
provider for causes. Refer to components by their published names.
"condition" is "normal" when nothing needs attention, "attention" when the system works but something needs attention, "failing" when an essential function is not working. It must agree with your summary.
Answer in JSON only:
{"score": 1-10, "condition": "normal, attention or failing", "summary": "one or two plain sentences on the service as a whole",
 "issues": ["what a user of this service should know now, empty if nothing"],
 "recommendations": ["at most three short next steps for a team that depends on it, empty if none"]}"""

OUTSIDE_PART_PROMPT = """You write a short analysis of ONE component of an EXTERNAL service for a business
reader. You only have what the provider publishes: this component's state and how long it has been in it,
open incidents or maintenance naming it with the provider's updates, and other components named in the
same incidents. Say what it means for people who use this component, what the provider has said, and what
cannot be known from outside. Never invent an internal cause. Refer to components by their published names.
Answer in JSON only:
{"score": 1-10, "summary": "one or two plain sentences",
 "issues": ["what needs attention, empty if nothing"], "recommendations": ["at most two, empty if none"]}"""

_lock = threading.Lock()
_system: dict = {}
_outside: dict = {}        # product -> overview of that external system
_own: dict = {}            # product -> overview of one of our own systems (REQ-GHA-037)
_own_jobs: dict = {}       # product -> actual assessment execution state
_state_sig: dict = {}      # product -> the part states its saved record was written from (REQ-GHA-040)
_triggered_sig: dict = {}  # product -> the part states that last triggered a new record
_last_round = [0.0]        # when the last full round of evaluations finished
_records_lock = threading.Lock()   # capture and publish together: an older snapshot cannot land last
_records_problem = [None]  # why the evaluations could not be saved, in words
_outside_running: set = set()  # external systems with a record being written right now
_changed: set = set()      # own systems whose parts changed state and await a new record
_outside_sig: dict = {}    # box id -> what its last analysis was written from (rewritten only on change)
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


def _spend_file():
    d = os.getenv("AI_STATE_DIR", "")
    return os.path.join(d, "ai_spend.json") if d else None


class SpendNotSaved(Exception):
    pass


_save_lock = threading.Lock()   # one writer at a time: snapshot, write and replace together


def _file_today() -> dict:
    """Today's (UTC) calls, tokens and cost on OpenAI, from GlassHood's saved count (the
    durable part: OpenAI's own usage needs an admin key GlassHood does not hold). With
    nowhere writable to keep the count, no paid call is made: the cap fails closed."""
    path = _spend_file()
    if not path:
        raise SpendNotSaved("no folder is set up to keep today's AI count (AI_STATE_DIR)")
    folder = os.path.dirname(path)
    if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
        raise SpendNotSaved("the folder that keeps today's AI count is not writable")
    if not os.path.exists(path):
        return {"calls": 0, "in": 0, "out": 0, "cost": 0.0}
    with open(path) as f:
        data = json.load(f)
    if data.get("day") != _today():
        return {"calls": 0, "in": 0, "out": 0, "cost": 0.0}
    return {k: data.get(k, 0) for k in ("calls", "in", "out", "cost")}


def _save_spend_file() -> None:
    """Write today's count. Raises SpendNotSaved, after stopping further paid calls, when it
    cannot be written: an unsaved count would let a restart exceed the cap."""
    import tempfile
    path = _spend_file()
    with _save_lock:
        with _lock:
            snap = {"day": _spend["day"], "calls": _spend["durable_calls"] + _spend["local_calls"],
                    "in": _spend["durable_in"] + _spend["local_in"], "out": _spend["durable_out"] + _spend["local_out"],
                    "cost": round(_spend.get("durable_cost", 0.0) + _spend.get("local_cost", 0.0), 6)}
        try:
            if not path:
                raise OSError("AI_STATE_DIR not set")
            fd, tmp = tempfile.mkstemp(prefix=".ai_spend.", dir=os.path.dirname(path))
            with os.fdopen(fd, "w") as f:
                json.dump(snap, f)
            os.replace(tmp, path)
        except Exception as e:
            why = f"today's AI count could not be saved ({type(e).__name__})"
            logger.warning(f"{why}: no further AI call until it can be")
            with _lock:
                _spend["durable_read"] = False
                _spend["read_error"] = why
            raise SpendNotSaved(why)


def refresh_durable_spend() -> None:
    """Fold today's durable totals in; never lowers what is already counted."""
    try:
        mon = _file_today() if PROVIDER == "openai" else _monitoring_today()
        err = None
    except Exception as e:
        mon, err = None, (str(e) if isinstance(e, SpendNotSaved)
                          else f"today's model usage could not be read ({type(e).__name__})")
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
        _spend["durable_cost"] = max(float(mon.get("cost", 0.0)),
                                     _spend.get("durable_cost", 0.0) + _spend.get("local_cost", 0.0))
        _spend.update(local_calls=0, local_in=0, local_out=0, local_cost=0.0, durable_read=True, read_error=None)


def _reserve_call():
    """Count one call against today's cap. Returns None when reserved, else the reason."""
    with _lock:
        if _spend.get("day") != _today():
            _spend.clear(); _spend.update(_new_day())
        if not _spend["durable_read"]:
            return _spend.get("read_error") or "today's model usage has not been read yet"
        # REQ-GHA-041: on the AI providers the limit is monthly money, not a number of calls
        if PROVIDER != "openai" and _spend["durable_calls"] + _spend["local_calls"] >= DAILY_CALL_CAP:
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


def _price(model: str) -> tuple:
    """REQ-GHA-041: a call whose cost cannot be estimated is not made."""
    prices = {**OPENAI_PRICES, **CLAUDE_PRICES}
    if model not in prices:
        raise RuntimeError(f"no price is known for model {model}")
    return prices[model]


def _reserve(provider: str, model: str, text: str, max_out: int, search: bool = False) -> tuple:
    """REQ-GHA-041: the most this call can cost, saved before it goes out: at most one token per
    byte of input plus framing, the whole output allowance, and an allowance for web searches."""
    pin, pout, _ = _price(model)
    tokens_in = len(text.encode("utf-8")) + 1000 + (SEARCH_INPUT_ALLOWANCE if search else 0)
    return ai_budget.reserve(provider, tokens_in / 1e6 * pin + max_out / 1e6 * pout
                             + (SEARCH_CALLS_ALLOWANCE * OPENAI_SEARCH_PRICE if search else 0))


def _record_openai(model: str, usage: dict, searches: int = 0, reservation: tuple = None) -> None:
    """Tokens and cost of one answer: cached input at its own price, plus web search calls."""
    tin, tout = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    cached = min(tin, int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0))
    pin, pout, pcached = _price(model)
    cost = (tin - cached) / 1e6 * pin + cached / 1e6 * pcached + tout / 1e6 * pout + searches * OPENAI_SEARCH_PRICE
    with _lock:
        _spend["local_in"] += tin
        _spend["local_out"] += tout
        _spend["local_cost"] = _spend.get("local_cost", 0.0) + cost
    if reservation:
        ai_budget.settle(reservation, cost)
    else:
        ai_budget.charge(ai_budget.MAIN, cost)
    try:
        _save_spend_file()
    except SpendNotSaved:
        pass     # today's figures are for display only; the monthly totals decide


def get_spend() -> dict:
    with _lock:
        sp = dict(_spend) if _spend.get("day") == _today() else _new_day()
    tin, tout = sp["durable_in"] + sp["local_in"], sp["durable_out"] + sp["local_out"]
    if PROVIDER == "openai":
        cost = sp.get("durable_cost", 0.0) + sp.get("local_cost", 0.0)
    else:
        cost = tin / 1e6 * PRICE_IN_PER_M + tout / 1e6 * PRICE_OUT_PER_M
    return {"day": sp["day"], "calls": sp["durable_calls"] + sp["local_calls"],
            "input_tokens": tin, "output_tokens": tout,
            "cost_usd": round(cost, 4),
            "capped": sp["capped"], "usage_read": sp["durable_read"], "read_error": sp["read_error"],
            "daily_call_cap": None if PROVIDER == "openai" else DAILY_CALL_CAP, "model": MODEL,
            "providers": ai_budget.status() if PROVIDER == "openai" else None,
            "price_per_m_tokens_usd": ({"input": OPENAI_PRICES.get(MODEL, (0, 0, 0))[0],
                                        "output": OPENAI_PRICES.get(MODEL, (0, 0, 0))[1]} if PROVIDER == "openai"
                                       else {"input": PRICE_IN_PER_M, "output": PRICE_OUT_PER_M})}


class CapReached(Exception):
    pass


class ProviderRefused(RuntimeError):
    """The provider turned GlassHood away for credit, quota, billing or its key."""
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def _refusal(status: int, code: str, text: str):
    """REQ-GHA-041 clause 6: words for a refusal about the account; None for any other failure."""
    words = f"{code} {text}".lower()
    if code in ("organization_spend_limit_exceeded", "project_spend_limit_exceeded", "organization_usage_limit_exceeded"):
        return f"the provider's own account limit is reached ({code})"
    if status == 401:
        return "the provider rejected the API key"
    if status == 403:
        return "the provider refused access for this API key"
    if status == 402 or any(w in words for w in ("insufficient_quota", "credit_balance", "credit balance", "billing")):
        return "the provider reports no remaining credit or quota"
    return None


# --- Model call ---

def _call_openai(system_prompt: str, user_text: str, max_tokens: int, search: bool, deep: bool) -> tuple:
    """One OpenAI Responses call. JSON answers (the word 'json' must be in the input for the
    JSON format); a web search tool when allowed. Reasoning is kept low: these are summaries."""
    model = OPENAI_MODEL_DEEP if deep else OPENAI_MODEL
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OpenAI key not configured")
    body = {"model": model, "instructions": system_prompt,
            "input": "Data (answer in JSON as instructed):\n" + user_text,
            # reasoning tokens count against this budget, so leave room for the answer
            "max_output_tokens": max(2000, max_tokens * 3), "reasoning": {"effort": "low"}}
    if search:
        body["tools"] = [{"type": "web_search"}]
        body["max_tool_calls"] = SEARCH_CALLS_ALLOWANCE    # the reservation's bound holds for the request
    else:
        body["text"] = {"format": {"type": "json_object"}}
    held = _reserve(ai_budget.MAIN, model, system_prompt + user_text, body["max_output_tokens"], search)
    try:
        r = httpx.post("https://api.openai.com/v1/responses", json=body,
                       headers={"Authorization": f"Bearer {key}"}, timeout=180 if search else 90)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        ai_budget.release(held)     # never reached the provider
        raise
    # any other failure on the way may have been billed: the reservation stands
    if r.status_code != 200:
        ai_budget.release(held)     # an error reply is not billed
        try:
            err = r.json().get("error") or {}
        except Exception:
            err = {}
        why = _refusal(r.status_code, str(err.get("code", "")), str(err.get("type", "")))
        if why:
            raise ProviderRefused(f"OpenAI HTTP {r.status_code}", why)
        raise RuntimeError(f"OpenAI HTTP {r.status_code}")
    data = r.json()
    searches = sum(1 for item in data.get("output") or [] if item.get("type") == "web_search_call")
    _record_openai(model, data.get("usage") or {}, searches, held)
    text, sources = "", []
    for item in data.get("output") or []:
        if item.get("type") == "web_search_call":
            q = ((item.get("action") or {}).get("query"))
            if q and len(sources) < 4:
                sources.append({"query": str(q)[:200]})
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    text += c.get("text", "")
                    for a in c.get("annotations") or []:
                        if a.get("type") == "url_citation" and str(a.get("url", "")).startswith("https://") \
                                and len(sources) < 12:
                            sources.append({"title": str(a.get("title", ""))[:200], "uri": a["url"]})
    return text, sources


def _call_claude(system_prompt: str, user_text: str, max_tokens: int) -> str:
    """One Claude call, used only after OpenAI failed. The SDK's own retries are off: every
    attempt must be a call counted against today's cap."""
    import anthropic
    held = _reserve(ai_budget.BACKUP, CLAUDE_MODEL, system_prompt + user_text, max(2000, max_tokens * 3))
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""), timeout=90, max_retries=0)
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=max(2000, max_tokens * 3), system=system_prompt,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Data (answer in JSON as instructed):\n" + user_text}])
    except anthropic.APIStatusError as e:
        ai_budget.release(held)
        why = _refusal(e.status_code, "", str(e.message))
        if why:
            ai_budget.refused(ai_budget.BACKUP, why)
        raise RuntimeError(f"Claude HTTP {e.status_code}") from None
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Claude could not be reached ({type(e).__name__})") from None
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    _record_openai(CLAUDE_MODEL, usage, reservation=held)
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to answer")
    return "".join(b.text for b in response.content if b.type == "text")


def _count_call() -> None:
    """Today's number of calls, for display. REQ-GHA-041: only the monthly totals can block."""
    with _lock:
        if _spend.get("day") != _today():
            _spend.clear(); _spend.update(_new_day())
        _spend["local_calls"] += 1
    try:
        _save_spend_file()
    except SpendNotSaved:
        pass


def call_model(system_prompt: str, user_text: str, max_tokens: int = 600,
               search: bool = False, deep: bool = False) -> tuple[str, list]:
    """One model call within today's cap (OpenAI, or Gemini on Vertex). Returns the answer's
    text and, when a web search was allowed and used, the pages it drew on ([{title, uri}])."""
    if PROVIDER == "openai":
        # REQ-GHA-041: the main provider while it may be called, else the backup
        blocked = ai_budget.gate(ai_budget.MAIN)
        if not blocked:
            _count_call()
            try:
                return _call_openai(system_prompt, user_text, max_tokens, search, deep)
            except ai_budget.Blocked as e:
                blocked = str(e)
            except ProviderRefused as e:
                blocked = e.reason
                ai_budget.refused(ai_budget.MAIN, e.reason)
            except (RuntimeError, httpx.HTTPError) as e:
                # a web-search answer has no equivalent here: fail plainly rather than drop the search
                if search or not os.getenv("ANTHROPIC_API_KEY"):
                    raise
                logger.warning(f"OpenAI failed ({str(e) if isinstance(e, RuntimeError) else type(e).__name__}); trying Claude")
        if blocked:
            ai_budget.note(f"AI provider OpenAI is blocked: {blocked}.")
            if search:
                raise CapReached(f"OpenAI is blocked ({blocked}); Investigate deeper needs its web search")
        backup = ai_budget.gate(ai_budget.BACKUP) or (None if os.getenv("ANTHROPIC_API_KEY") else "no key is configured")
        if backup:
            ai_budget.note(f"AI provider Anthropic is blocked: {backup}.")
            raise CapReached(f"Anthropic is blocked: {backup}")
        if blocked:
            ai_budget.note("GlassHood is using its backup AI provider, Anthropic, because OpenAI is blocked.")
        _count_call()
        try:
            return _call_claude(system_prompt, user_text, max_tokens), []
        except ai_budget.Blocked as e:
            raise CapReached(f"Anthropic is blocked: {e}")
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
        "condition": obj.get("condition") if obj.get("condition") in CONDITIONS else None,
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


# Google allows about 60 log reads a minute per project; the overview's workers share
# one pace and retry a refusal (HTTP 429) after a growing wait
LOG_READ_GAP_S = float(os.getenv("LOG_READ_GAP_S", "1.2"))
_log_gate = threading.Lock()
_last_log_read = [0.0]


def _read_entries(body: dict, sleep=time.sleep) -> list:
    for attempt, wait in enumerate((0, 5, 15, 30)):
        if wait:
            sleep(wait)
        with _log_gate:
            gap = LOG_READ_GAP_S - (time.monotonic() - _last_log_read[0])
            if gap > 0:
                sleep(gap)
            _last_log_read[0] = time.monotonic()
        r = httpx.post("https://logging.googleapis.com/v2/entries:list", headers=_headers(), timeout=30, json=body)
        if r.status_code == 429 and attempt < 3:
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Cloud Logging HTTP {r.status_code}")
        return r.json().get("entries", [])
    raise RuntimeError("Cloud Logging HTTP 429")


def _log_lines(log_filter: str, warn_n: int, sample_n: int, project: str = "",
               since_s: int = None) -> list:
    """Recent warning/error lines plus a small sample of other lines, newest first."""
    if isinstance(log_filter, dict):
        if log_filter.get("source") != "aws":
            raise ValueError("Unsupported structured log source")
        # Non-Google locations stay structured; never send an AWS location to Cloud Logging.
        from src.collectors.aws_resources import query_logs
        entries = query_logs(log_filter, (since_s or INTERVAL_S) / 3600, warn_n + sample_n)
        warning = {"WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"}
        picked = [e for e in entries if e.get("severity") in warning][:warn_n]
        picked += [e for e in entries if e.get("severity") not in warning][:sample_n]
        return [_entry_text({**e, "textPayload": e["message"]}) for e in picked]
    since = (datetime.now(timezone.utc) - timedelta(seconds=since_s or INTERVAL_S)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = f'timestamp>="{since}"' + (f" AND ({log_filter})" if log_filter else "")
    out = []
    for flt, n in ((f"{base} AND severity>=WARNING", warn_n), (f"{base} AND severity<WARNING", sample_n)):
        if n <= 0:
            continue
        # Errors (unreachable API, credential refresh) propagate to the overview's own error boundary.
        entries = _read_entries({"resourceNames": [f"projects/{project or PROJECT}"], "filter": flt,
                                 "orderBy": "timestamp desc", "pageSize": n})
        out += [_entry_text(e) for e in entries]
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


def _log_location(logs):
    if not logs:
        return None
    return dict(logs[0]) if logs[0].get("source") == "aws" else logs[0].get("filter")


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
                location = _log_location(logs)
                if location:
                    filters[n["id"]] = location
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
        yield rec, (_log_location(logs) if logs else filters.get(n.get("id"), parent_filter))

        def kids(children, parent):
            for c in children or []:
                if isinstance(c, dict) and c.get("id"):
                    cl = ((c.get("monitoring") or {}).get("logs") or [])
                    yield _part_record(c, parent), (_log_location(cl) if cl else "")
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


def _records_file():
    d = os.getenv("AI_STATE_DIR", "")
    return os.path.join(d, "ai_records.json") if d else None


def _save_records() -> None:
    """REQ-GHA-042 clause 9: what GlassHood has evaluated survives a restart."""
    import tempfile
    path = _records_file()
    if not path:
        _records_problem[0] = "no folder is set up to keep the AI evaluations (AI_STATE_DIR)"
        return
    with _records_lock:
        with _lock:
            snap = {"system": _system, "own": _own, "outside": _outside, "parts": _parts, "outside_sig": _outside_sig,
                    "state_sig": _state_sig, "last_round": _last_round[0]}
            text = json.dumps(snap, default=str)
        try:
            fd, tmp = tempfile.mkstemp(prefix=".ai_records.", dir=os.path.dirname(path))
            with os.fdopen(fd, "w") as f:
                f.write(text)
            os.replace(tmp, path)
            _records_problem[0] = None
        except Exception as e:
            _records_problem[0] = f"the AI evaluations could not be saved ({type(e).__name__})"
            logger.warning(_records_problem[0])


CHECKPOINT_S = 5
_last_checkpoint = [0.0]
_flush_timer = [None]


def _flush_checkpoint() -> None:
    with _lock:
        _flush_timer[0] = None
        _last_checkpoint[0] = time.monotonic()
    _save_records()


def _checkpoint() -> None:
    """A long batch saves as it goes. A save skipped to space them out is scheduled, so a finished
    analysis reaches the disk within a few seconds even if nothing else finishes."""
    now = time.monotonic()
    timer = None
    with _lock:
        if now - _last_checkpoint[0] >= CHECKPOINT_S:
            _last_checkpoint[0] = now
        else:
            if _flush_timer[0] is None:
                timer = _flush_timer[0] = threading.Timer(CHECKPOINT_S, _flush_checkpoint)
                timer.daemon = True
            else:
                return
    if timer:
        timer.start()
    else:
        _save_records()


_records_once = threading.Lock()
_records_loaded = [None]  # None until the saved records were read once; then the schedule's start time


def _ensure_records() -> float:
    """REQ-GHA-046 clause 20: the saved records are read before anything is shown from them, so a
    restart never shows a system as not yet assessed while its saved evaluation is still unread."""
    with _records_once:
        if _records_loaded[0] is None:
            _records_loaded[0] = _load_records()
        return _records_loaded[0]


def _load_records() -> float:
    """Bring back what was evaluated before a restart. Returns the time the schedule counts from: the
    last finished round, or the newest evaluation if no round finished yet (0 if nothing was evaluated)."""
    global _system
    path = _records_file()
    if not path or not os.path.exists(path):
        return 0.0
    try:
        with open(path) as f:
            data = json.load(f)
        with _lock:
            _system = data.get("system") or {}
            _own.update(data.get("own") or {})
            _outside.update(data.get("outside") or {})
            _parts.update(data.get("parts") or {})
            _outside_sig.update(data.get("outside_sig") or {})
            _state_sig.update(data.get("state_sig") or {})
            _last_round[0] = float(data.get("last_round") or 0.0)
            times = [e["analyzed_at"] for e in [_system, *_own.values(), *_outside.values(), *_parts.values()]
                     if e.get("summary") and e.get("analyzed_at")]
        return _last_round[0] or max(times, default=0.0)
    except Exception as e:
        _records_problem[0] = f"the saved AI evaluations could not be read ({type(e).__name__})"
        logger.warning(_records_problem[0])
        return 0.0


def _fill_missing(topology: dict) -> None:
    """REQ-GHA-042 clause 10: after a restart only what has no saved evaluation is evaluated at once."""
    from src.api.routes.manifests import _load_manifests
    refresh_durable_spend()
    with _lock:
        have_system = bool(_system.get("summary"))
        known_parts = {k for k, v in _parts.items() if v.get("summary")}
        known_outside = {k for k, v in _outside.items() if v.get("summary")}
    if not have_system:
        run_system(topology)
    edges = topology.get("edges", [])
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="overview") as ex:
        list(ex.map(lambda r: _run_part(r[0], r[1], edges),
                    [(rec, flt) for rec, flt in _walk_parts(topology) if rec["id"] not in known_parts]))
    missing = {m.get("product") for m in _load_manifests() if m.get("kind") == "outside_view"} - known_outside
    run_outside(topology=topology, overviews=missing)
    _save_records()


def ai_offline():
    """REQ-GHA-042: {since, alert} while no AI provider can be called, else None."""
    if PROVIDER != "openai" or not any(a["group"] == "budget:all" for a in ai_budget.alarms()):
        return None
    from src.models.alert import alarm_number
    return {"since": ai_budget.offline_since() or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "alert": alarm_number("budget:all", ai_budget.ALARM_PART),
            "group": "budget:all", "node_id": ai_budget.ALARM_PART}   # the number is for reading, this opens it


def _system_nodes(topology: dict, product: str) -> list:
    """Every box of one system, including the ones drawn inside another."""
    def walk(nodes):
        for n in nodes or []:
            yield n
            yield from walk(n.get("children"))
    return list(walk([n for n in topology.get("nodes", []) if n.get("project") == product]))


def _signature(nodes: list) -> str:
    return json.dumps(sorted((str(n.get("id")), str(n.get("status"))) for n in nodes))


def _open_alerts(nodes: list) -> list:
    """REQ-GHA-040: the system's open alarms as they stand when its record is written."""
    from src.rules.engine import get_alerts
    ids = {n.get("id") for n in nodes}
    skip = ("evidence", "report", "reasons", "explanation", "anomaly_classification", "check")
    return [{k: v for k, v in a.items() if k not in skip}
            for a in get_alerts() if a.get("node_id") in ids and a.get("kind") != "example"]


def _system_record(result: dict, alerts: list) -> dict:
    """REQ-GHA-040: condition, text, alarms and time, written as one record."""
    if not result.get("condition"):
        raise ValueError("the model's answer had no condition")
    return {**_now_entry(result), "alerts": alerts}


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


OWN_ATTEMPTS = 3


def _worth_retrying(e: Exception) -> bool:
    """A refused budget, missing configuration or a rejected request fails the same way again."""
    if isinstance(e, CapReached) or "not configured" in str(e):
        return False
    status = re.search(r"HTTP (\d{3})", str(e))
    return not status or not (400 <= int(status.group(1)) < 500) or int(status.group(1)) in (408, 429)


def _assessment_due(product: str) -> bool:
    """Call with _lock held: does this system still need a first or a retried assessment?"""
    job, current = _own_jobs.get(product, {}), _own.get(product) or {}
    if product in _changed:
        return job.get("status") != "running"
    if job.get("status") in ("running", "failed") or (current.get("summary") and not current.get("error")):
        return False
    return job.get("attempts", 0) < OWN_ATTEMPTS and time.time() >= job.get("retry_at", 0)


def run_own_systems(topology: dict, only_pending: bool = False) -> None:
    """REQ-GHA-037: an overview of each of our own systems on its own, for its card and its
    view. A system's recent log lines are included when they live in the project read here."""
    by_product: dict = {}
    for n in topology.get("nodes", []):
        if n.get("project"):
            by_product.setdefault(n["project"], []).append(n)
    try:
        from src.api.routes.manifests import _load_manifests
        projects = {m.get("product"): m.get("project_id") for m in _load_manifests() if m.get("kind") != "outside_view"}
    except Exception:
        projects = {}
    for product, nodes in by_product.items():
        if product not in projects:
            continue  # external systems have their own overview (run_outside)
        with _lock:
            job = _own_jobs.get(product, {})
            # one run per system: a manual refresh, the round and the scan never compete
            if job.get("status") == "running" or (only_pending and not _assessment_due(product)):
                continue
            attempts = job.get("attempts", 0) + 1 if only_pending else 1
            _changed.discard(product)
            _own_jobs[product] = {"status": "running", "attempts": attempts,
                                  "started_at": time.time()}
        try:
            walked = list(_walk_parts({"nodes": nodes}))
            parts = [rec for rec, _ in walked]
            statuses = [p.get("status") for p in parts]
            logs = _log_lines("", SYSTEM_WARN_LINES, SYSTEM_SAMPLE_LINES) if projects.get(product) == PROJECT else []
            locations = {json.dumps(f, sort_keys=True): f for _, f in walked if isinstance(f, dict)}
            for location in locations.values():
                logs += _log_lines(location, SYSTEM_WARN_LINES, SYSTEM_SAMPLE_LINES)
            full = _system_nodes({"nodes": nodes}, product)
            sig, alerts = _signature(full), _open_alerts(full)
            payload = sanitize({"system": product, "parts": parts, "recent_logs": logs,
                                "open_alerts": [{"severity": a.get("severity"), "kind": a.get("kind"), "title": a.get("title")} for a in alerts],
                                "states": {s: statuses.count(s) for s in set(statuses)}})
            record = _system_record(_generate(SYSTEM_PROMPT, json.dumps(payload, default=str)), alerts)
            with _lock:
                _own[product] = record
                _state_sig[product] = sig
                _own_jobs[product] = {"status": "complete", "attempts": attempts}
            _save_records()
        except Exception as e:
            why = _failure(e)
            logger.warning(f"overview of {product} failed: {why}")
            with _lock:
                _own[product] = _keep_last_good(_own.get(product), why)
                if _worth_retrying(e) and attempts < OWN_ATTEMPTS:
                    _own_jobs[product] = {"status": "retrying", "attempts": attempts,
                                          "retry_at": time.time() + 60 * attempts}
                else:
                    _own_jobs[product] = {"status": "failed", "attempts": attempts}


def get_own(product: str):
    with _lock:
        entry = _own.get(product)
        job = dict(_own_jobs.get(product) or {"status": "not_started"})
    if not entry and job["status"] == "not_started":
        return None
    return {**_with_staleness(entry), "job": job}


def system_cards() -> dict:
    """{product: short overview} for every system that has one, for the home view's cards."""
    _ensure_records()
    with _lock:
        both = {**{k: dict(v) for k, v in _own.items()}, **{k: dict(v) for k, v in _outside.items()}}
        jobs = {k: dict(v) for k, v in _own_jobs.items()}
        for product in jobs:
            both.setdefault(product, {})
    off = ai_offline()
    notice = next((a["title"] for a in ai_budget.alarms()), None) if PROVIDER == "openai" and not off else None
    if notice:
        both.setdefault(ai_budget.GROUP, {})
    if off:
        from src.api.routes.manifests import _load_manifests
        for m in _load_manifests():
            both.setdefault(m.get("product"), {})
    return {k: {"ai_offline": off, "critical_notice": notice if k == ai_budget.GROUP else None,
                "summary": v.get("summary"), "score": v.get("score"), "analyzed_at": v.get("analyzed_at"),
                "error": v.get("error"), "stale": _with_staleness(v).get("stale"),
                "condition": v.get("condition"), "alerts": v.get("alerts"), "issues": v.get("issues") or [],
                "job": jobs.get(k) or {"status": "complete"}} for k, v in both.items()}


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
        _checkpoint()
    except Exception as e:
        why = _failure(e)
        logger.warning(f"part overview failed for {pid}: {why}")
        with _lock:
            _parts[pid] = _keep_last_good(_parts.get(pid), why)


def run_all(topology: dict) -> None:
    refresh_durable_spend()
    run_system(topology)
    run_own_systems(topology)
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
    try:
        written = run_outside(topology=topology)
    except Exception as e:
        written = 0
        logger.error(f"outside overviews failed: {e}")
    _last_round[0] = time.time()
    _save_records()
    logger.info(f"AI overviews written: system + {len(futures) - failed} parts + {written} external parts; "
                f"spend today {get_spend()}")


def _with_staleness(entry: dict) -> dict:
    out = dict(entry or {})
    ts = out.get("analyzed_at")
    out["stale"] = (ts is None) or (time.time() - ts > INTERVAL_S)
    out["interval_s"] = INTERVAL_S
    return out


def get_system() -> dict:
    _ensure_records()
    with _lock:
        return _with_staleness(_system)


def get_outside(product: str) -> dict:
    with _lock:
        entry = _outside.get(product)
    return _with_staleness(entry) if entry else None


def _published_parts(p: dict) -> list:
    """[(box id, record, signature)] for one provider: the part, the provider's words about it,
    and what its analysis depends on, so it is rewritten only when that changes."""
    by_cid = {c.get("id"): c for c in p["components"]}
    groups = {c.get("id"): c.get("name") for c in p["components"] if c.get("group")}
    out = []
    for cid, box in p["comps"].items():
        c = by_cid.get(cid) or {}
        events = [e for e in p["events"] if any(x.get("id") == cid for x in e.get("components") or [])]
        rec = {"component": c.get("name"), "group": groups.get(c.get("group_id")),
               "provider_status": c.get("status"), "provider_updated": c.get("updated_at"),
               "open_incidents_and_maintenance": [{
                   "name": e.get("name"), "kind": e.get("_kind"), "status": e.get("status"),
                   "impact": e.get("impact"),
                   "updates": [{"at": u.get("created_at"), "status": u.get("status"), "text": (u.get("body") or "")[:600]}
                               for u in (e.get("incident_updates") or [])[:5]],
                   "also_affects": [x.get("name") for x in e.get("components") or [] if x.get("id") != cid][:20],
               } for e in events]}
        # everything the analysis is written from: any change (an edited update, a new
        # incident status, a changed set of affected parts) rewrites it; nothing else does
        sig = json.dumps(rec, sort_keys=True, default=str)
        out.append((box, rec, sig))
    return out


def _run_outside_part(box: str, rec: dict, sig) -> None:
    try:
        result = _generate(OUTSIDE_PART_PROMPT, json.dumps(sanitize(rec), default=str))
        with _lock:
            _parts[box] = _now_entry(result)
            _outside_sig[box] = sig
        _checkpoint()
    except Exception as e:
        why = _failure(e)
        logger.warning(f"outside part analysis failed for {box}: {why}")
        with _lock:
            _parts[box] = _keep_last_good(_parts.get(box), why)


def run_outside(parts: bool = True, topology: dict = None, only: set = None, overviews: set = None) -> int:
    """REQ-GHA-036 clause 7: an overview of each external system every round, and an analysis
    of each of its parts written only when what the provider publishes about it changed.
    Returns the number of part analyses written."""
    from src.collectors import statuspage
    jobs = []
    for p in statuspage.published():
        product = p.get("product")
        if only is not None and product not in only:
            continue
        if not p["read"]:
            with _lock:
                _outside[product] = _keep_last_good(_outside.get(product), f"the provider's status could not be read: {p['error']}")
            continue
        part_list = _published_parts(p)
        counts = {}
        for _, rec, _ in part_list:
            counts[rec["provider_status"]] = counts.get(rec["provider_status"], 0) + 1
        payload = {"service": p["name"], "status_page": p["page"], "components_by_state": counts,
                   "not_operational": [{"component": r["component"], "group": r["group"], "state": r["provider_status"],
                                        "since": r["provider_updated"]}
                                       for _, r, _ in part_list if r["provider_status"] != "operational"][:150],
                   "open_incidents_and_maintenance": [{
                       "name": e.get("name"), "kind": e.get("_kind"), "status": e.get("status"), "impact": e.get("impact"),
                       "components": [x.get("name") for x in e.get("components") or []][:30],
                       "latest_update": ((e.get("incident_updates") or [{}])[0].get("body") or "")[:800],
                   } for e in p["events"]]}
        with _lock:     # one run per system: old work can never overwrite a newer record
            wanted = overviews is None or product in overviews
            claimed = wanted and product not in _outside_running
            if claimed:
                _outside_running.add(product)
            if wanted and not claimed and only is not None:
                _triggered_sig.pop(product, None)   # skipped, so this change is still due
        try:
            if claimed:
                # what the record says is fixed before the model is asked
                nodes = _system_nodes(topology or {}, product)
                sig, alerts = _signature(nodes), _open_alerts(nodes)
                record = _system_record(_generate(OUTSIDE_SYSTEM_PROMPT, json.dumps(sanitize(payload), default=str)), alerts)
                with _lock:
                    _outside[product] = record
                    _state_sig[product] = sig
        except Exception as e:
            why = _failure(e)
            logger.warning(f"outside overview failed for {p['name']}: {why}")
            with _lock:
                _outside[product] = _keep_last_good(_outside.get(product), why)
        finally:
            if claimed:
                with _lock:
                    _outside_running.discard(product)
        if not parts:
            continue
        with _lock:
            jobs += [(box, rec, sig) for box, rec, sig in part_list
                     if not (_outside_sig.get(box) == sig and (_parts.get(box) or {}).get("summary"))]
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="outside") as ex:
        for f in [ex.submit(_run_outside_part, *j) for j in jobs]:
            try:
                f.result()
            except Exception as e:
                logger.error(f"outside part worker failed: {e}")
    _save_records()
    return len(jobs)


def get_part(part_id: str):
    _ensure_records()
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
    """A person's refresh renews every system overview the views show (the combined one, each
    own system's and each external system's); part analyses follow their own schedule."""
    refresh_durable_spend()
    run_system(topology)
    run_own_systems(topology)
    try:
        run_outside(parts=False, topology=topology)
    except Exception as e:
        logger.error(f"outside overviews on refresh failed: {e}")
    _save_records()


def _pending_scan_once(get_topology_fn) -> None:
    from src.api.routes.manifests import _load_manifests
    own = {m.get("product") for m in _load_manifests() if m.get("kind") != "outside_view"}
    with _lock:
        due = any(_assessment_due(p) for p in own)
    if due:
        refresh_durable_spend()
        run_own_systems(get_topology_fn(), only_pending=True)


def _sync_budget_alarms() -> None:
    """REQ-GHA-041 clauses 7, 9 and 10: raised and ended here, with no AI call."""
    if PROVIDER == "openai":
        from src.rules.engine import track_ai_budget
        ai_budget.monitor()
        from src.analysis import selection_review
        unsaved = _records_problem[0] or selection_review.problem[0]
        saving = [{"group": "budget:saving", "title": "GlassHood could not save its AI evaluations",
                   "explanation": {"what": f"{unsaved}. A restart would lose the latest evaluations.", "suspicion": "",
                                   "directions": ["GlassHood administrator: check that the state storage share is mounted and writable."]}}
                  ] if unsaved else []
        track_ai_budget(ai_budget.alarms() + saving, ai_budget.ALARM_PART)


def _change_scan_once(get_topology_fn) -> None:
    """REQ-GHA-040 clause 7: a system whose parts changed state gets a new record soon."""
    from src.api.routes.manifests import _load_manifests
    kinds = {m.get("product"): m.get("kind") for m in _load_manifests()}
    topology = get_topology_fn()
    own, outside = set(), set()
    for product, kind in kinds.items():
        sig = _signature(_system_nodes(topology, product))
        with _lock:
            known = _state_sig.get(product)
            if sig == known:
                _triggered_sig.pop(product, None)   # back where it was: the next change counts again
            if known is None or sig in (known, _triggered_sig.get(product)):
                continue
            _triggered_sig[product] = sig
            if kind == "outside_view":
                outside.add(product)
            else:
                own.add(product)
                _changed.add(product)
                if _own_jobs.get(product, {}).get("status") != "running":
                    _own_jobs[product] = {"status": "queued", "attempts": 0}
    if own or outside:
        refresh_durable_spend()
    if own:
        run_own_systems(topology, only_pending=True)
    if outside:
        run_outside(parts=False, topology=topology, only=outside)


def _pending_loop(get_topology_fn, stop) -> None:
    """A new system gets its first assessment without waiting for a round, however long that takes."""
    next_change_scan = time.monotonic() + CHANGE_SCAN_S
    while not stop.wait(PENDING_SCAN_S):
        try:
            _sync_budget_alarms()
            _pending_scan_once(get_topology_fn)
            if time.monotonic() >= next_change_scan:
                next_change_scan = time.monotonic() + CHANGE_SCAN_S
                _change_scan_once(get_topology_fn)
            from src.analysis import selection_review
            selection_review.refresh_due()
            from src.api.routes import agents   # REQ-GHA-049 clause 4
            agents.scan((get_topology_fn() or {}).get("nodes") or [])
        except Exception as e:
            logger.error(f"new-system assessment scan failed: {type(e).__name__}")


def overview_loop(get_topology_fn, ready_fn=None):
    """Clause 4: first overviews as soon as the parts are known, then every INTERVAL_S."""
    stop = threading.Event()
    _ensure_records()   # clause 20: before the first poll, so the screen never waits on it
    for _ in range(60):  # wait for the first poll of the parts, at most ~5 minutes
        if ready_fn is None or ready_fn():
            break
        stop.wait(5)
    last_round = _ensure_records()
    threading.Thread(target=_pending_loop, args=(get_topology_fn, stop), daemon=True,
                     name="assessment-scan").start()
    if last_round:      # REQ-GHA-042 clause 10: a restart does not start a new round
        try:
            _fill_missing(get_topology_fn())
        except Exception as e:
            logger.error(f"filling in missing evaluations failed: {type(e).__name__}")
        stop.wait(max(0, last_round + INTERVAL_S - time.time()))
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
