"""Compatibility gate backed by short-lived cryptographic sessions."""
from __future__ import annotations

from fastapi import Header, HTTPException

from .command_auth import get_session_principal


def _require_session(authorization: str | None) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Ventor administrative session required")
    token = authorization.split(" ", 1)[1].strip()
    if not token or get_session_principal(token) is None:
        raise HTTPException(status_code=401, detail="Missing, expired, or invalid Ventor administrative session")


def require_owner(authorization: str | None = Header(default=None)) -> None:
    _require_session(authorization)


def require_team_or_owner(authorization: str | None = Header(default=None)) -> None:
    _require_session(authorization)
