from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import httpx


@dataclass
class LocalResponse:
    mentor: str
    model: str
    text: str
    latency_ms: int
    metadata: dict

    @property
    def answer(self):
        return self.text


class OllamaMentor:
    """Ollama mentor with shared HTTP transport and cached model discovery."""
    def __init__(self, mentor, env_name, default_chain, capability):
        override = os.getenv(env_name, "")
        self.mentor = mentor
        self.chain = [m.strip() for m in override.split(",") if m.strip()] if override else list(default_chain)
        self.model = self.chain[0]
        self.base = os.getenv("VENTOR_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.capability = capability
        self.health_ttl = max(1.0, float(os.getenv("VENTOR_OLLAMA_HEALTH_TTL", "15")))
        self.timeout = max(1.0, float(os.getenv("VENTOR_OLLAMA_TIMEOUT", "180")))
        self._health_cache: dict | None = None
        self._health_at = 0.0
        self._health_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            async with self._client_lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)), limits=httpx.Limits(max_connections=32, max_keepalive_connections=8))
        return self._client

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def health(self, force: bool = False):
        now = time.monotonic()
        if not force and self._health_cache is not None and now - self._health_at < self.health_ttl:
            return self._health_cache
        async with self._health_lock:
            now = time.monotonic()
            if not force and self._health_cache is not None and now - self._health_at < self.health_ttl:
                return self._health_cache
            try:
                client = await self._get_client()
                response = await client.get(f"{self.base}/api/tags", timeout=2.0)
                response.raise_for_status()
                names = {item.get("name", "") for item in response.json().get("models", [])}
                def installed(model: str) -> bool:
                    return model in names or any(name.split(":")[0] == model.split(":")[0] for name in names)
                resolved = next((model for model in self.chain if installed(model)), None)
                if resolved:
                    self.model = resolved
                result = {"mentor": self.mentor, "model": self.model, "available": bool(resolved), "ollama": True, "installed_models": sorted(names), "fallback_chain": self.chain, "detail": "model available locally" if resolved else f"none of {self.chain} are pulled yet"}
            except Exception as exc:
                result = {"mentor": self.mentor, "model": self.model, "available": False, "ollama": True, "detail": f"Ollama unavailable: {type(exc).__name__}"}
            self._health_cache, self._health_at = result, time.monotonic()
            return result

    def health_sync(self):
        # Health is primarily used from async request paths. Keep the sync API
        # for compatibility without performing blocking network I/O here.
        return self._health_cache or {"mentor": self.mentor, "model": self.model, "available": False, "detail": "health not probed"}

    async def generate(self, prompt, system=None):
        health = await self.health()
        if not health["available"]:
            raise RuntimeError(f"{self.mentor}: {health['detail']}")
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        started = time.perf_counter()
        client = await self._get_client()
        response = await client.post(f"{self.base}/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
        return LocalResponse(self.mentor, self.model, data.get("response", ""), round((time.perf_counter() - started) * 1000), {"backend": "ollama", "capability": self.capability})


class QwenMentor(OllamaMentor):
    def __init__(self):
        super().__init__("Qwen Mentor", "VENTOR_QWEN_MODEL", ["qwen3.6:27b", "qwen3:8b", "qwen3:4b"], "reasoning,coding")


class GemmaMentor(OllamaMentor):
    def __init__(self):
        super().__init__("Gemma Mentor", "VENTOR_GEMMA_MODEL", ["gemma3:4b"], "reasoning,general")
