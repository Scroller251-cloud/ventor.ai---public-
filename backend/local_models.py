from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class LocalResponse:
    mentor: str
    model: str
    text: str
    latency_ms: int
    metadata: dict[str, Any]

    @property
    def answer(self) -> str:
        return self.text


class OllamaMentor:
    """Low-overhead Ollama client with shared connection pooling and fallback models."""

    def __init__(self, mentor: str, env_name: str, default_chain: list[str], capability: str):
        self.mentor = mentor
        self.env_name = env_name
        override = os.getenv(env_name)
        self.chain = [m.strip() for m in override.split(",") if m.strip()] if override else list(default_chain)
        if not self.chain:
            raise ValueError(f"{env_name} must contain at least one model")
        self.model = self.chain[0]
        self.base = os.getenv("VENTOR_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.capability = capability
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._health_cache: tuple[float, dict[str, Any]] | None = None
        self._health_ttl = max(0.0, float(os.getenv("VENTOR_OLLAMA_HEALTH_TTL", "5")))

    async def _get_client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._client_loop is not loop:
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
            timeout = httpx.Timeout(
                connect=float(os.getenv("VENTOR_OLLAMA_CONNECT_TIMEOUT", "3")),
                read=float(os.getenv("VENTOR_OLLAMA_READ_TIMEOUT", "180")),
                write=float(os.getenv("VENTOR_OLLAMA_WRITE_TIMEOUT", "30")),
                pool=float(os.getenv("VENTOR_OLLAMA_POOL_TIMEOUT", "3")),
            )
            self._client = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=16, max_keepalive_connections=8))
            self._client_loop = loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._client_loop = None

    async def health_async(self, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._health_cache and now - self._health_cache[0] < self._health_ttl:
            return self._health_cache[1]
        try:
            client = await self._get_client()
            r = await client.get(f"{self.base}/api/tags", timeout=3)
            if r.status_code != 200:
                result = {"mentor": self.mentor, "model": self.model, "available": False, "detail": f"Ollama HTTP {r.status_code}"}
            else:
                names = {x.get("name", "") for x in r.json().get("models", [])}
                def installed(model: str) -> bool:
                    return model in names or any(n.split(":", 1)[0] == model.split(":", 1)[0] for n in names)
                resolved = next((m for m in self.chain if installed(m)), None)
                if resolved:
                    self.model = resolved
                    result = {"mentor": self.mentor, "model": self.model, "available": True, "ollama": True,
                              "installed_models": sorted(names), "fallback_chain": self.chain}
                else:
                    result = {"mentor": self.mentor, "model": self.chain[0], "available": False, "ollama": True,
                              "installed_models": sorted(names), "fallback_chain": self.chain,
                              "detail": "none of the configured models are pulled yet"}
        except Exception as exc:
            result = {"mentor": self.mentor, "model": self.model, "available": False,
                      "detail": f"Ollama unavailable: {type(exc).__name__}"}
        self._health_cache = (now, result)
        return result

    def health(self) -> dict[str, Any]:
        """Compatibility health check. Async request paths use health_async()."""
        try:
            import httpx as _httpx
            r = _httpx.get(f"{self.base}/api/tags", timeout=2)
            if r.status_code != 200:
                return {"mentor": self.mentor, "model": self.model, "available": False, "detail": f"Ollama HTTP {r.status_code}"}
            names = {x.get("name", "") for x in r.json().get("models", [])}
            resolved = next((m for m in self.chain if m in names or any(n.split(":", 1)[0] == m.split(":", 1)[0] for n in names)), None)
            if resolved:
                self.model = resolved
                return {"mentor": self.mentor, "model": self.model, "available": True, "ollama": True, "installed_models": sorted(names), "fallback_chain": self.chain}
            return {"mentor": self.mentor, "model": self.chain[0], "available": False, "ollama": True, "installed_models": sorted(names), "fallback_chain": self.chain}
        except Exception as exc:
            return {"mentor": self.mentor, "model": self.model, "available": False, "detail": f"Ollama unavailable: {type(exc).__name__}"}

    async def generate(self, prompt: str, system: str | None = None) -> LocalResponse:
        health = await self.health_async()
        if not health["available"]:
            raise RuntimeError(f"{self.mentor}: {health.get('detail', 'model unavailable')}")
        payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        start = time.perf_counter()
        client = await self._get_client()
        response = await client.post(f"{self.base}/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
        return LocalResponse(self.mentor, self.model, data.get("response", ""), int((time.perf_counter() - start) * 1000),
                             {"backend": "ollama", "capability": self.capability})


class QwenMentor(OllamaMentor):
    def __init__(self):
        super().__init__("Qwen Mentor", "VENTOR_QWEN_MODEL", ["qwen3.8:27b", "qwen3.6:27b", "qwen3:8b", "qwen3:4b"], "reasoning,coding")


class GemmaMentor(OllamaMentor):
    def __init__(self):
        super().__init__("Gemma Mentor", "VENTOR_GEMMA_MODEL", ["gemma3:4b"], "reasoning,general")
