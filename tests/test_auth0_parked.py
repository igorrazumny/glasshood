"""REQ-GHA-017: Auth0 is parked — off by default, never contacted while off,
and the login screen offers only the sign-ins that work."""

import importlib
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest

import src.config.settings as settings
import src.api.routes.auth as auth_routes

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"


@pytest.fixture
def no_auth0_env(monkeypatch):
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    yield
    importlib.reload(settings)


def _rs256_token_with_kid() -> str:
    # Shaped like an Auth0 or Google token: RS256 header carrying a key id.
    # The signature is junk; only the header decides which validators are tried.
    header = '{"alg":"RS256","kid":"k1","typ":"JWT"}'
    seg = lambda s: pyjwt.utils.base64url_encode(s.encode()).decode()
    return f"{seg(header)}.{seg('{}')}.{seg('sig')}"


def _request(token: str):
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}
    return req


def test_auth0_is_off_by_default(no_auth0_env):
    importlib.reload(settings)
    assert settings.AUTH0_DOMAIN == ""


def test_backend_never_reaches_auth0_while_off(no_auth0_env):
    # Patch in place: reloading the auth routes would replace session state
    # that other test modules hold references to.
    importlib.reload(settings)
    with patch.object(auth_routes, "AUTH0_DOMAIN", settings.AUTH0_DOMAIN), \
         patch("src.auth.auth0_handler.get_auth0_handler") as handler, \
         patch("src.auth.auth0_handler.requests.get") as auth0_http, \
         patch("httpx.get", side_effect=RuntimeError("no network in tests")):
        try:
            auth_routes.verify_token(_request(_rs256_token_with_kid()))
        except Exception:
            pass  # rejected by the remaining validators; that is fine here
        handler.assert_not_called()
        auth0_http.assert_not_called()


def test_backend_still_uses_auth0_when_configured(no_auth0_env):
    fake = MagicMock()
    fake.validate_token.return_value = {"sub": "auth0|1", "email": "a@example.test"}
    with patch.object(auth_routes, "AUTH0_DOMAIN", "tenant.example.test"), \
         patch("src.auth.auth0_handler.get_auth0_handler", return_value=fake):
        ctx = auth_routes.verify_token(_request(_rs256_token_with_kid()))
    assert ctx["user"] == "a@example.test"


def _read(rel: str) -> str:
    return (FRONTEND / rel).read_text()


def test_only_the_wrapper_talks_to_the_auth0_sdk():
    users = [p.relative_to(FRONTEND).as_posix() for p in FRONTEND.rglob("*.jsx")
             if "@auth0/auth0-react" in p.read_text()]
    assert users == ["components/Auth0ProviderWrapper.jsx"]


def test_wrapper_skips_the_provider_and_hook_while_off():
    src = _read("components/Auth0ProviderWrapper.jsx")
    assert re.search(r"if \(!auth0Config\.enabled\) return children", src)
    assert re.search(r"if \(!auth0Config\.enabled\) return AUTH0_OFF", src)
    off = re.search(r"const AUTH0_OFF = \{(.*?)\n\}", src, re.S).group(1)
    assert "isLoading: false" in off and "isAuthenticated: false" in off


def test_login_screen_shows_sso_only_when_enabled():
    src = _read("components/LoginScreen.jsx")
    gate = src.index("{ssoEnabled && (")
    assert gate < src.index("Sign in with Corporate SSO") < src.rindex("Live demo")
    assert "loginWithRedirect()" in src[gate:src.rindex("Live demo")]


def test_flag_defaults_off():
    src = _read("config/auth0Flag.js")
    assert "env?.VITE_AUTH0_ENABLED === 'true'" in src
    assert "enabled: isAuth0Enabled(import.meta.env)" in _read("config/auth0.js")
