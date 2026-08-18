"""Short-lived session and one-time command authorization."""
from __future__ import annotations

import secrets
import time
from threading import Lock

from owner_authorization import Principal

SESSION_TTL = 900
COMMAND_TTL = 120
_SESSIONS: dict[str, tuple[Principal, int]] = {}
_COMMANDS: dict[str, tuple[Principal, str, dict, int]] = {}
_LOCK = Lock()


def _cleanup(now: int) -> None:
    for store in (_SESSIONS, _COMMANDS):
        for key, value in list(store.items()):
            if value[-1] < now:
                store.pop(key, None)


def issue_session(principal: Principal) -> str:
    token = secrets.token_urlsafe(48)
    with _LOCK:
        now = int(time.time())
        _cleanup(now)
        _SESSIONS[token] = (principal, now + SESSION_TTL)
    return token


def get_session_principal(token: str) -> Principal | None:
    if not token:
        return None
    with _LOCK:
        now = int(time.time())
        _cleanup(now)
        item = _SESSIONS.get(token)
        return item[0] if item else None


def verify_session(token: str, scope: str = "owner") -> bool:
    return get_session_principal(token) is not None


def sign_command(principal: Principal, capability: str, args: dict, ttl: int = COMMAND_TTL) -> str:
    if principal.role not in {"owner", "user", "device"}:
        raise PermissionError("authenticated principal required")
    token = secrets.token_urlsafe(48)
    with _LOCK:
        now = int(time.time())
        _cleanup(now)
        _COMMANDS[token] = (principal, capability, dict(args), now + min(max(1, ttl), COMMAND_TTL))
    return token


def verify_command(token: str, capability: str, args: dict) -> tuple[bool, str]:
    with _LOCK:
        now = int(time.time())
        _cleanup(now)
        item = _COMMANDS.pop(token, None)
    if not item:
        return False, "invalid_or_replayed"
    principal, expected_capability, expected_args, expires = item
    if expires < int(time.time()):
        return False, "expired"
    if expected_capability != capability or expected_args != args:
        return False, "command_mismatch"
    if principal.role not in {"owner", "user", "device"}:
        return False, "unauthorized_principal"
    return True, "ok"
