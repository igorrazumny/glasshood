# File: tests/test_session_boot.py
# Purpose: REQ-GHA-018 clause 8 — a sleep ends login sessions. Tokens carry the
# process's boot id; a token from an earlier process is refused as session_ended,
# even when it has also expired, and the signature is always checked.

import time
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api.routes import auth as auth_routes


def _request(token: str) -> Request:
    return Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})


def _token(boot, exp_offset=600, secret=None, typ="access"):
    now = int(time.time())
    payload = {"sub": "u@example.com", "role": "viewer", "iat": now,
               "exp": now + exp_offset, "jti": "j", "type": typ}
    if boot is not None:
        payload["boot"] = boot
    return pyjwt.encode(payload, secret or auth_routes._jwt_secret(), algorithm="HS256")


@pytest.fixture(autouse=True)
def _no_auth0():
    with patch.object(auth_routes, "AUTH0_DOMAIN", ""):
        yield


def test_current_process_token_is_accepted():
    ctx = auth_routes.verify_token(_request(auth_routes._make_access_token("u@example.com", "viewer")))
    assert ctx["user"] == "u@example.com"


def test_token_from_an_earlier_process_is_session_ended():
    with pytest.raises(HTTPException) as e:
        auth_routes.verify_token(_request(_token("0000000000000000")))
    assert e.value.status_code == 401 and e.value.detail == auth_routes.SESSION_ENDED


def test_expired_token_from_an_earlier_process_is_session_ended_not_expired():
    with pytest.raises(HTTPException) as e:
        auth_routes.verify_token(_request(_token("0000000000000000", exp_offset=-7200)))
    assert e.value.detail == auth_routes.SESSION_ENDED


def test_token_without_boot_id_is_session_ended():
    with pytest.raises(HTTPException) as e:
        auth_routes.verify_token(_request(_token(None)))
    assert e.value.detail == auth_routes.SESSION_ENDED


def test_expired_token_from_this_process_keeps_ordinary_answer():
    with pytest.raises(HTTPException) as e:
        auth_routes.verify_token(_request(_token(auth_routes.BOOT_ID, exp_offset=-10)))
    assert e.value.detail == "Token expired"


def test_wrong_signature_is_invalid_even_with_matching_boot_id():
    with pytest.raises(HTTPException) as e:
        auth_routes.verify_token(_request(_token(auth_routes.BOOT_ID, secret="x" * 40)))
    assert e.value.detail == "Invalid token"


def test_refresh_token_from_an_earlier_process_is_session_ended():
    body = auth_routes.RefreshRequest(refresh_token=_token("0000000000000000", typ="refresh"))
    with pytest.raises(HTTPException) as e:
        auth_routes.refresh(body)
    assert e.value.detail == auth_routes.SESSION_ENDED


def test_refresh_from_this_process_still_works():
    rt = auth_routes._make_refresh_token("u@example.com", "viewer")
    out = auth_routes.refresh(auth_routes.RefreshRequest(refresh_token=rt))
    assert out["token"]
