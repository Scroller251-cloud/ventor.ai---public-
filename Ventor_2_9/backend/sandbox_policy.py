"""Shared cross-platform policy for generated-code execution."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxPolicy:
    timeout_seconds: int = 10
    memory_mb: int = 256
    cpu_seconds: int = 5
    network: bool = False
    filesystem: str = "temporary-only"
    credentials: bool = False
    max_output_kb: int = 256

    def validate(self) -> None:
        if self.timeout_seconds <= 0 or self.cpu_seconds <= 0:
            raise ValueError("execution limits must be positive")
        if self.memory_mb < 64:
            raise ValueError("memory limit is too small")
        if self.network:
            raise ValueError("network access is deny-by-default")
        if self.credentials:
            raise ValueError("credentials must never enter the sandbox")
        if self.filesystem != "temporary-only":
            raise ValueError("filesystem policy must remain temporary-only")
        if self.max_output_kb <= 0:
            raise ValueError("output limit must be positive")
