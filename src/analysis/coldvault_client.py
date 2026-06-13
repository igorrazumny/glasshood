# File: src/analysis/coldvault_client.py
# Purpose: AI analysis via ColdVault API (replaces direct Gemini)

import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

import os
from src.config.settings import (
    COLDVAULT_URL, COLDVAULT_API_KEY,
    ANALYSIS_INTERVAL, ANALYSIS_COOLDOWN, ANALYSIS_ESCALATION_THRESHOLD,
)

# Platform API for inference (preferred over ColdVault direct)
PLATFORM_URL = os.getenv("PLATFORM_URL", "https://api.9robots.ai")
PLATFORM_KEY = os.getenv("NINE_ROBOTS_PLATFORM_KEY", "")

logger = logging.getLogger(__name__)

_cached_analysis: dict = {
    "score": None,
    "summary": "",
    "issues": [],
    "recommendations": [],
    "timestamp": None,
    "stale": True,
}
_last_run: float = 0
_lock = threading.Lock()

SYSTEM_PROMPT = """You are an infrastructure health analyst for a pharma-grade AI platform (ColdVault).
Analyze the topology state and provide:
1. A health score (1-10, where 10 = perfect)
2. A 1-2 sentence summary
3. A list of current issues (empty if none)
4. A list of actionable recommendations

Context: This is a Confidential VM (AMD SEV-SNP) running ColdVault with encrypted RAG,
Cloud SQL, and connections to 4+ LLM providers. It serves pharma customers requiring
ALCOA+ / Annex 11 compliance.

Known limitations (do NOT flag these as issues):
- FAISS RAG metrics (active_stores, total_vectors) are null — ColdVault does not yet expose these via /api/metrics. Pending ColdVault-side fix.
- PostgreSQL pool metrics (pool_size, pool_checked_out) are null — same reason.
- Planned nodes (status=planned) are expected future infrastructure, not outages.
- Self-hosted model nodes with status=deployed are running but lack external health probes.

Focus on: actual service degradation, connectivity failures, security gaps, and compliance risks.

Respond in JSON format:
{
  "score": 9,
  "summary": "All systems operational. ColdVault running with low resource usage.",
  "issues": [],
  "recommendations": ["Consider enabling LB access logging for audit trail"]
}"""


def _parse_response(raw_text: str) -> dict:
    """Extract JSON from ColdVault response (handles markdown code blocks)."""
    if not raw_text:
        raise ValueError("Empty response from ColdVault API")
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    # Try to find JSON object in the response
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    return json.loads(text)


def _call_platform(message: str, model: str = "gemini-3.1-flash-lite-preview",
                   timeout: float = 120.0) -> str:
    """Call Platform /api/v1/inference for AI analysis."""
    if not PLATFORM_KEY:
        raise ValueError("NINE_ROBOTS_PLATFORM_KEY not set")
    resp = httpx.post(
        f"{PLATFORM_URL}/api/v1/inference",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            "max_tokens": 1000,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "")


def _stream_coldvault(message: str, mode: str = "standard",
                      models: list = None, timeout: float = 60.0) -> str:
    """POST to ColdVault /api/chat/stream (SSE) and return complete response text."""
    if models is None:
        models = ["Gemini 2.5 Flash"]

    # Read timeout must be long — ColdVault may take 60-90s to process large prompts
    # before sending first SSE data chunk after the heartbeat
    stream_timeout = httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=10.0)
    with httpx.Client(timeout=stream_timeout) as client:
        with client.stream("POST",
            f"{COLDVAULT_URL}/api/chat/stream",
            headers={"Authorization": f"Bearer {COLDVAULT_API_KEY}"},
            json={
                "message": message,
                "mode": mode,
                "models": models,
                "web_search_enabled": False,
                "session_id": f"glasshood-{mode}-{int(time.time())}",
            },
        ) as resp:
            resp.raise_for_status()
            text = ""
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "complete":
                    text = event.get("response", "") or ""
                    break
            if not text:
                logger.warning(f"ColdVault stream returned no 'complete' event (mode={mode})")
            return text


def _call_coldvault(message: str, mode: str = "standard",
                    models: list = None) -> str:
    """Call ColdVault via streaming endpoint."""
    return _stream_coldvault(message, mode=mode, models=models, timeout=120.0)


def _call_debate(topology_json: str) -> str:
    """Call ColdVault debate mode for deeper analysis."""
    message = f"{SYSTEM_PROMPT}\n\nCurrent topology state:\n{topology_json}"
    return _stream_coldvault(
        message, mode="aggregate",
        models=["Gemini 2.5 Flash", "Claude Haiku 4.5", "GPT-5 Mini"],
        timeout=120.0,
    )


