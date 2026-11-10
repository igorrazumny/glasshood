# File: src/collectors/glasshood_self.py
# Purpose: REQ-GHA-035 clause 8 — GlassHood's view of its own work: each collector and AI
# task as a box, judged from GlassHood's own state when the page is built (so a stopped
# loop shows as stopped, rather than keeping the last state it wrote).
#
#   probe: {type: glasshood_self, component: coldvault_read | landscape_checks |
#           ai_overview | ai_review | public_status | saved_state}

import time

from src.config.settings import BACKGROUND_POLL_INTERVAL

_STARTED = time.time()   # a task that never runs is measured from GlassHood's own start

COMPONENTS = ("coldvault_read", "landscape_checks", "ai_overview", "ai_review", "public_status", "saved_state")


def _age(ts) -> float:
    return time.time() - ts if ts else float("inf")


def _fresh(ts, interval: float, what: str) -> tuple:
    """healthy within 2.5 rounds, degraded up to 5 rounds, error beyond: a stopped loop shows."""
    age = _age(ts)
    if age == float("inf"):
        since = time.time() - _STARTED
        if since <= 2.5 * interval:
            return "not checked", f"{what} has not run yet (GlassHood started {round(since / 60)} min ago)"
        return "error", (f"{what} has not run at all since GlassHood started {round(since / 60)} min ago "
                         f"(every {round(interval / 60)} min)")
    minutes = round(age / 60)
    if age <= 2.5 * interval:
        return "healthy", f"{what} ran {minutes} min ago (every {round(interval / 60)} min)"
    if age <= 5 * interval:
        return "degraded", f"{what} is late: last ran {minutes} min ago (every {round(interval / 60)} min)"
    return "error", f"{what} has stopped: last ran {minutes} min ago (every {round(interval / 60)} min)"


def component(name: str) -> dict:
    status, desc, figures = _judge(name)
    return {"status": status, "metrics": figures, "check_description": desc}


def _judge(name: str) -> tuple:
    interval = BACKGROUND_POLL_INTERVAL
    if name == "coldvault_read":
        from src.collectors import coldvault
        st = coldvault.get_metrics_status()
        if st.get("checked_at") and not st.get("read"):
            return "error", f"ColdVault's figures were not read: {st.get('reason')}", {"read": False}
        s, d = _fresh(st.get("checked_at"), interval, "Reading ColdVault's figures")
        return s, d, {"read": bool(st.get("read"))}
    if name == "landscape_checks":
        from src.collectors import manifest_metrics
        polls = [v.get("last_poll") for v in manifest_metrics.get_all_statuses().values() if v.get("last_poll")]
        s, d = _fresh(max(polls) if polls else None, interval, "Checking the landscapes' parts")
        return s, d, {"parts_checked": len(polls)}
    if name == "ai_overview":
        from src.analysis import vertex_overview as ov
        try:
            sysov = ov.get_system()
        except RuntimeError as e:
            return "error", f"The saved AI evaluations could not be read: {e}", {}
        spend = ov.get_spend()
        figures = {"calls_today": spend.get("calls"), "cost_today_usd": spend.get("cost_usd")}
        if spend.get("capped"):
            return "degraded", f"Daily cap of {spend.get('daily_call_cap')} AI calls reached; overviews wait for tomorrow", figures
        if sysov.get("error") and not sysov.get("summary"):
            return "error", f"AI overview not written: {sysov['error']}", figures
        if sysov.get("error"):
            # readers keep the last good overview; the failed refresh is still a problem
            return "degraded", f"AI overview refresh failed ({sysov['error']}); the last good overview is shown", figures
        s, d = _fresh(sysov.get("analyzed_at"), ov.INTERVAL_S, "The AI overview")
        return s, d, figures
    if name == "ai_review":
        from src.analysis import ai_review
        st = ai_review.status()
        if st.get("error"):
            return "error", f"AI log review failed: {st['error']}", {}
        s, d = _fresh(st.get("reviewed_at"), st.get("interval_s") or interval, "The AI log review")
        return s, d, {}
    if name == "public_status":
        from src.collectors import statuspage
        with statuspage._lock:
            entries = dict(statuspage._cache)
        if not entries:
            return "not checked", "No public status page read yet", {}
        failed = [u for u, e in entries.items() if not e.get("data")]
        newest = max(e["at"] for e in entries.values())
        if failed:
            return "degraded", f"{len(failed)} of {len(entries)} public status pages could not be read", {"providers": len(entries)}
        s, d = _fresh(newest, interval, "Reading the public status pages")
        return s, d, {"providers": len(entries)}
    if name == "saved_state":
        from src.analysis import ai_review
        st = ai_review.status()
        if st.get("saved"):
            return "healthy", "Alarms that must survive a restart are saved", {}
        if st.get("saving_problem"):
            return "error", f"Alarms are not saved: {st['saving_problem']}", {}
        return "not checked", "Nothing saved yet since the start", {}
    return "not checked", f"Unknown GlassHood component {name!r}", {}
