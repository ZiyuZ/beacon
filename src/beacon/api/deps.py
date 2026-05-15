"""Shared FastAPI dependencies."""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from beacon.config import Settings, load_settings
from beacon.database import get_session

_bearer_scheme = HTTPBearer(auto_error=False)

# How long a UI login JWT remains valid.
JWT_EXPIRY_DAYS = 7


def get_settings() -> Settings:
    return load_settings()


def _verify_jwt(token: str, secret: str) -> bool:
    """Return ``True`` if *token* is a valid JWT signed with *secret*."""
    if not secret:
        return False
    try:
        jwt.decode(token, secret, algorithms=["HS256"])
        return True
    except jwt.PyJWTError:
        return False


def create_login_jwt(secret: str) -> str:
    """Sign a short-lived JWT for the UI session."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin",
        "iat": now,
        "exp": now + timedelta(days=JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate the shared API token or a UI login JWT.

    Accepts one of:
    * the static ``BEACON_API_TOKEN`` (used by automated sinks / scripts), or
    * a JWT obtained from ``POST /api/auth/login`` (used by the browser UI).

    If ``BEACON_API_TOKEN`` is empty the static-token check is skipped
    (``--no-auth`` mode).
    """

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # 1. Try the static API token.
    if settings.api_token and token == settings.api_token:
        return

    # 2. Try the UI login JWT.
    if _verify_jwt(token, settings.admin_password):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = [
    "create_login_jwt",
    "get_session",
    "get_settings",
    "require_token",
    "Session",
]
