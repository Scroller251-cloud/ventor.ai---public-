from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelState:
    name: str
    provider: str
    loaded: bool = False


class ModelManager:
    """Lightweight registry; model loading remains delegated to Ollama/providers."""
    def __init__(self):
        self._models = [
            ModelState(os.getenv("VENTOR_QWEN_MODEL", "qwen3.8:27b"), "ollama"),
            ModelState(os.getenv("VENTOR_GEMMA_MODEL", "gemma3:4b"), "ollama"),
        ]

    def snapshot(self) -> dict:
        return {"models": [m.__dict__ for m in self._models], "count": len(self._models), "local_loading": False}
