from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import httpx


@dataclass
class ProviderReply:
    provider: str
    model: str
    text: str
    ok: bool
    error: str | None = None
    latency_ms: int = 0


@dataclass
class ProviderHealth:
    failures: int = 0
    successes: int = 0
    opened_until: float = 0.0
    last_latency_ms: int = 0


class ProviderRouter:
    def __init__(self):
        self.ollama = os.getenv("VENTOR_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self.timeout = max(1.0, float(os.getenv("VENTOR_PROVIDER_TIMEOUT", "45")))
        self.failure_threshold = max(1, int(os.getenv("VENTOR_PROVIDER_FAILURE_THRESHOLD", "3")))
        self.cooldown = max(1.0, float(os.getenv("VENTOR_PROVIDER_COOLDOWN", "30")))
        self.health: dict[str, ProviderHealth] = {}
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self):
        if self._client is None or self._client.is_closed:
            async with self._client_lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)), limits=httpx.Limits(max_connections=64, max_keepalive_connections=16), follow_redirects=False)
        return self._client

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _state(self, provider):
        return self.health.setdefault(provider, ProviderHealth())

    def _available(self, provider):
        return {"ollama": True, "openai": bool(self.openai_key), "anthropic": bool(self.anthropic_key), "gemini": bool(self.gemini_key)}.get(provider, False)

    def status(self):
        now = time.monotonic()
        return {provider: {"configured": self._available(provider), "healthy": self._state(provider).opened_until <= now, "failures": self._state(provider).failures, "successes": self._state(provider).successes, "last_latency_ms": self._state(provider).last_latency_ms} for provider in ("ollama", "openai", "anthropic", "gemini")}

    async def _mark_success(self, provider, latency_ms):
        async with self._lock:
            state = self._state(provider)
            state.successes += 1
            state.failures = 0
            state.opened_until = 0.0
            state.last_latency_ms = latency_ms

    async def _mark_failure(self, provider):
        async with self._lock:
            state = self._state(provider)
            state.failures += 1
            if state.failures >= self.failure_threshold:
                state.opened_until = time.monotonic() + self.cooldown

    async def _request(self, method, url, **kwargs):
        client = await self._get_client()
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    async def _call(self, provider, model, request_fn):
        started = time.perf_counter()
        try:
            text = await request_fn()
            if not text or not text.strip():
                raise RuntimeError("empty_response")
            latency = round((time.perf_counter() - started) * 1000)
            await self._mark_success(provider, latency)
            return ProviderReply(provider, model, text, True, latency_ms=latency)
        except Exception as exc:
            latency = round((time.perf_counter() - started) * 1000)
            await self._mark_failure(provider)
            return ProviderReply(provider, model, "", False, f"{type(exc).__name__}: {exc}", latency)

    async def _ollama(self, prompt, system):
        model = os.getenv("VENTOR_CHAT_MODEL", "qwen3:4b")
        async def request():
            r = await self._request("POST", self.ollama + "/api/generate", json={"model": model, "prompt": prompt, "system": system, "stream": False})
            return r.json().get("response", "")
        return await self._call("ollama", model, request)

    async def _openai(self, prompt, system):
        model = os.getenv("VENTOR_OPENAI_MODEL", "gpt-5.4-mini")
        async def request():
            r = await self._request("POST", "https://api.openai.com/v1/responses", headers={"Authorization": "Bearer " + self.openai_key, "Content-Type": "application/json"}, json={"model": model, "input": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
            return r.json().get("output_text", "")
        return await self._call("openai", model, request)

    async def _anthropic(self, prompt, system):
        model = os.getenv("VENTOR_ANTHROPIC_MODEL", "claude-sonnet-4-5")
        async def request():
            r = await self._request("POST", "https://api.anthropic.com/v1/messages", headers={"x-api-key": self.anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json={"model": model, "max_tokens": 2048, "system": system, "messages": [{"role": "user", "content": prompt}]})
            return "".join(x.get("text", "") for x in r.json().get("content", []) if x.get("type") == "text")
        return await self._call("anthropic", model, request)

    async def _gemini(self, prompt, system):
        model = os.getenv("VENTOR_GEMINI_MODEL", "gemini-2.5-flash")
        async def request():
            r = await self._request("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_key}", json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}]})
            return "".join(p.get("text", "") for p in r.json().get("candidates", [{}])[0].get("content", {}).get("parts", []))
        return await self._call("gemini", model, request)

    async def generate(self, prompt, system, preferred=None):
        configured = [x.strip() for x in os.getenv("VENTOR_PROVIDER_ORDER", "ollama,openai,anthropic,gemini").split(",") if x.strip()]
        order = ([preferred] if preferred else []) + [x for x in configured if x != preferred]
        errors = []
        for provider in order:
            if not self._available(provider):
                continue
            if self._state(provider).opened_until > time.monotonic():
                errors.append(provider + ": circuit_open")
                continue
            result = await {"ollama": self._ollama, "openai": self._openai, "anthropic": self._anthropic, "gemini": self._gemini}[provider](prompt, system)
            if result.ok:
                return result
            errors.append(result.error or provider + ": failed")
        return ProviderReply("none", "", "", False, "; ".join(errors) or "No configured provider")
