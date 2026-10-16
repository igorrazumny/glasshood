"""REQ-GHA-016: background cadence comes from one configurable interval, and
AI analysis never calls a platform host unless one is explicitly configured."""

import importlib
import time
from unittest.mock import patch

import pytest

import src.config.settings as settings
import src.collectors.gcs_bucket as gcs_bucket
import src.collectors.manifest_metrics as manifest_metrics
import src.collectors.coldvault as coldvault
import src.analysis.coldvault_client as coldvault_client

_ENV_VARS = ("BACKGROUND_POLL_INTERVAL", "DISCOVERY_INTERVAL", "PLATFORM_URL")


def _reload_all():
    importlib.reload(settings)
    for mod in (gcs_bucket, manifest_metrics, coldvault, coldvault_client):
        importlib.reload(mod)


@pytest.fixture
def clean_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    _reload_all()


def test_default_cadence_is_ten_minutes_for_every_loop(clean_env):
    _reload_all()
    assert settings.BACKGROUND_POLL_INTERVAL == 600
    assert settings.COLDVAULT_POLL_INTERVAL == 600
    assert settings.GCP_POLL_INTERVAL == 600
    assert settings.ANALYSIS_INTERVAL == 600
    assert settings.DISCOVERY_INTERVAL == 600
    assert gcs_bucket.POLL_INTERVAL == 600
    assert manifest_metrics._POLL_INTERVAL == 600


def test_cadence_is_set_from_configuration(clean_env):
    clean_env.setenv("BACKGROUND_POLL_INTERVAL", "60")
    _reload_all()
    assert settings.COLDVAULT_POLL_INTERVAL == 60
    assert settings.GCP_POLL_INTERVAL == 60
    assert settings.ANALYSIS_INTERVAL == 60
    assert settings.DISCOVERY_INTERVAL == 60
    assert gcs_bucket.POLL_INTERVAL == 60
    assert manifest_metrics._POLL_INTERVAL == 60


def test_explicit_discovery_interval_still_wins(clean_env):
    clean_env.setenv("DISCOVERY_INTERVAL", "1800")
    _reload_all()
    assert settings.DISCOVERY_INTERVAL == 1800
    assert settings.COLDVAULT_POLL_INTERVAL == 600


@pytest.mark.parametrize("bad", ["0", "-30", "ten", "", "1.5"])
def test_invalid_interval_fails_loudly(clean_env, bad):
    clean_env.setenv("BACKGROUND_POLL_INTERVAL", bad)
    with pytest.raises(ValueError, match="BACKGROUND_POLL_INTERVAL"):
        importlib.reload(settings)


def test_staleness_follows_the_configured_interval(clean_env):
    _reload_all()
    # One and a half intervals since the last poll: late, but not missed twice.
    with patch.object(coldvault, "_last_poll", time.time() - 900):
        assert coldvault.is_stale() is False
    with patch.object(coldvault, "_last_poll", time.time() - 1300):
        assert coldvault.is_stale() is True


def test_manifest_nodes_report_the_configured_interval(clean_env):
    _reload_all()
    assert manifest_metrics.metrics_loop.__defaults__ == (600,)


def test_platform_has_no_default_host(clean_env):
    _reload_all()
    assert coldvault_client.PLATFORM_URL == ""


def test_key_without_url_never_calls_the_platform(clean_env):
    _reload_all()
    with patch.object(coldvault_client, "PLATFORM_KEY", "a-key"), \
         patch.object(coldvault_client, "COLDVAULT_API_KEY", ""), \
         patch.object(coldvault_client.httpx, "post") as post:
        coldvault_client.analyze({"nodes": [], "edges": []})
        post.assert_not_called()
    with pytest.raises(ValueError, match="PLATFORM_URL"):
        coldvault_client._call_platform("hello")


def test_platform_path_needs_both_url_and_key(clean_env):
    _reload_all()
    cases = [("", ""), ("https://x.test", ""), ("", "k"), ("https://x.test", "k")]
    for url, key in cases:
        with patch.object(coldvault_client, "PLATFORM_URL", url), \
             patch.object(coldvault_client, "PLATFORM_KEY", key):
            assert coldvault_client._platform_enabled() is bool(url and key)
