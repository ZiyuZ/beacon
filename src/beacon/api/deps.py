"""Shared FastAPI dependencies."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from beacon.config import Settings, load_settings
from beacon.database import get_session

_bearer_scheme = HTTPBearer(auto_error=False)


def get_settings() -> Settings:
    return load_settings()


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate the shared API token.

    If ``BEACON_API_TOKEN`` is empty the server is treated as open; this is
    convenient for local development but should not be used on the public
    internet.
    """

    expected = settings.api_token
    if not expected:
        return

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


__all__ = ["get_session", "get_settings", "require_token", "Session"]
