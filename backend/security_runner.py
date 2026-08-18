"""Deny-by-default static security validator for generated Python."""
from __future__ import annotations

import ast
from dataclasses import dataclass

MAX_SOURCE = 32000
MAX_NODES = 1500
MAX_INT_DIGITS = 100
BLOCKED_NAMES = {"__import__", "eval", "exec", "compile", "open", "input", "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr", "help", "breakpoint", "exit", "quit", "__builtins__"}
ALLOWED_CALLS = {"abs", "all", "any", "bool", "dict", "float", "int", "len", "list", "max", "min", "range", "round", "set", "sorted", "str", "sum", "tuple", "zip", "print"}


@dataclass(frozen=True)
class SecurityDecision:
    allowed: bool
    reason: str
    violations: list[str]
    node_count: int = 0


class _Validator(ast.NodeVisitor):
    def __init__(self): self.violations: list[str] = []; self.nodes = 0
    def generic_visit(self, node):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            self.violations.append("AST node limit exceeded"); return
        super().generic_visit(node)
    def visit_Name(self, node):
        self.nodes += 1
        if node.id in BLOCKED_NAMES or node.id.startswith("__"): self.violations.append(f"blocked name: {node.id}")
        super().generic_visit(node)
    def visit_Attribute(self, node): self.violations.append("attribute access is disabled")
    def visit_Import(self, node): self.violations.append("imports are disabled")
    def visit_ImportFrom(self, node): self.violations.append("imports are disabled")
    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_CALLS: self.violations.append("only approved pure builtin calls are allowed")
        super().generic_visit(node)
    def visit_Constant(self, node):
        if isinstance(node.value, int) and len(str(abs(node.value))) > MAX_INT_DIGITS: self.violations.append("integer literal too large")
        super().generic_visit(node)


def validate_source(code: str) -> SecurityDecision:
    if not isinstance(code, str) or not code.strip(): return SecurityDecision(False, "empty code", ["no code supplied"])
    if len(code.encode("utf-8")) > MAX_SOURCE: return SecurityDecision(False, "source too large", [f"source exceeds {MAX_SOURCE} bytes"])
    try: tree = ast.parse(code, mode="exec")
    except SyntaxError as exc: return SecurityDecision(False, "syntax error", [f"syntax error: {exc.msg}"])
    validator = _Validator(); validator.visit(tree)
    if validator.violations: return SecurityDecision(False, "code rejected by deny-by-default policy", sorted(set(validator.violations)), validator.nodes)
    return SecurityDecision(True, "safe subset accepted", [], validator.nodes)
