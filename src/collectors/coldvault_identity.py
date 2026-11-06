# File: src/collectors/coldvault_identity.py
# Purpose: GlassHood's own short-lived identity token for ColdVault /api/metrics (REQ-GHA-025)
#
# GlassHood's Azure managed identity is exchanged by Google Workload Identity
# Federation for a federated token; that token asks Google for an ID token of the
# ColdVault metrics account, for exactly one audience. No key is stored anywhere.
# The token is never logged or returned to a caller other than the collector.

import json
import os
import threading

from src.config.settings import COLDVAULT_URL, COLDVAULT_METRICS_SA

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_lock = threading.Lock()
_creds = None


class IdentityNotConfigured(Exception):
    """The deployment does not name a cred config or a metrics account."""


def audience() -> str:
    """The one audience the token is valid for."""
    return f"{COLDVAULT_URL.rstrip('/')}/api/metrics"


def _build():
    import google.auth
    from google.auth import impersonated_credentials

    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not path or not COLDVAULT_METRICS_SA:
        raise IdentityNotConfigured("no ColdVault metrics identity configured")
    with open(path) as f:
        info = json.load(f)
    # The cred config impersonates GlassHood's log reader; the metrics token is
    # granted to the pool principal itself, so use the federated token directly.
    info.pop("service_account_impersonation_url", None)
    info.pop("service_account_impersonation", None)
    source, _ = google.auth.load_credentials_from_dict(info, scopes=[_SCOPE])
    target = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=COLDVAULT_METRICS_SA,
        target_scopes=[_SCOPE],
    )
    return impersonated_credentials.IDTokenCredentials(
        target, target_audience=audience(), include_email=True,
    )


def id_token() -> str:
    """Return a valid ID token, refreshing it when it has expired. Blocking."""
    global _creds
    from google.auth.transport.requests import Request

    with _lock:
        if _creds is None:
            _creds = _build()
        if not _creds.valid:
            _creds.refresh(Request())
        return _creds.token
