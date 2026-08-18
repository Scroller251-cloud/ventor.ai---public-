from __future__ import annotations

import os
import platform
import shutil
import time
from dataclasses import dataclass

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


@dataclass(frozen=True)
class ModelProfile:
    name: str
    provider: str
    ram_mb: int
    vram_mb: int
    specialties: tuple[str, ...]


class RuntimeManager:
    """Hardware telemetry with short-lived caching to avoid repeated syscalls."""
    def __init__(self):
        self.started = time.time()
        self.profiles = [
            ModelProfile("qwen3:4b", "ollama", 4500, 3000, ("general", "coding", "fast")),
            ModelProfile("gemma3:4b", "ollama", 4500, 3000, ("general", "verification", "fast")),
            ModelProfile(os.getenv("VENTOR_CHAT_MODEL", "qwen3:4b"), "ollama", 4500, 3000, ("chat",)),
        ]
        self._cache_ttl = max(0.25, float(os.getenv("VENTOR_RUNTIME_CACHE_TTL", "2")))
        self._cached_memory = None
        self._cached_memory_at = 0.0

    def memory(self) -> dict:
        now = time.monotonic()
        if self._cached_memory is not None and now - self._cached_memory_at < self._cache_ttl:
            return self._cached_memory
        if psutil is None:
            value = {"available": False, "reason": "install psutil for live resource telemetry"}
        else:
            vm = psutil.virtual_memory()
            value = {"available": True, "total_mb": round(vm.total / 1048576), "available_mb": round(vm.available / 1048576), "used_mb": round(vm.used / 1048576), "percent": vm.percent}
        self._cached_memory, self._cached_memory_at = value, now
        return value

    def disk(self) -> dict:
        usage = shutil.disk_usage(os.getenv("VENTOR_WORKSPACE", "."))
        return {"total_gb": round(usage.total / 1073741824, 2), "free_gb": round(usage.free / 1073741824, 2), "used_percent": round((usage.used / usage.total) * 100, 2) if usage.total else 0}

    def waterline(self, memory=None) -> dict:
        memory = memory or self.memory()
        percent = memory.get("percent")
        if percent is None:
            state = "unknown"
        elif percent < 70:
            state = "normal"
        elif percent < 82:
            state = "pressure"
        elif percent < 92:
            state = "evict_idle"
        elif percent < 97:
            state = "aggressive_cleanup"
        else:
            state = "emergency"
        return {"state": state, "percent": percent, "policy": "protect responsiveness first; unload idle resources before shrinking active work"}

    def snapshot(self) -> dict:
        memory = self.memory()
        return {"platform": platform.platform(), "python": platform.python_version(), "memory": memory, "disk": self.disk(), "waterline": self.waterline(memory), "profiles": [p.__dict__ for p in self.profiles], "uptime_s": round(time.time() - self.started, 2)}
