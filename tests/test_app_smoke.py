from __future__ import annotations

from fastapi.testclient import TestClient


def test_application_imports_and_exposes_core_routes(monkeypatch):
    monkeypatch.setenv("VENTOR_PRODUCTION", "0")
    from backend.app import app
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/ready" in paths
    assert "/metrics" in paths
    assert "/api/chat" in paths
    assert "/api/learn" in paths
    assert "/api/browser/open" in paths


def test_core_health_endpoints_execute():
    from backend.app import app

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.headers["X-Content-Type-Options"] == "nosniff"
        assert health.headers["X-Frame-Options"] == "DENY"

        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "runtime" in metrics.json()


def test_security_policy_is_fail_closed():
    from backend.security_runner import validate_source
    assert validate_source("1 + 2").allowed
    for source in ("import os", "open('x')", "eval('1')", "exec('x=1')", "__import__('os')", "x.__class__"):
        assert not validate_source(source).allowed
