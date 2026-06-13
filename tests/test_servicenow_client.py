# File: tests/test_servicenow_client.py
# Purpose: Tests for ServiceNow API client — all external calls mocked

from unittest.mock import patch, MagicMock

from src.integrations.servicenow import ServiceNowClient, _load_config


class TestServiceNowClientAvailability:
    def test_unavailable_when_no_url(self):
        client = ServiceNowClient("", "user", "pass")
        assert client.available is False

    def test_unavailable_when_no_auth(self):
        client = ServiceNowClient("https://snow.example.com", "", "")
        assert client.available is False

    def test_available_when_configured(self):
        client = ServiceNowClient("https://snow.example.com", "user", "pass")
        assert client.available is True

    def test_trailing_slash_stripped(self):
        client = ServiceNowClient("https://snow.example.com/", "u", "p")
        assert client.base_url == "https://snow.example.com"


class TestUnavailableReturns:
    """When client is not available, methods return safe defaults."""

    def _client(self):
        return ServiceNowClient("", "", "")

    def test_fetch_incidents_returns_empty(self):
        assert self._client().fetch_incidents("2026-01-01", ["sys_id"]) == []

    def test_fetch_changes_returns_empty(self):
        assert self._client().fetch_changes("2026-01-01", ["sys_id"]) == []

    def test_create_incident_returns_none(self):
        assert self._client().create_incident({"desc": "test"}) is None

    def test_resolve_incident_returns_false(self):
        assert self._client().resolve_incident("abc", "done") is False


class TestWithMocks:
    def _client(self):
        return ServiceNowClient("https://snow.example.com", "user", "pass")

    @patch("src.integrations.servicenow.httpx.get")
    def test_fetch_incidents_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": [
            {"sys_id": "abc", "number": "INC0001001", "state": "1"}
        ]}
        mock_get.return_value = mock_resp

        result = self._client().fetch_incidents("2026-01-01", ["sys_id", "number"])
        assert len(result) == 1
        assert result[0]["sys_id"] == "abc"
        mock_get.assert_called_once()

    @patch("src.integrations.servicenow.httpx.get")
    def test_fetch_incidents_http_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("503")
        mock_get.return_value = mock_resp

        result = self._client().fetch_incidents("2026-01-01", ["sys_id"])
        assert result == []

    @patch("src.integrations.servicenow.httpx.get")
    def test_fetch_changes_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": [
            {"sys_id": "chg1", "number": "CHG0001", "state": "3"}
        ]}
        mock_get.return_value = mock_resp

        result = self._client().fetch_changes("2026-01-01", ["sys_id"])
        assert len(result) == 1
        assert result[0]["sys_id"] == "chg1"

    @patch("src.integrations.servicenow.httpx.post")
    def test_create_incident_returns_sys_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"sys_id": "xyz789"}}
        mock_post.return_value = mock_resp

        sys_id = self._client().create_incident({"short_description": "test"})
        assert sys_id == "xyz789"

    @patch("src.integrations.servicenow.httpx.post")
    def test_create_incident_http_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("400 Bad Request")
        mock_post.return_value = mock_resp

        assert self._client().create_incident({"desc": "fail"}) is None

    @patch("src.integrations.servicenow.httpx.patch")
    def test_resolve_incident_success(self, mock_patch):
        mock_resp = MagicMock()
        mock_patch.return_value = mock_resp

        result = self._client().resolve_incident("xyz789", "GlassHood resolved")
        assert result is True

    @patch("src.integrations.servicenow.httpx.patch")
    def test_resolve_incident_error(self, mock_patch):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404")
        mock_patch.return_value = mock_resp

        assert self._client().resolve_incident("bad_id", "n/a") is False


class TestLoadConfig:
    def test_missing_file_returns_empty(self):
        with patch("src.integrations.servicenow.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            result = _load_config()
        assert result == {}
