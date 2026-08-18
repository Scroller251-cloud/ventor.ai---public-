"""Fail-closed Docker isolation for untrusted generated code."""
from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .sandbox_policy import SandboxPolicy


class IsolationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class IsolationResult:
    ran: bool
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


class DockerIsolationProvider:
    LINUX_IMAGE = "python:3.12-slim"
    WINDOWS_IMAGE = "python:3.12-windowsservercore-ltsc2025"

    def __init__(self, image: str | None = None):
        self.host = platform.system().lower()
        self.image = image or (self.WINDOWS_IMAGE if self.host == "windows" else self.LINUX_IMAGE)

    def available(self) -> bool:
        return shutil.which("docker") is not None and self._docker_responds()

    def _docker_responds(self) -> bool:
        try:
            result = subprocess.run(["docker", "info", "--format", "{{json .ServerVersion}}"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0 and bool(result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return False

    def _command(self, source_path: Path, name: str, policy: SandboxPolicy) -> list[str]:
        source = source_path.resolve().as_posix()
        if self.host == "windows":
            return ["docker", "run", "--rm", "--name", name, "--isolation=hyperv", "--network=none",
                    "--memory", f"{policy.memory_mb}m", "--cpus", "0.50",
                    "--mount", f"type=bind,src={source},dst=C:/work/main.py,readonly", "--workdir", "C:/work", self.image,
                    "python", "C:/work/main.py"]
        return ["docker", "run", "--rm", "--name", name, "--network=none", "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--memory", f"{policy.memory_mb}m", "--cpus", "0.50",
                "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                "--user", "65532:65532", "--mount", f"type=bind,src={source},dst=/work/main.py,readonly",
                "--workdir", "/work", self.image, "python", "/work/main.py"]

    def execute(self, source: str, policy: SandboxPolicy) -> IsolationResult:
        policy.validate()
        if self.host not in {"linux", "windows"}:
            raise IsolationUnavailable("Only Windows and Linux are supported")
        if not self.available():
            raise IsolationUnavailable("Docker isolation is unavailable; refusing to execute untrusted code")
        with tempfile.TemporaryDirectory(prefix="ventor-isolated-") as directory:
            script = Path(directory) / "main.py"
            script.write_text(source, encoding="utf-8")
            name = "ventor-sbx-" + uuid.uuid4().hex[:16]
            try:
                result = subprocess.run(self._command(script, name, policy), stdin=subprocess.DEVNULL,
                                        capture_output=True, text=True, timeout=policy.timeout_seconds,
                                        env=None if self.host == "windows" else {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"})
                limit = policy.max_output_kb * 1024
                return IsolationResult(True, result.returncode, result.stdout[:limit], result.stderr[:limit])
            except subprocess.TimeoutExpired as exc:
                try:
                    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=5)
                except subprocess.SubprocessError:
                    pass
                return IsolationResult(True, None, (exc.stdout or "")[:policy.max_output_kb * 1024],
                                       (exc.stderr or "")[:policy.max_output_kb * 1024], True)
