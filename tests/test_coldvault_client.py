# File: tests/test_coldvault_client.py
# Purpose: Tests for ColdVault API analysis client

import json
import time
from unittest.mock import patch, MagicMock

import pytest


def _reset_module():
    """Reset module globals between tests."""
    import src.analysis.coldvault_client as mod
    mod._cached_analysis = {
        "score": None, "summary": "", "issues": [],
        "recommendations": [], "timestamp": None, "stale": True,
    }
    mod._last_run = 0


class TestParseResponse:
    def test_plain_json(self):
        from src.analysis.coldvault_client import _parse_response
        raw = '{"score": 8, "summary": "All good", "issues": [], "recommendations": []}'
        result = _parse_response(raw)
        assert result["score"] == 8
        assert result["summary"] == "All good"

    def test_markdown_wrapped_json(self):
        from src.analysis.coldvault_client import _parse_response
        raw = '```json\n{"score": 7, "summary": "OK", "issues": [], "recommendations": []}\n```'
        result = _parse_response(raw)
        assert result["score"] == 7

    def test_json_with_surrounding_text(self):
        from src.analysis.coldvault_client import _parse_response
        raw = 'Here is the analysis:\n{"score": 6, "summary": "Degraded", "issues": ["High CPU"], "recommendations": []}\nEnd.'
        result = _parse_response(raw)
        assert result["score"] == 6
        assert result["issues"] == ["High CPU"]

    def test_invalid_json_raises(self):
        from src.analysis.coldvault_client import _parse_response
        with pytest.raises(json.JSONDecodeError):
            _parse_response("not json at all")


@patch("src.analysis.coldvault_client.PLATFORM_KEY", "")
class TestAnalyze:
    def setup_method(self):
        _reset_module()

    @patch("src.analysis.coldvault_client.COLDVAULT_API_KEY", "test-key")
    @patch("src.analysis.coldvault_client._stream_coldvault")
    def test_fast_mode_high_score(self, mock_call):
        from src.analysis.coldvault_client import analyze
        mock_call.return_value = '{"score": 9, "summary": "Healthy", "issues": [], "recommendations": []}'
        result = analyze({"nodes": []})
        assert result["score"] == 9
        assert result["stale"] is False
        mock_call.assert_called_once()

    @patch("src.analysis.coldvault_client.COLDVAULT_API_KEY", "test-key")
    @patch("src.analysis.coldvault_client._call_debate")
    @patch("src.analysis.coldvault_client._stream_coldvault")
    def test_escalation_on_low_score(self, mock_fast, mock_debate):
        from src.analysis.coldvault_client import analyze
        mock_fast.return_value = '{"score": 3, "summary": "Critical", "issues": ["Down"], "recommendations": []}'
        mock_debate.return_value = '{"score": 3, "summary": "Confirmed critical", "issues": ["VM down"], "recommendations": ["Restart"]}'
        result = analyze({"nodes": []})
        assert result["score"] == 3
        assert result["summary"] == "Confirmed critical"
        mock_debate.assert_called_once()

    @patch("src.analysis.coldvault_client.COLDVAULT_API_KEY", "test-key")
    @patch("src.analysis.coldvault_client._stream_coldvault")
    def test_no_escalation_above_threshold(self, mock_call):
        from src.analysis.coldvault_client import analyze
        mock_call.return_value = '{"score": 7, "summary": "OK", "issues": [], "recommendations": []}'
        with patch("src.analysis.coldvault_client._call_debate") as mock_debate:
            analyze({"nodes": []})
            mock_debate.assert_not_called()

    @patch("src.analysis.coldvault_client.COLDVAULT_API_KEY", "")
    def test_no_api_key(self):
        from src.analysis.coldvault_client import analyze
        result = analyze({"nodes": []})
        assert result["score"] is None
        assert "No API key" in result["summary"] or "not configured" in result["summary"]

    @patch("src.analysis.coldvault_client.COLDVAULT_API_KEY", "test-key")
    @patch("src.analysis.coldvault_client._stream_coldvault", side_effect=Exception("Connection refused"))
    def test_unreachable_no_cache(self, mock_call):
        from src.analysis.coldvault_client import analyze
        result = analyze({"nodes": []})
        assert result["score"] is None
        assert "unreachable" in result["summary"]
        assert result["stale"] is True

    @patch("src.analysis.coldvault_client.COLDVAULT_API_KEY", "test-key")
    @patch("src.analysis.coldvault_client._stream_coldvault")
    def test_unreachable_serves_stale_cache(self, mock_call):
        from src.analysis.coldvault_client import analyze
        # First call succeeds
        mock_call.return_value = '{"score": 8, "summary": "Good", "issues": [], "recommendations": []}'
        analyze({"nodes": []})
        # Second call fails — should serve stale
        mock_call.side_effect = Exception("timeout")
        result = analyze({"nodes": []})
        assert result["score"] == 8
        assert result["stale"] is True


@patch("src.analysis.coldvault_client.PLATFORM_KEY", "")
class TestCanRefresh:
    def setup_method(self):
        _reset_module()

    def test_can_refresh_initially(self):
        from src.analysis.coldvault_client import can_refresh
        assert can_refresh() is True

    @patch("src.analysis.coldvault_client.COLDVAULT_API_KEY", "test-key")
    @patch("src.analysis.coldvault_client._stream_coldvault")
    def test_cannot_refresh_after_recent_run(self, mock_call):
        from src.analysis.coldvault_client import analyze, can_refresh
        mock_call.return_value = '{"score": 9, "summary": "OK", "issues": [], "recommendations": []}'
        analyze({"nodes": []})
        assert can_refresh() is False
