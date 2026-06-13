# File: tests/test_agent_webhook.py
# Purpose: Tests for HTTP webhook collector

import json
import queue
import threading
import time
import urllib.request

from agent.collectors.webhook import WebhookCollector


def _start_webhook(port, q):
    """Start webhook collector in background thread, return collector."""
    wh = WebhookCollector(q, bind_port=port)
    t = threading.Thread(target=wh.run, daemon=True)
    t.start()
    time.sleep(0.2)  # let server bind
    return wh


class TestWebhookCollector:
    def test_accepts_valid_json_post(self):
        q = queue.Queue()
        port = 19515
        wh = _start_webhook(port, q)
        try:
            data = json.dumps({"source_id": "sap-gw", "message": "RFC completed", "severity": "info"})
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=data.encode(),
                                        headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req)
            assert resp.status == 200

            event = q.get(timeout=1)
            assert event["source_type"] == "webhook"
            assert event["source_id"] == "sap-gw"
            assert event["message"] == "RFC completed"
        finally:
            wh.stop()

    def test_rejects_invalid_json(self):
        q = queue.Queue()
        port = 19516
        wh = _start_webhook(port, q)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=b"not json",
                                        headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req)
            except urllib.error.HTTPError as e:
                assert e.code == 400
            assert q.empty()
        finally:
            wh.stop()

    def test_uses_sender_ip_as_default_source_id(self):
        q = queue.Queue()
        port = 19517
        wh = _start_webhook(port, q)
        try:
            data = json.dumps({"message": "hello"})
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=data.encode(),
                                        headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req)
            event = q.get(timeout=1)
            assert event["source_id"] == "127.0.0.1"
        finally:
            wh.stop()

    def test_get_returns_ready(self):
        q = queue.Queue()
        port = 19518
        wh = _start_webhook(port, q)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            body = json.loads(resp.read())
            assert body["status"] == "ready"
        finally:
            wh.stop()

    def test_default_severity_is_info(self):
        q = queue.Queue()
        port = 19519
        wh = _start_webhook(port, q)
        try:
            data = json.dumps({"source_id": "app", "message": "event"})
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=data.encode(),
                                        headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req)
            event = q.get(timeout=1)
            assert event["severity"] == "info"
        finally:
            wh.stop()
