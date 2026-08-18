import tempfile
from pathlib import Path

from backend.command_auth import issue_session, sign_command, verify_command
from backend.memory_store import MemoryStore
from backend.owner_authorization import Principal
from backend.production_runtime import RateLimiter
from backend.provider_router import ProviderRouter


def test_rate_limiter_rejects_after_limit():
    limiter = RateLimiter(limit=2, window=60)
    assert limiter.allow("client")[0] is True
    assert limiter.allow("client")[0] is True
    allowed, retry = limiter.allow("client")
    assert allowed is False
    assert retry >= 1


def test_rate_limiter_key_cardinality_is_bounded():
    limiter = RateLimiter(limit=2, window=60, max_keys=128)
    for i in range(10_000):
        limiter.allow(f"client-{i}")
    assert limiter.snapshot()["keys"] <= 128


def test_memory_isolation_and_retrieval():
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(Path(tmp) / "memory.db")
        alice = MemoryStore.namespace("alice", "default")
        bob = MemoryStore.namespace("bob", "default")
        store.add("user", "Alice private fact", alice, importance=1.0)
        store.add("user", "Bob private fact", bob, importance=1.0)
        assert store.recent(20, alice)[0]["content"] == "Alice private fact"
        assert store.recent(20, bob)[0]["content"] == "Bob private fact"
        assert store.retrieve_context("Alice fact", alice, 4)[0]["content"] == "Alice private fact"


def test_memory_fact_provenance_is_persisted():
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(Path(tmp) / "memory.db")
        store.set_fact("language", "Python", "alice", confidence=0.9, source="verified")
        fact = store.facts("alice")[0]
        assert fact["confidence"] == 0.9
        assert fact["source"] == "verified"


def test_principal_bound_command_is_one_time():
    principal = Principal("owner", "key-a", principal_id="alice")
    other = Principal("owner", "key-b", principal_id="bob")
    assert issue_session(principal)
    token = sign_command(principal, "workspace.read", {"path": "x"})
    assert verify_command(token, "workspace.read", {"path": "x"}, other)[0] is False
    token = sign_command(principal, "workspace.read", {"path": "x"})
    assert verify_command(token, "workspace.read", {"path": "x"}, principal)[0] is True
    assert verify_command(token, "workspace.read", {"path": "x"}, principal)[0] is False


def test_provider_status_has_breaker_fields():
    status = ProviderRouter().status()
    assert set(status) >= {"ollama", "openai", "anthropic", "gemini"}
    assert all("healthy" in value and "failures" in value for value in status.values())
