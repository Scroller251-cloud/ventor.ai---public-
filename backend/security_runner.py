from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass

MAX_SOURCE = 32_000
MAX_OUTPUT = 8_000
MAX_NODES = 1_500
MAX_INT_DIGITS = 100
ALLOWED_NODES = {ast.Module, ast.Expr, ast.Assign, ast.AnnAssign, ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.BoolOp, ast.And, ast.Or, ast.Not, ast.IfExp, ast.ListComp, ast.SetComp, ast.DictComp, ast.comprehension, ast.For, ast.While, ast.Break, ast.Continue, ast.AugAssign, ast.Call, ast.keyword, ast.Assert, ast.Return}
ALLOWED_CALLS = {"abs", "all", "any", "bool", "dict", "float", "int", "len", "list", "max", "min", "range", "round", "set", "sorted", "str", "sum", "tuple", "zip", "print"}
BLOCKED_NAMES = {"__import__", "eval", "exec", "compile", "open", "input", "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr", "help", "breakpoint", "exit", "quit", "__builtins__", "__loader__", "__spec__", "__package__", "__file__"}


@dataclass
class SecurityDecision:
    allowed: bool
    reason: str
    violations: list[str]
    node_count: int = 0


@dataclass
class SafeRunResult:
    ran: bool
    passed: bool
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool
    security: SecurityDecision
    note: str


class _Validator(ast.NodeVisitor):
    def __init__(self):
        self.violations = []
        self.nodes = 0

    def generic_visit(self, node):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            self.violations.append("AST node limit exceeded")
            return
        if type(node) not in ALLOWED_NODES:
            self.violations.append(f"blocked syntax: {type(node).__name__}")
            return
        super().generic_visit(node)

    def visit_Name(self, node):
        self.nodes += 1
        if node.id in BLOCKED_NAMES or node.id.startswith("__"):
            self.violations.append(f"blocked name: {node.id}")
        super().generic_visit(node)

    def visit_Attribute(self, node):
        self.violations.append("attribute access is disabled")

    def visit_Import(self, node):
        self.violations.append("imports are disabled")

    def visit_ImportFrom(self, node):
        self.violations.append("imports are disabled")

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_CALLS:
            self.violations.append("only approved pure builtin calls are allowed")
        super().generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, int) and len(str(abs(node.value))) > MAX_INT_DIGITS:
            self.violations.append("integer literal too large")
        super().generic_visit(node)


def validate_source(code):
    if not isinstance(code, str) or not code.strip():
        return SecurityDecision(False, "empty code", ["no code supplied"])
    if len(code) > MAX_SOURCE:
        return SecurityDecision(False, "source too large", [f"source exceeds {MAX_SOURCE} bytes"])
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return SecurityDecision(False, "syntax error", [f"syntax error: {exc.msg}"])
    validator = _Validator()
    validator.visit(tree)
    if validator.violations:
        return SecurityDecision(False, "code rejected by deny-by-default policy", sorted(set(validator.violations)), validator.nodes)
    return SecurityDecision(True, "safe subset accepted", [], validator.nodes)


async def run_safe_python(code, timeout=3.0):
    decision = validate_source(code)
    if not decision.allowed:
        return SafeRunResult(False, False, "", "", None, False, decision, "Rejected before execution. This is intentional.")
    timeout = max(0.1, min(float(timeout), 5.0))
    with tempfile.TemporaryDirectory(prefix="ventor_safe_test_") as directory:
        path = os.path.join(directory, "test.py")
        runner = "import builtins\n_src=" + repr(code) + "\n_runner=exec\n_compiler=compile\n_keep={k:getattr(builtins,k) for k in " + repr(sorted(ALLOWED_CALLS)) + "}\n_keep['AssertionError']=AssertionError\nbuiltins.__dict__.clear(); builtins.__dict__.update(_keep)\n_runner(_compiler(_src,'<ventor-safe-test>','exec'),{'__builtins__':_keep})\n"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(runner)
        try:
            proc = await asyncio.create_subprocess_exec(sys.executable, "-I", "-S", path, cwd=directory, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={"PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1"})
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout)
                return SafeRunResult(True, proc.returncode == 0, out.decode("utf-8", "replace")[-MAX_OUTPUT:], err.decode("utf-8", "replace")[-MAX_OUTPUT:], proc.returncode, False, decision, "Restricted deterministic test subset; not a general sandbox.")
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SafeRunResult(True, False, "", "execution timeout", None, True, decision, "Execution exceeded the enforced timeout.")
        except Exception as exc:
            return SafeRunResult(False, False, "", repr(exc), None, False, decision, "Safe test process could not be started.")
