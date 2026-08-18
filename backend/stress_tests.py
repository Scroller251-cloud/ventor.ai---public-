from __future__ import annotations

import asyncio
import importlib
import time
from pathlib import Path


async def run():
    results = []

    def check(name, fn):
        started = time.perf_counter()
        try:
            value = fn()
            results.append({"name": name, "passed": bool(value), "ms": round((time.perf_counter() - started) * 1000, 2), "detail": "ok" if value else "returned false"})
        except Exception as exc:
            results.append({"name": name, "passed": False, "ms": round((time.perf_counter() - started) * 1000, 2), "detail": repr(exc)})

    root = Path(__file__).resolve().parent
    for module in ("app", "agent_registry", "unified_router", "critic_verifier", "evidence_checker", "security_runner"):
        check(f"import {module}", lambda m=module: importlib.import_module(m) is not None)
    check("policy exists", lambda: (root.parent / "AGENT_POLICY.json").exists())

    from security_runner import validate_source
    blocked = ["import os", "open('secret.txt').read()", "import socket", "import subprocess", "eval('1+1')", "exec('print(1)')", "__import__('os')", "globals()", "while True: pass"]
    for code in blocked:
        check("security rejects: " + code[:24], lambda c=code: not validate_source(c).allowed)
    check("safe code accepted", lambda: validate_source("x=sorted([3,1,2]); assert x==[1,2,3]; print(sum(x))").allowed)

    from unified_router import UnifiedRouter
    router = UnifiedRouter()
    for prompt in ("write python code to sort a list", "explain recursion"):
        check("routing: " + prompt[:30], lambda p=prompt: set(router.select_specialists(p)) == {"Qwen Mentor", "Gemma Mentor"})

    return results


if __name__ == "__main__":
    import json
    output = asyncio.run(run())
    print(json.dumps({"passed": all(item["passed"] for item in output), "tests": output}, indent=2))
