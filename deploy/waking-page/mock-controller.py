#!/usr/bin/env python3
"""Local stand-in for the wake controller and app.glasshood.ai (REQ-GHA-018 clause 6), for
checking the waking page (index.html, next to this file) in a browser. Not deployed: the
real controller replaces it.

Usage:
  python3 deploy/waking-page/mock-controller.py [--port 8790] [--wake 20] [--app-lag 0]
                                                 [--scenario normal|fail|sleeping]

Two origins, so the page's calls are cross-origin as they will be:
  http://127.0.0.1:PORT      the app's site. /waking-page/ serves the page, with CONTROLLER
                             set to the second origin. Any other path is a stand-in app page
                             naming that path once the app is awake; before that it redirects
                             to /waking-page/?next=<path>, as the app does for a visitor who
                             arrives while it is asleep.
  http://127.0.0.1:PORT+1    the wake controller, with CORS for the app's site:
                             GET /status  200 {"state", "since", "expected_seconds"}, no-store
                             POST /wake   202, the same JSON; repeated posts cause one wake
                             GET /_mock/stats  counters for tests
Scenarios: normal wakes after --wake seconds; fail never becomes awake; sleeping starts in
"going-to-sleep" for 5 s and runs a wake posted meanwhile as soon as the sleep ends.
--app-lag N keeps sending visitors back to the waking page for N seconds after the
status reads "awake", like an app that has not caught up yet.
--first-status changes only the first status request: hang-headers never answers,
hang-body sends the headers and part of the body and then stops, late:N answers after
N seconds with the state at that moment.
"""
import argparse
import html
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

PAGE = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
WAKING_PATH = "/waking-page/"
SLEEP_SECONDS = 5
HANG_SECONDS = 600


class Wake:
    def __init__(self, scenario, wake_seconds, app_lag, first_status=None):
        self.lock = threading.Lock()
        self.first_status = first_status
        self.scenario = scenario
        self.wake_seconds = wake_seconds
        self.app_lag = app_lag
        self.stats = {"posts": 0, "wakes": 0, "status_checks": 0, "waking_pages": 0, "sent_back": 0, "app_pages": 0}
        self.page_times = []
        self.queued = False
        self.state = "going-to-sleep" if scenario == "sleeping" else "asleep"
        self.since = self.t0 = time.time()

    def _advance(self):  # the caller holds the lock
        t = time.time()
        if self.state == "going-to-sleep" and t - self.since >= SLEEP_SECONDS:
            self.state, self.since = "asleep", t
            if self.queued:
                self.queued = False
                self._start(t)
        if self.state == "waking" and self.scenario != "fail" and t - self.since >= self.wake_seconds:
            self.state, self.since = "awake", t

    def _start(self, t):
        self.state, self.since = "waking", t
        self.stats["wakes"] += 1

    def _json(self):
        return {
            "state": self.state,
            "since": datetime.fromtimestamp(self.since, timezone.utc).isoformat().replace("+00:00", "Z"),
            "expected_seconds": None if self.state == "awake" else self.wake_seconds,
        }

    def post(self):
        with self.lock:
            self.stats["posts"] += 1
            self._advance()
            if self.state == "asleep":
                self._start(time.time())
            elif self.state == "going-to-sleep":
                self.queued = True
            return self._json()

    def take_first_status(self):
        """The --first-status mode for the first status request; None after that."""
        with self.lock:
            mode, self.first_status = self.first_status, None
            return mode

    def status(self):
        with self.lock:
            self.stats["status_checks"] += 1
            self._advance()
            return self._json()

    def waking_page_served(self):
        with self.lock:
            self.stats["waking_pages"] += 1
            self.page_times.append(round(time.time() - self.t0, 2))

    def app_ready(self):
        """True once the app is awake and has caught up (--app-lag)."""
        with self.lock:
            self._advance()
            ready = self.state == "awake" and time.time() - self.since >= self.app_lag
            self.stats["app_pages" if ready else "sent_back"] += 1
            return ready

    def counters(self):
        with self.lock:
            return dict(self.stats, page_times=list(self.page_times))


class Base(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class Controller(Base):
    def _cors(self):
        return {"Access-Control-Allow-Origin": APP_ORIGIN, "Vary": "Origin"}

    def _json(self, code, data):
        self._send(code, json.dumps(data).encode(), "application/json", self._cors())

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain", dict(self._cors(), **{
            "Access-Control-Allow-Methods": "GET, POST",
            "Access-Control-Allow-Headers": "Cache-Control, Pragma",
            "Access-Control-Max-Age": "600"}))

    def do_POST(self):
        if urlsplit(self.path).path == "/wake":
            self._json(202, WAKE.post())
        else:
            self._send(404, b"not found", "text/plain", self._cors())

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/status":
            mode = WAKE.take_first_status()
            if mode == "hang-headers":
                time.sleep(HANG_SECONDS)
                return
            if mode == "hang-body":
                body = json.dumps(WAKE.status()).encode()
                self.send_response(200)
                for k, v in dict(self._cors(), **{"Content-Type": "application/json", "Cache-Control": "no-store",
                                                  "Content-Length": str(len(body))}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body[:5])
                self.wfile.flush()
                time.sleep(HANG_SECONDS)
                return
            if mode and mode.startswith("late:"):
                time.sleep(float(mode[5:]))
            self._json(200, WAKE.status())
        elif path == "/_mock/stats":
            self._json(200, WAKE.counters())
        else:
            self._send(404, b"not found", "text/plain", self._cors())


class App(Base):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == WAKING_PATH:
            WAKE.waking_page_served()
            page = PAGE.replace('var CONTROLLER = "";', 'var CONTROLLER = "%s";' % CONTROLLER_ORIGIN, 1)
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif WAKE.app_ready():
            body = "<!doctype html><title>GlassHood app (mock)</title><p>App page: <code>%s</code></p>" % html.escape(self.path)
            self._send(200, body.encode(), "text/html; charset=utf-8")
        else:
            self._send(302, b"", "text/plain", {"Location": WAKING_PATH + "?next=" + quote(self.path, safe="")})


def main():
    global WAKE, APP_ORIGIN, CONTROLLER_ORIGIN
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--wake", type=float, default=20, help="seconds from wake to awake")
    p.add_argument("--app-lag", type=float, default=0, help="seconds the app keeps sending visitors back after awake")
    p.add_argument("--scenario", choices=("normal", "fail", "sleeping"), default="normal")
    p.add_argument("--first-status", help="hang-headers, hang-body or late:SECONDS, for the first status request only")
    a = p.parse_args()
    if a.first_status and a.first_status not in ("hang-headers", "hang-body") and not a.first_status.startswith("late:"):
        p.error("--first-status: hang-headers, hang-body or late:SECONDS")
    WAKE = Wake(a.scenario, a.wake, a.app_lag, a.first_status)
    APP_ORIGIN = "http://127.0.0.1:%d" % a.port
    CONTROLLER_ORIGIN = "http://127.0.0.1:%d" % (a.port + 1)
    controller = ThreadingHTTPServer(("127.0.0.1", a.port + 1), Controller)
    threading.Thread(target=controller.serve_forever, daemon=True).start()
    print("app %s (try %s/demo), controller %s, scenario %s" % (APP_ORIGIN, APP_ORIGIN, CONTROLLER_ORIGIN, a.scenario), flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), App).serve_forever()


if __name__ == "__main__":
    main()
