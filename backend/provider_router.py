from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ProviderReply:
    provider: str
    model: str
    text: str
    ok: bool
    error: str | None = None


class ProviderRouter:
    """Ordered provider fallback with one pooled HTTP client per event loop."""
    def __init__(self):
        self.ollama = os.getenv("VENTOR_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self._client: httpx.AsyncClient | None = None
        self._loop = None

    async def _http(self) -> httpx.AsyncClient:
        import asyncio
        loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._loop is not loop:
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=3, read=120, write=30, pool=3),
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            )
            self._loop = loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._loop = None

    def status(self):
        return {"ollama": True, "openai": bool(self.openai_key), "anthropic": bool(self.anthropic_key), "gemini": bool(self.gemini_key)}

    async def _ollama(self, prompt, system):
        model = os.getenv("VENTOR_CHAT_MODEL", "qwen3:4b")
        r = await (await self._http()).post(self.ollama + "/api/generate", json={"model": model, "prompt": prompt, "system": system, "stream": False})
        r.raise_for_status()
        return ProviderReply("ollama", model, r.json().get("response", ""), True)

    async def _openai(self, prompt, system):
        model = os.getenv("VENTOR_OPENAI_MODEL", "gpt-5.4-mini")
        headers = {"Authorization": "Bearer " + self.openai_key, "Content-Type": "application/json"}
        r = await (await self._http()).post("https://api.openai.com/v1/responses", headers=headers,
            json={"model": model, "input": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        r.raise_for_status()
        return ProviderReply("openai", model, r.json().get("output_text", ""), True)

    async def _anthropic(self, prompt, system):
        model = os.getenv("VENTOR_ANTHROPIC_MODEL", "claude-sonnet-4-5")
        headers = {"x-api-key": self.anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        r = await (await self._http()).post("https://api.anthropic.com/v1/messages", headers=headers,
            json={"model": model, "max_tokens": 2048, "system": system, "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = "".join(x.get("text", "") for x in r.json().get("content", []) if x.get("type") == "text")
        return ProviderReply("anthropic", model, text, True)

    async def _gemini(self, prompt, system):
        model = os.getenv("VENTOR_GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_key}"
        r = await (await self._http()).post(url, json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}]})
        r.raise_for_status()
        candidates = r.json().get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        return ProviderReply("gemini", model, "".join(p.get("text", "") for p in parts), True)

    async def generate(self, prompt, system, preferred=None):
        configured = {"ollama": True, "openai": bool(self.openai_key), "anthropic": bool(self.anthropic_key), "gemini": bool(self.gemini_key)}
        raw_order = [x.strip() for x in os.getenv("VENTOR_PROVIDER_ORDER", "ollama,openai,anthropic,gemini").split(",") if x.strip()]
        order = list(dict.fromkeys(([preferred] if preferred else []) + raw_order))
        errors = []
        for provider in order:
            if provider not in configured or not configured[provider]:
                continue
            try:
                if provider == "ollama": return await self._ollama(prompt, system)
                if provider == "openai": return await self._openai(prompt, system)
                if provider == "anthropic": return await self._anthropic(prompt, system)
                if provider == "gemini": return await self._gemini(prompt, system)
            except Exception as exc:
                errors.append(provider + ": " + type(exc).__name__)
        return ProviderReply("none", "", "", False, "; ".join(errors) or "No configured provider")
