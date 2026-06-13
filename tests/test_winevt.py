# File: tests/test_winevt.py
# Purpose: Tests for Windows Event Log collector (XML parsing, event generation)

import queue
import unittest
from unittest.mock import patch, MagicMock

from agent.collectors.winevt import _parse_event_xml, WinEventCollector, _LEVEL_MAP


SAMPLE_EVENT_XML = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-Windows-Security-Auditing"/>
    <EventID>4624</EventID>
    <Level>4</Level>
    <TimeCreated SystemTime="2026-03-12T01:00:00.000Z"/>
    <Channel>Security</Channel>
    <Computer>PHARMA-SRV01</Computer>
  </System>
  <EventData>
    <Data>User logon</Data>
    <Data>DOMAIN\\admin</Data>
  </EventData>
</Event>"""


class TestParseEventXml(unittest.TestCase):
    """XML parsing of Windows Event Log records."""

    def test_parses_valid_event(self):
        result = _parse_event_xml(SAMPLE_EVENT_XML)
        self.assertIsNotNone(result)
        self.assertEqual(result["source_type"], "winevt")
        self.assertEqual(result["source_id"], "Security")
        self.assertEqual(result["severity"], "info")
        self.assertIn("PHARMA-SRV01", result["tags"]["computer"])

    def test_extracts_event_data(self):
        result = _parse_event_xml(SAMPLE_EVENT_XML)
        self.assertIn("User logon", result["message"])
        self.assertIn("DOMAIN\\admin", result["message"])

    def test_extracts_tags(self):
        result = _parse_event_xml(SAMPLE_EVENT_XML)
        self.assertEqual(result["tags"]["event_id"], "4624")
        self.assertEqual(result["tags"]["provider"], "Microsoft-Windows-Security-Auditing")
        self.assertEqual(result["tags"]["channel"], "Security")

    def test_timestamp(self):
        result = _parse_event_xml(SAMPLE_EVENT_XML)
        self.assertEqual(result["timestamp"], "2026-03-12T01:00:00.000Z")

    def test_invalid_xml_returns_none(self):
        result = _parse_event_xml("<broken>")
        self.assertIsNone(result)

    def test_no_system_element_returns_none(self):
        xml = '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><Other/></Event>'
        result = _parse_event_xml(xml)
        self.assertIsNone(result)

    def test_level_mapping(self):
        self.assertEqual(_LEVEL_MAP["1"], "critical")
        self.assertEqual(_LEVEL_MAP["2"], "error")
        self.assertEqual(_LEVEL_MAP["3"], "warning")
        self.assertEqual(_LEVEL_MAP["4"], "info")

    def test_missing_event_data_uses_event_id(self):
        xml = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
          <System>
            <EventID>1234</EventID>
            <Level>4</Level>
            <TimeCreated SystemTime="2026-03-12T01:00:00Z"/>
            <Channel>Application</Channel>
            <Computer>SRV</Computer>
          </System>
        </Event>"""
        result = _parse_event_xml(xml)
        self.assertIn("EventID=1234", result["message"])


class TestWinEventCollector(unittest.TestCase):
    """WinEventCollector query and queue behavior."""

    def test_default_channels(self):
        eq = queue.Queue()
        c = WinEventCollector(eq)
        self.assertEqual(c._channels, ["Application", "System", "Security"])

    def test_custom_channels(self):
        eq = queue.Queue()
        c = WinEventCollector(eq, channels=["Setup"])
        self.assertEqual(c._channels, ["Setup"])

    @patch("agent.collectors.winevt.subprocess.run")
    def test_query_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=SAMPLE_EVENT_XML, stderr="",
        )
        eq = queue.Queue()
        c = WinEventCollector(eq)
        events = c._query_events("Security")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_id"], "Security")

    @patch("agent.collectors.winevt.subprocess.run")
    def test_query_empty_on_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="channel not found",
        )
        eq = queue.Queue()
        c = WinEventCollector(eq)
        events = c._query_events("Nonexistent")
        self.assertEqual(events, [])

    @patch("agent.collectors.winevt.subprocess.run", side_effect=FileNotFoundError)
    def test_query_no_wevtutil(self, mock_run):
        eq = queue.Queue()
        c = WinEventCollector(eq)
        events = c._query_events("Application")
        self.assertEqual(events, [])

    def test_stop(self):
        eq = queue.Queue()
        c = WinEventCollector(eq)
        c.stop()
        self.assertTrue(c._stop.is_set())
