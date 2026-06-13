# File: tests/test_agent_heartbeat.py
# Purpose: Tests for agent heartbeat sender

from unittest.mock import patch, MagicMock

from agent.heartbeat import HeartbeatSender


class TestHeartbeatSender:
    def test_sends_agent_id(self):
        mock_client = MagicMock()
        with patch("agent.heartbeat.httpx.Client", return_value=mock_client):
            hb = HeartbeatSender("http://localhost:8080", "key", "agent-1")
            hb._send()
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"]["agent_id"] == "agent-1"
        assert call_kwargs.kwargs["headers"]["X-API-Key"] == "key"

    def test_includes_status_from_callback(self):
        mock_client = MagicMock()
        status_fn = lambda: {"queue_depth": 42, "events_pushed": 100}
        with patch("agent.heartbeat.httpx.Client", return_value=mock_client):
            hb = HeartbeatSender("http://localhost:8080", "key", "agent-1",
                                 get_status_fn=status_fn)
            hb._send()
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["queue_depth"] == 42

    def test_handles_connection_error(self):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("connection refused")
        with patch("agent.heartbeat.httpx.Client", return_value=mock_client):
            hb = HeartbeatSender("http://localhost:8080", "key", "agent-1")
            hb._send()  # should not raise
