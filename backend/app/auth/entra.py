"""
Real Azure Entra ID OIDC JWT validation (prod path).

Even though local dev bypasses this entirely via AUTH_MODE=dev, this module is
fully implemented so switching a deployment to AUTH_MODE=prod is a config-only
change, not a code change.
"""
import logging
import time
from typing import Dict, List, Optional

import httpx
from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import JOSEError

from app.config import settings

logger = logging.getLogger(__name__)

_jwks_cache: Dict = {}
_jwks_fetched_at: float = 0.0
# Minimum spacing between forced JWKS refetches: an attacker sending garbage
# `kid`s must not be able to hammer the JWKS endpoint through us.
_JWKS_REFRESH_COOLDOWN_SECONDS = 60.0


def validate_prod_config() -> None:
    """Fail fast at startup when AUTH_MODE=prod is misconfigured.

    Without this, a blank ENTRA_AUDIENCE/ENTRA_CLIENT_ID silently disables
    audience verification and a blank ENTRA_ISSUER disables issuer
    verification -- the service would boot and accept tokens it must not.
    Refusing to start is the only safe failure mode."""
    missing = []
    if not settings.ENTRA_JWKS_URL:
        missing.append("ENTRA_JWKS_URL")
    if not settings.ENTRA_ISSUER:
        missing.append("ENTRA_ISSUER")
    if not (settings.ENTRA_AUDIENCE or settings.ENTRA_CLIENT_ID):
        missing.append("ENTRA_AUDIENCE (or ENTRA_CLIENT_ID)")
    if missing:
        raise RuntimeError(
            "AUTH_MODE=prod requires these settings, otherwise token validation "
            f"is silently weakened: {', '.join(missing)}"
        )


def _get_jwks(force_refresh: bool = False) -> Dict:
    """Fetch (and cache in-process) the Entra JWKS document.

    Note: caching here is only for the *signing keys* (which rotate rarely
    and are not authorization-sensitive) -- role/tenant resolution itself is
    never cached, per the auth model. `force_refresh` re-fetches (rate-limited
    by the cooldown) so Entra key rotation is picked up without a redeploy.
    """
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    if _jwks_cache:
        if not force_refresh:
            return _jwks_cache
        if now - _jwks_fetched_at < _JWKS_REFRESH_COOLDOWN_SECONDS:
            return _jwks_cache
    if not settings.ENTRA_JWKS_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ENTRA_JWKS_URL is not configured",
        )
    resp = httpx.get(settings.ENTRA_JWKS_URL, timeout=10.0)
    resp.raise_for_status()
    _jwks_cache = resp.json()
    _jwks_fetched_at = now
    return _jwks_cache


def _find_signing_key(jwks: Dict, kid: Optional[str]) -> Optional[Dict]:
    return next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)


def validate_token(token: str) -> Dict:
    """Validate a raw bearer JWT against Entra's JWKS and return its claims."""
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        key = _find_signing_key(_get_jwks(), kid)
        if key is None:
            # Likely Entra key rotation since our cached fetch: refresh once
            # (cooldown-limited) before rejecting.
            key = _find_signing_key(_get_jwks(force_refresh=True), kid)
        if key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown signing key")

        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.ENTRA_AUDIENCE or settings.ENTRA_CLIENT_ID,
            issuer=settings.ENTRA_ISSUER or None,
            options={"verify_aud": bool(settings.ENTRA_AUDIENCE or settings.ENTRA_CLIENT_ID)},
        )
        return claims
    except JOSEError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc


def extract_group_ids(claims: Dict) -> List[str]:
    """Extract Entra group object IDs from validated claims.

    Handles the common `groups` claim shape. (Overage scenarios where Entra
    omits `groups` and instead sets a `_claim_names`/`hasgroups` indicator
    requiring a follow-up Microsoft Graph call are out of scope for v1.)
    """
    groups = claims.get("groups") or []
    if isinstance(groups, str):
        return [groups]
    return list(groups)
