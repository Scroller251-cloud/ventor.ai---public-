import asyncio

from backend.provider_router import ProviderRouter


def test_provider_circuit_breaker_opens_after_failures():
    async def run():
        router = ProviderRouter()
        router.failure_threshold = 2
        router.cooldown = 60
        await router._call("openai", "test", lambda: _empty())
        await router._call("openai", "test", lambda: _empty())
        assert router.status()["openai"]["healthy"] is False

    async def _empty():
        return ""

    asyncio.run(run())
