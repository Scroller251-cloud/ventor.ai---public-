"""Cryptographic principal authorization. No static private key or password is stored here."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROLE_OWNER = "owner"
ROLE_USER = "user"
ROLE_DEVICE = "device"
MAX_PROOF_AGE_SECONDS = 120
OWNER_ID = os.getenv("VENTOR_OWNER_ID", "owner")
_consumed_challenges: dict[str, float] = {}
_challenge_lock = Lock()


@dataclass(frozen=True)
class Principal:
    role: str
    key_id: str
    github_login: str | None = None
    principal_id: str | None = None
    device_id: str | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == ROLE_OWNER and self.principal_id == OWNER_ID


class AuthorizationError(RuntimeError):
    pass


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical_claims(claims: dict) -> bytes:
    return json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()


def new_challenge() -> str:
    challenge = secrets.token_urlsafe(32)
    now = time.time()
    with _challenge_lock:
        for key, expiry in list(_consumed_challenges.items()):
            if expiry < now:
                _consumed_challenges.pop(key, None)
    return challenge


def _consume_challenge(challenge: str, max_age: int) -> bool:
    now = time.time()
    with _challenge_lock:
        for key, expiry in list(_consumed_challenges.items()):
            if expiry < now:
                _consumed_challenges.pop(key, None)
        if challenge in _consumed_challenges:
            return False
        _consumed_challenges[challenge] = now + max_age
        return True


def fingerprint_public_key(public_key_b64: str) -> str:
    return hashlib.sha256(_b64decode(public_key_b64)).hexdigest()[:16]


def verify_signed_challenge(*, challenge, claims, signature_b64, public_key_b64, expected_key_id, max_age_seconds=MAX_PROOF_AGE_SECONDS):
    if not challenge or claims.get("challenge") != challenge:
        return False
    try:
        issued_at = int(claims.get("issued_at", 0))
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - issued_at) > max_age_seconds or claims.get("key_id") != expected_key_id:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(_b64decode(public_key_b64)).verify(_b64decode(signature_b64), _canonical_claims(claims))
        return True
    except Exception:
        return False


def load_runtime_roster(path=None):
    roster_path = os.environ.get("VENTOR_AUTH_ROSTER") or (str(path) if path else None)
    if not roster_path:
        raise AuthorizationError("VENTOR_AUTH_ROSTER is not configured")
    roster_file = Path(roster_path).expanduser().resolve()
    if not roster_file.is_file():
        raise AuthorizationError("authorization roster is unavailable")
    return json.loads(roster_file.read_text(encoding="utf-8"))


def authorize(*, challenge, claims, signature_b64, roster):
    key_id = str(claims.get("key_id", ""))
    entry = next((e for e in roster.get("principals", []) if e.get("key_id") == key_id and not e.get("disabled", False)), None)
    if entry is None or not verify_signed_challenge(challenge=challenge, claims=claims, signature_b64=signature_b64, public_key_b64=str(entry.get("public_key", "")), expected_key_id=key_id):
        raise AuthorizationError("authorization failed")
    if not _consume_challenge(challenge, MAX_PROOF_AGE_SECONDS):
        raise AuthorizationError("challenge has already been consumed")
    role = entry.get("role")
    principal_id = entry.get("principal_id")
    if role == ROLE_OWNER and principal_id != OWNER_ID:
        raise AuthorizationError("invalid owner root")
    if role not in {ROLE_OWNER, ROLE_USER, ROLE_DEVICE, "team-admin"}:
        raise AuthorizationError("unknown principal role")
    return Principal(role, key_id, entry.get("github_login"), principal_id, entry.get("device_id"))


def can_manage_principal(actor, target):
    return actor.is_owner


def can_change_owner_root(actor):
    return actor.is_owner
