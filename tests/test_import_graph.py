from __future__ import annotations

import importlib
import pkgutil

import backend


def test_every_backend_module_imports():
    failures: list[str] = []
    for module_info in pkgutil.walk_packages(backend.__path__, backend.__name__ + "."):
        try:
            importlib.import_module(module_info.name)
        except Exception as exc:  # pragma: no cover - failure details are asserted below
            failures.append(f"{module_info.name}: {type(exc).__name__}: {exc}")
    assert not failures, "Backend import failures:\n" + "\n".join(failures)
