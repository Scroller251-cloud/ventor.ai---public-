from __future__ import annotations


def public_registry():
    return [
        {"name": "Qwen Mentor", "model": "qwen3.6:27b", "capability": "reasoning,coding", "backend": "ollama"},
        {"name": "Gemma Mentor", "model": "gemma3:4b", "capability": "reasoning,general", "backend": "ollama"},
    ]


def probe():
    return public_registry()