def analyze(topology_data: dict) -> dict:
    """Run ColdVault API analysis on topology state."""
    global _cached_analysis, _last_run

    if not PLATFORM_KEY and not COLDVAULT_API_KEY:
        with _lock:
            if _cached_analysis.get("timestamp"):
                _cached_analysis["stale"] = True
                return _cached_analysis
            _cached_analysis = {
                "score": None,
                "summary": "No API key configured (NINE_ROBOTS_PLATFORM_KEY or COLDVAULT_API_KEY)",
                "issues": ["No API key"],
                "recommendations": [],
                "timestamp": None,
                "stale": True,
            }
        return _cached_analysis

    topology_json = json.dumps(topology_data, indent=2)
    message = f"Current topology state:\n{topology_json}"

    # Include anomaly data if any detected
    from src.security.anomaly_detector import get_anomalies
    anomalies = get_anomalies()
    if anomalies:
        message += f"\n\nSECURITY ANOMALIES DETECTED:\n{json.dumps(anomalies, indent=2)}"

    try:
        raw = None
        result = None

        # Prefer Platform API (fast, unified endpoint)
        if PLATFORM_KEY:
            PLATFORM_MODELS = [
                "gemini-3.1-flash-lite-preview",
                "gpt-5.4",
            ]
            for model in PLATFORM_MODELS:
                try:
                    raw = _call_platform(message, model=model)
                    result = _parse_response(raw)
                    break
                except Exception as e:
                    logger.warning(f"Platform analysis with {model} failed: {e}, trying next")
                    continue

        # Fallback to ColdVault direct if Platform unavailable
        if result is None and COLDVAULT_API_KEY:
            MODEL_CHAIN = [
                (["Gemini 2.5 Flash"], "standard"),
                (["GLM-4.7 Flash"], "standard"),
            ]
            for models, mode in MODEL_CHAIN:
                try:
                    raw = _stream_coldvault(message, mode=mode, models=models, timeout=120.0)
                    result = _parse_response(raw)
                    break
                except Exception as e:
                    logger.warning(f"ColdVault analysis with {models[0]} failed: {e}")
                    continue

        if result is None:
            raise ValueError("All models in chain failed")

        score = result.get("score")

        # Escalate to debate if score below threshold
        if score is not None and score < ANALYSIS_ESCALATION_THRESHOLD:
            logger.info(f"Score {score} < {ANALYSIS_ESCALATION_THRESHOLD}, escalating to debate")
            try:
                debate_raw = _call_debate(topology_json)
                debate_result = _parse_response(debate_raw)
                result = debate_result
            except Exception as e:
                logger.warning(f"Debate escalation failed, using fast result: {e}")

        def _to_strings(items):
            return [i.get("description", str(i)) if isinstance(i, dict) else str(i)
                    for i in (items or [])]

        with _lock:
            _cached_analysis = {
                "score": result.get("score"),
                "summary": result.get("summary", ""),
                "issues": _to_strings(result.get("issues", [])),
                "recommendations": _to_strings(result.get("recommendations", [])),
                "timestamp": time.time(),
                "stale": False,
            }
            _last_run = time.time()

    except Exception as e:
        logger.error(f"ColdVault analysis failed (all models): {e}")
        with _lock:
            if _cached_analysis.get("timestamp"):
                # Serve stale cache — last known good analysis
                _cached_analysis["stale"] = True
            else:
                _cached_analysis = {
                    "score": None,
                    "summary": f"ColdVault unreachable — {e}",
                    "issues": [str(e)],
                    "recommendations": [],
                    "timestamp": None,
                    "stale": True,
                }
        # Buffer telemetry for black box
        try:
            from src.analysis.black_box import buffer_telemetry
            buffer_telemetry(topology_data, _cached_analysis, event="unreachable")
        except Exception:
            pass

    return _cached_analysis


def analysis_loop(get_topology_fn):
    """Background analysis loop — runs immediately then every ANALYSIS_INTERVAL seconds."""
    stop = threading.Event()
    # Initial delay: wait 30s for collectors to populate, then run first analysis
    stop.wait(30)
    while True:
        try:
            topology_data = get_topology_fn()
            analyze(topology_data)
        except Exception as e:
            logger.error(f"Analysis loop error: {e}")
        # Periodic flush of black box spool to GCS
        try:
            from src.analysis.black_box import flush_to_gcs
            flush_to_gcs()
        except Exception:
            pass
        if stop.wait(ANALYSIS_INTERVAL):
            break


def can_refresh() -> bool:
    """Rate limit manual refresh to ANALYSIS_COOLDOWN."""
    return (time.time() - _last_run) >= ANALYSIS_COOLDOWN


def get_analysis() -> dict:
    with _lock:
        return dict(_cached_analysis)


# --- Per-node analysis (stale-while-revalidate) ---

