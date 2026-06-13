# File: tests/test_ingest_processor.py
# Purpose: Tests for ingested event processing

from src.ingest.processor import (
    process_batch, get_recent_events, get_agent_status,
    get_audit_log, record_heartbeat, _events, _agent_heartbeats, _audit_log,
)


def _reset():
    _events.clear()
    _agent_heartbeats.clear()
    _audit_log.clear()


class TestProcessBatch:
    def setup_method(self):
        _reset()

    def test_accepts_valid_events(self):
        events = [
            {"source_id": "middleware-01", "message": "Connection established"},
            {"source_id": "sap-gw", "message": "RFC call completed", "severity": "info"},
        ]
        result = process_batch(events, "agent-alpha")
        assert result["accepted"] == 2
        assert result["rejected"] == 0

    def test_rejects_missing_source_id(self):
        events = [{"message": "no source"}]
        result = process_batch(events, "agent-1")
        assert result["rejected"] == 1
        assert "missing source_id" in result["errors"][0]

    def test_rejects_missing_message(self):
        events = [{"source_id": "node-1"}]
        result = process_batch(events, "agent-1")
        assert result["rejected"] == 1
        assert "missing message" in result["errors"][0]

    def test_rejects_invalid_source_type(self):
        events = [{"source_id": "x", "message": "m", "source_type": "invalid"}]
        result = process_batch(events, "agent-1")
        assert result["rejected"] == 1

    def test_rejects_invalid_severity(self):
        events = [{"source_id": "x", "message": "m", "severity": "fatal"}]
        result = process_batch(events, "agent-1")
        assert result["rejected"] == 1

    def test_mixed_valid_and_invalid(self):
        events = [
            {"source_id": "ok", "message": "good"},
            {"message": "no source"},
            {"source_id": "ok2", "message": "also good"},
        ]
        result = process_batch(events, "agent-1")
        assert result["accepted"] == 2
        assert result["rejected"] == 1

    def test_fills_default_timestamp(self):
        events = [{"source_id": "x", "message": "m"}]
        process_batch(events, "agent-1")
        recent = get_recent_events(limit=1)
        assert recent[0]["timestamp"] != ""

    def test_sets_agent_id_on_events(self):
        events = [{"source_id": "x", "message": "m"}]
        process_batch(events, "agent-beta")
        recent = get_recent_events(limit=1)
        assert recent[0]["agent_id"] == "agent-beta"


class TestGetRecentEvents:
    def setup_method(self):
        _reset()

    def test_returns_most_recent_first(self):
        process_batch([{"source_id": "a", "message": "first"}], "ag1")
        process_batch([{"source_id": "b", "message": "second"}], "ag1")
        events = get_recent_events(limit=10)
        assert events[0]["source_id"] == "b"
        assert events[1]["source_id"] == "a"

    def test_filters_by_source_type(self):
        process_batch([
            {"source_id": "a", "message": "m", "source_type": "syslog"},
            {"source_id": "b", "message": "m", "source_type": "file"},
        ], "ag1")
        events = get_recent_events(limit=10, source_type="syslog")
        assert len(events) == 1
        assert events[0]["source_type"] == "syslog"

    def test_respects_limit(self):
        events = [{"source_id": f"s{i}", "message": f"m{i}"} for i in range(10)]
        process_batch(events, "ag1")
        assert len(get_recent_events(limit=3)) == 3


class TestAgentStatus:
    def setup_method(self):
        _reset()

    def test_tracks_agent_heartbeat(self):
        process_batch([{"source_id": "x", "message": "m"}], "agent-1")
        status = get_agent_status()
        assert "agent-1" in status
        assert status["agent-1"]["total_events"] == 1
        assert "last_seen" in status["agent-1"]

    def test_accumulates_event_count(self):
        process_batch([{"source_id": "x", "message": "m"}], "agent-1")
        process_batch([{"source_id": "y", "message": "n"}], "agent-1")
        status = get_agent_status()
        assert status["agent-1"]["total_events"] == 2

    def test_record_heartbeat(self):
        record_heartbeat("agent-2", {"queue_depth": 42, "uptime": 3600})
        status = get_agent_status()
        assert status["agent-2"]["queue_depth"] == 42


class TestAuditLog:
    def setup_method(self):
        _reset()

    def test_records_batch_processing(self):
        process_batch([{"source_id": "x", "message": "m"}], "agent-1")
        log = get_audit_log()
        assert len(log) == 1
        assert log[0]["action"] == "batch_processed"
        assert log[0]["accepted"] == 1

    def test_most_recent_first(self):
        process_batch([{"source_id": "a", "message": "m"}], "ag1")
        process_batch([{"source_id": "b", "message": "m"}], "ag2")
        log = get_audit_log()
        assert log[0]["agent_id"] == "ag2"


class TestRingBuffer:
    def setup_method(self):
        _reset()

    def test_maxlen_respected(self):
        events = [{"source_id": f"s{i}", "message": f"m{i}"} for i in range(5005)]
        process_batch(events, "ag1")
        assert len(get_recent_events(limit=10000)) == 5000
