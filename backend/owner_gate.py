from __future__ import annotations

from fastapi import Header, HTTPException
from command_auth import get_session_principal


def require_owner(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Ventor administrative session required")
    principal = get_session_principal(authorization.split(" ", 1)[1].strip())
    if principal is None or principal.role not in {"owner", "team-admin"}:
        raise HTTPException(status_code=403, detail="Owner or team-admin authority required")
