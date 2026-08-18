"""Owner-gated workspace access and fail-closed process execution."""
from __future__ import annotations

import os
from pathlib import Path

from Ventor_2_9.backend.platform_sandbox import DockerIsolationProvider, IsolationUnavailable
from Ventor_2_9.backend.sandbox_policy import SandboxPolicy


class SandboxExecutionDenied(PermissionError):
    pass


class ComputerSandbox:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv("VENTOR_WORKSPACE", Path(__file__).resolve().parent / "workspace")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.isolator = DockerIsolationProvider()

    def _path(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError("path outside Ventor workspace")
        return path

    def list(self, rel: str = ".") -> list[str]:
        return [item.name for item in self._path(rel).iterdir()]

    def read(self, rel: str) -> str:
        return self._path(rel).read_text(encoding="utf-8")

    def write(self, rel: str, text: str) -> str:
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path.relative_to(self.root))

    def run_safe(self, argv: list[str]):
        if not argv:
            raise PermissionError("executable is required")
        executable = Path(str(argv[0])).name.lower()
        if executable not in {"python", "python.exe"}:
            raise PermissionError("only Python execution is available through the isolated runner")
        source_parts = list(argv[1:])
        if not source_parts:
            raise PermissionError("Python execution requires a source argument")
        if source_parts[0] == "-c":
            if len(source_parts) != 2:
                raise PermissionError("python -c requires exactly one source argument")
            source = str(source_parts[1])
        elif source_parts[0] == "-m":
            raise PermissionError("python -m is not permitted by the isolated runner")
        else:
            script = self._path(str(source_parts[0]))
            if script.suffix.lower() != ".py":
                raise PermissionError("only workspace .py files may be executed")
            source = script.read_text(encoding="utf-8")
        try:
            result = self.isolator.execute(source, SandboxPolicy())
        except IsolationUnavailable as exc:
            raise SandboxExecutionDenied(str(exc)) from exc
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                "timed_out": result.timed_out, "isolated": True}