_node_cache: dict = {}  # {node_id: {"result": dict, "ts": float}}
_node_lock = threading.Lock()
_node_refreshing: set = set()  # node_ids currently being refreshed
NODE_CACHE_TTL = 3600  # 1 hour — stale after this, but still served instantly
_node_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="node-analysis")

NODE_PROMPT = """You are an infrastructure analyst for a pharma-grade AI platform (ColdVault).
Analyze this specific component and provide:
1. A health score (1-10)
2. A brief assessment (1-2 sentences)
3. Issues specific to this component (empty if none)
4. Recommendations

Component:
{node_json}

Connections: {connections}

Respond in JSON: {{"score": N, "summary": "...", "issues": [...], "recommendations": [...]}}"""


def _do_node_analysis(node_id: str, node_data: dict, connections: list):
    """Run node analysis in background thread. Updates cache when done."""
    try:
        if not PLATFORM_KEY and not COLDVAULT_API_KEY:
            return

        message = NODE_PROMPT.format(
            node_json=json.dumps(node_data, indent=2),
            connections=", ".join(connections) if connections else "none",
        )

        parsed = None

        # Prefer Platform API
        if PLATFORM_KEY:
            for model in ["gemini-3.1-flash-lite-preview", "gpt-5.4"]:
                try:
                    raw = _call_platform(message, model=model)
                    parsed = _parse_response(raw)
                    break
                except Exception as e:
                    logger.warning(f"Node {node_id} Platform analysis with {model} failed: {e}")
                    continue

        # Fallback to ColdVault
        if parsed is None and COLDVAULT_API_KEY:
            for models in [["Gemini 2.5 Flash"], ["GLM-4.7 Flash"]]:
                try:
                    raw = _stream_coldvault(message, mode="standard", models=models, timeout=120.0)
                    parsed = _parse_response(raw)
                    break
                except Exception as e:
                    logger.warning(f"Node {node_id} ColdVault analysis with {models[0]} failed: {e}")
                    continue

        if parsed is None:
            logger.error(f"Node analysis failed for {node_id}: all models failed")
            return

        # Normalize: AI sometimes returns issues/recs as objects instead of strings
        def _to_strings(items):
            return [i.get("description", str(i)) if isinstance(i, dict) else str(i)
                    for i in (items or [])]

        result = {
            "score": parsed.get("score"),
            "summary": parsed.get("summary", ""),
            "issues": _to_strings(parsed.get("issues", [])),
            "recommendations": _to_strings(parsed.get("recommendations", [])),
            "analyzed_at": time.time(),
            "stale": False,
        }
        with _node_lock:
            _node_cache[node_id] = {"result": result, "ts": time.time()}
        logger.info(f"Node analysis complete for {node_id}: score={result['score']}")
    except Exception as e:
        logger.error(f"Node analysis failed for {node_id}: {e}")
    finally:
        with _node_lock:
            _node_refreshing.discard(node_id)


def analyze_node(node_data: dict, connections: list) -> dict:
    """Return cached node analysis instantly. Triggers background refresh if stale.

    Never blocks the caller — always returns immediately with whatever is cached.
    If nothing is cached, returns a placeholder and kicks off background analysis.
    """
    node_id = node_data.get("id", "unknown")

    with _node_lock:
        cached = _node_cache.get(node_id)

    if cached:
        result = dict(cached["result"])
        age = time.time() - cached["ts"]
        result["stale"] = age > NODE_CACHE_TTL
        result["analyzed_at"] = cached["ts"]

        # If stale, trigger background refresh (if not already running)
        if result["stale"]:
            _trigger_node_refresh(node_id, node_data, connections)

        return result

    # No cache at all — return placeholder, start background analysis
    _trigger_node_refresh(node_id, node_data, connections)
    return {
        "score": None,
        "summary": "Analysis in progress — check back shortly",
        "issues": [],
        "recommendations": [],
        "analyzed_at": None,
        "stale": True,
    }


def refresh_node(node_id: str, node_data: dict, connections: list):
    """Force a background refresh for a specific node (manual trigger)."""
    _trigger_node_refresh(node_id, node_data, connections, force=True)


def _trigger_node_refresh(node_id: str, node_data: dict, connections: list,
                          force: bool = False):
    """Submit background analysis if not already running."""
    with _node_lock:
        if not force and node_id in _node_refreshing:
            return
        _node_refreshing.add(node_id)
    _node_executor.submit(_do_node_analysis, node_id, node_data, connections)


def get_node_analysis_cached(node_id: str) -> dict:
    """Return cached analysis for a node without triggering refresh."""
    with _node_lock:
        cached = _node_cache.get(node_id)
    if cached:
        result = dict(cached["result"])
        result["stale"] = (time.time() - cached["ts"]) > NODE_CACHE_TTL
        result["analyzed_at"] = cached["ts"]
        return result
    return None
