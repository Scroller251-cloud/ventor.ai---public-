from __future__ import annotations

from dataclasses import dataclass

from security_runner import validate_source


@dataclass
class TestResult:
    passed: bool
    status: str
    output: str = ""
    error: str | None = None


def security_check(code: str):
    decision = validate_source(code)
    return {"allowed": decision.allowed, "reason": decision.reason, "violations": decision.violations, "node_count": decision.node_count}


async def run_python_test(code: str, timeout: float = 3.0):
    decision = validate_source(code)
    if not decision.allowed:
        return TestResult(False, "rejected", "", decision.reason)
    return TestResult(False, "not_executed", "", "Execution disabled in the API process; use the Docker isolation endpoint for untrusted execution.")
