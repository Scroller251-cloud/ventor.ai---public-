import asyncio

from backend.provider_router import ProviderReply, ProviderRouter


def test_provider_circuit_breaker_opens_after_failures(monkeypatch):
    async def run():
        router = ProviderRouter()
        router.failure_threshold = 2
        router.cooldown = 60
        router.openai_key = "test-key"
        async def fail(prompt, system):
            return ProviderReply("openai", "test", "", False, "boom", 1)
        monkeypatch.setattr(router, "_openai", fail)
        await router._openai("x", "y")
        await router._openai("x", "y")
        assert router.status()["openai"]["healthy"] is False
    asyncio.run(run())
