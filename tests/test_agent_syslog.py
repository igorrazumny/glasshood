# File: tests/test_agent_syslog.py
# Purpose: Tests for RFC 5424 syslog parser and receiver

import queue
import socket
import threading
import time

from agent.collectors.parsers import parse_rfc5424
from agent.collectors.syslog_receiver import SyslogReceiver


class TestParseRfc5424:
    def test_parses_full_message(self):
        raw = b"<134>1 2026-03-09T10:30:00Z middleware01 sapgw 1234 - - Connection established"
        result = parse_rfc5424(raw)
        assert result is not None
        assert result["severity"] == "info"  # 134 & 7 = 6 = info
        assert result["hostname"] == "middleware01"
        assert result["app_name"] == "sapgw"
        assert result["message"] == "Connection established"

    def test_parses_critical_severity(self):
        # PRI = facility*8 + severity. facility=1 (user), severity=2 (critical) = 10
        raw = b"<10>1 2026-03-09T10:30:00Z host1 app - - - Critical failure"
        result = parse_rfc5424(raw)
        assert result["severity"] == "critical"

    def test_parses_warning(self):
        # facility=1, severity=4 (warning) = 12
        raw = b"<12>1 2026-03-09T10:30:00Z host1 app - - - Disk space low"
        result = parse_rfc5424(raw)
        assert result["severity"] == "warning"

    def test_parses_bsd_style(self):
        raw = b"<13>Mar  9 10:30:00 host1 kernel: OOM killer invoked"
        result = parse_rfc5424(raw)
        assert result is not None
        assert "OOM killer" in result["message"]
        assert result["severity"] == "notice"  # 13 & 7 = 5 = notice

    def test_handles_nil_fields(self):
        raw = b"<134>1 - - - - - - Plain message"
        result = parse_rfc5424(raw)
        assert result is not None
        assert result["hostname"] == ""
        assert result["message"] == "Plain message"

    def test_returns_none_for_empty(self):
        assert parse_rfc5424(b"") is None
        assert parse_rfc5424(b"   ") is None

    def test_returns_none_for_garbage(self):
        assert parse_rfc5424(b"not a syslog message") is None

    def test_handles_unicode(self):
        raw = "<134>1 2026-03-09T10:30:00Z host app - - - Ümlauts äöü".encode("utf-8")
        result = parse_rfc5424(raw)
        assert "Ümlauts" in result["message"]

    def test_extracts_facility(self):
        # PRI=134: facility=16 (local0), severity=6 (info)
        raw = b"<134>1 - host app - - - msg"
        result = parse_rfc5424(raw)
        assert result["facility"] == 16


class TestSyslogReceiver:
    def test_receives_udp_message(self):
        q = queue.Queue()
        # Use a random high port to avoid conflicts
        port = 19514
        receiver = SyslogReceiver(q, bind_port=port)
        t = threading.Thread(target=receiver.run, daemon=True)
        t.start()
        time.sleep(0.1)  # let socket bind

        # Send a syslog message via UDP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"<134>1 2026-03-09T10:30:00Z testhost myapp - - - Test message", ("127.0.0.1", port))
        sock.close()

        time.sleep(0.2)
        receiver.stop()

        assert not q.empty()
        event = q.get_nowait()
        assert event["source_type"] == "syslog"
        assert event["source_id"] == "testhost"
        assert event["message"] == "Test message"
        assert event["severity"] == "info"
