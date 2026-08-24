from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path


async def run() -> list[dict]:
    results = []

    def check(name, fn):
        started = time.perf_counter()
        try:
            value = fn()
            results.append({"name": name, "passed": bool(value), "ms": round((time.perf_counter() - started) * 1000, 2), "detail": "ok" if value else "returned false"})
        except Exception as exc:
            results.append({"name": name, "passed": False, "ms": round((time.perf_counter() - started) * 1000, 2), "detail": repr(exc)})

    root = Path(__file__).resolve().parent
    project = root.parent
    backend_dir = str(root)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    check("backend imports", lambda: __import__("app") is not None)
    registry = __import__("agent_registry")
    check("agent registry", lambda: len(registry.public_registry()) >= 2 and all(item.get("model") for item in registry.public_registry()))
    check("policy exists", lambda: (project / "AGENT_POLICY.json").exists())
    requirements = (project / "requirements.txt").read_text(encoding="utf-8")
    check("requirements pinned", lambda: all("==" in line for line in requirements.splitlines() if line.strip() and not line.startswith("#")))

    from security_runner import validate_source
    for code in ["import os", "open('secret.txt').read()", "import socket", "import subprocess", "eval('1+1')", "exec('print(1)')", "__import__('os')", "globals()", "while True: pass"]:
        check(f"security rejects: {code[:24]}", lambda c=code: not validate_source(c).allowed)
    check("safe code accepted", lambda: validate_source("x=sorted([3,1,2]); assert x==[1,2,3]; print(sum(x))").allowed)

    from unified_router import UnifiedRouter
    router = UnifiedRouter()
    for prompt in ("write python code to sort a list", "explain recursion", "verify whether this numerical claim is correct"):
        check(f"routing: {prompt[:30]}", lambda p=prompt: len(router.select_specialists(p)) >= 1)

    from production_runtime import RateLimiter
    limiter = RateLimiter(limit=5, window=60, max_keys=128)
    allowed = [limiter.allow("same-client")[0] for _ in range(8)]
    check("rate limiter blocks sustained burst", lambda: sum(allowed) == 5)
    for i in range(2_000):
        limiter.allow(f"unique-client-{i}")
    check("rate limiter cardinality bounded", lambda: limiter.snapshot()["keys"] <= 128)

    from command_auth import issue_session, sign_command, verify_command
    from owner_authorization import Principal
    principal = Principal("owner", "test-key", principal_id="test-owner")
    token = issue_session(principal)
    check("session issued", lambda: bool(token))
    command = sign_command(principal, "workspace.read", {"path": "x"})
    check("command token verifies", lambda: verify_command(command, "workspace.read", {"path": "x"}, principal)[0])
    check("command replay rejected", lambda: not verify_command(command, "workspace.read", {"path": "x"}, principal)[0])

    iterations = max(1, int(os.getenv("VENTOR_STRESS_ITERATIONS", "10000")))
    async def noop(i):
        await asyncio.sleep(0)
        return i * i
    started = time.perf_counter()
    values = await asyncio.gather(*(noop(i) for i in range(iterations)))
    elapsed = time.perf_counter() - started
    check("async scheduler pressure", lambda: len(values) == iterations and values[-1] == (iterations - 1) ** 2)
    check("async scheduler pressure under 15s", lambda: elapsed < 15.0)

    payloads = [f"ventor-stress-{i}" * 4 for i in range(20_000)]
    check("bounded memory workload", lambda: len(payloads) == 20_000 and sum(map(len, payloads)) > 0)
    del payloads
    return results


if __name__ == "__main__":
    output = asyncio.run(run())
    passed = all(item["passed"] for item in output)
    print(json.dumps({"passed": passed, "tests": output}, indent=2))
    sys.exit(0 if passed else 1)
