"""Public authorization primitives for Ventor.

This module contains no private credentials. Creator and Co-Creator public-key
material is injected at runtime from secure deployment storage. The Creator
root is immutable from Co-Creator administration.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

CREATOR_ID = "VENTOR-CREATOR-SUJAL-AJAY-KALE"
ROLE_CREATOR = "creator"
ROLE_CO_CREATOR = "co_creator"
MAX_PROOF_AGE_SECONDS = 120

@dataclass(frozen=True)
class Principal:
    role: str
    key_id: str
    github_login: str | None = None
    principal_id: str | None = None

    @property
    def is_creator(self) -> bool:
        return self.role == ROLE_CREATOR and self.principal_id == CREATOR_ID

    @property
    def is_co_creator(self) -> bool:
        return self.role == ROLE_CO_CREATOR

class AuthorizationError(RuntimeError):
    pass

def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def _canonical_claims(claims: dict) -> bytes:
    return json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()

def new_challenge() -> str:
    return secrets.token_urlsafe(32)

def fingerprint_public_key(public_key_b64: str) -> str:
    return hashlib.sha256(_b64decode(public_key_b64)).hexdigest()[:16]

def verify_signed_challenge(*, challenge: str, claims: dict, signature_b64: str,
                            public_key_b64: str, expected_key_id: str,
                            max_age_seconds: int = MAX_PROOF_AGE_SECONDS) -> bool:
    if not challenge or claims.get("challenge") != challenge:
        return False
    if abs(int(time.time()) - int(claims.get("issued_at", 0))) > max_age_seconds:
        return False
    if claims.get("key_id") != expected_key_id:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(_b64decode(public_key_b64)).verify(
            _b64decode(signature_b64), _canonical_claims(claims)
        )
        return True
    except Exception:
        return False

def load_runtime_roster(path: str | os.PathLike[str] | None = None) -> dict:
    roster_path = os.environ.get("VENTOR_AUTH_ROSTER") if path is None else str(path)
    if not roster_path:
        raise AuthorizationError("VENTOR_AUTH_ROSTER is not configured")
    p = Path(roster_path).expanduser().resolve()
    if not p.is_file():
        raise AuthorizationError("authorization roster is unavailable")
    return json.loads(p.read_text(encoding="utf-8"))

def authorize(*, challenge: str, claims: dict, signature_b64: str, roster: dict) -> Principal:
    key_id = str(claims.get("key_id", ""))
    for entry in roster.get("principals", []):
        if entry.get("key_id") != key_id or entry.get("disabled", False):
            continue
        if not verify_signed_challenge(challenge=challenge, claims=claims,
                                       signature_b64=signature_b64,
                                       public_key_b64=entry["public_key"],
                                       expected_key_id=key_id):
            continue
        role = entry.get("role")
        principal_id = entry.get("principal_id")
        if role not in {ROLE_CREATOR, ROLE_CO_CREATOR}:
            raise AuthorizationError("principal is not an administrative role")
        if role == ROLE_CREATOR and principal_id != CREATOR_ID:
            raise AuthorizationError("invalid Creator root")
        return Principal(role=role, key_id=key_id,
                         github_login=entry.get("github_login"),
                         principal_id=principal_id)
    raise AuthorizationError("authorization failed")

def can_manage_principal(actor: Principal, target: Principal) -> bool:
    if not (actor.is_creator or actor.is_co_creator):
        return False
    if target.principal_id == CREATOR_ID:
        return actor.is_creator
    return True
