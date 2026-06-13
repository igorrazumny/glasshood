# File: src/auth/auth0_handler.py
# Purpose: Auth0 JWT validation with JWKS caching (ported from ColdVault)

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
from jose import jwt, JWTError

from src.config.settings import AUTH0_DOMAIN, AUTH0_AUDIENCE

logger = logging.getLogger(__name__)


class Auth0Handler:
    """Validate Auth0 JWT tokens using JWKS public keys."""

    def __init__(self, domain: str = "", audience: str = ""):
        self.domain = domain or AUTH0_DOMAIN
        self.audience = audience or AUTH0_AUDIENCE
        self.algorithms = ["RS256"]
        self.jwks_uri = f"https://{self.domain}/.well-known/jwks.json"
        self._jwks = None
        self._jwks_fetched_at = None
        self._jwks_cache_duration = timedelta(hours=1)

    def get_jwks(self) -> dict:
        """Fetch JWKS from Auth0 with 1-hour cache and fallback."""
        now = datetime.now()
        if self._jwks and self._jwks_fetched_at:
            if now - self._jwks_fetched_at < self._jwks_cache_duration:
                return self._jwks
        try:
            response = requests.get(self.jwks_uri, timeout=10)
            response.raise_for_status()
            self._jwks = response.json()
            self._jwks_fetched_at = now
            return self._jwks
        except requests.RequestException as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            if self._jwks:
                logger.warning("Using cached JWKS due to fetch failure")
                return self._jwks
            raise

    def validate_token(self, token: str) -> Optional[dict]:
        """Validate Auth0 JWT. Returns decoded payload or None."""
        try:
            if token.startswith("Bearer "):
                token = token[7:]

            unverified_header = jwt.get_unverified_header(token)
            if "kid" not in unverified_header:
                return None

            jwks = self.get_jwks()
            rsa_key = None
            for key in jwks.get("keys", []):
                if key["kid"] == unverified_header["kid"]:
                    rsa_key = {
                        "kty": key["kty"],
                        "kid": key["kid"],
                        "use": key["use"],
                        "n": key["n"],
                        "e": key["e"],
                    }
                    break

            if not rsa_key:
                return None

            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=f"https://{self.domain}/",
            )
            logger.debug(f"Auth0 token validated for: {payload.get('sub')}")
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("Auth0 token expired")
            return None
        except jwt.JWTClaimsError as e:
            logger.warning(f"Auth0 invalid claims: {e}")
            return None
        except JWTError as e:
            logger.warning(f"Auth0 JWT error: {e}")
            return None
        except Exception as e:
            logger.error(f"Auth0 validation error: {e}")
            return None


_handler = None


def get_auth0_handler() -> Auth0Handler:
    """Singleton Auth0 handler."""
    global _handler
    if _handler is None:
        _handler = Auth0Handler()
    return _handler
