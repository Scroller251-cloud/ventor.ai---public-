from __future__ import annotations


def public_registry() -> list[dict[str, str]]:
    return [
        {"name": "Qwen Mentor", "model": "qwen3.8:27b", "capability": "reasoning,coding", "backend": "ollama"},
        {"name": "Gemma Mentor", "model": "gemma3:4b", "capability": "reasoning,general", "backend": "ollama"},
    ]


def probe() -> list[dict[str, str]]:
    return public_registry()
