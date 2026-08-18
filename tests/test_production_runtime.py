from __future__ import annotations

from backend.production_runtime import BoundedRateLimiter, Metrics


def test_rate_limiter_is_bounded_and_enforces_window_limit():
    limiter = BoundedRateLimiter(limit=2, window=60, max_keys=3)
    assert limiter.allow("a")[0]
    assert limiter.allow("a")[0]
    allowed, retry = limiter.allow("a")
    assert not allowed
    assert retry >= 1

    for key in ("b", "c", "d", "e"):
        assert limiter.allow(key)[0]
    assert limiter.snapshot()["keys"] <= 3


def test_metrics_are_bounded_and_use_monotonic_uptime():
    metrics = Metrics(max_routes=2)
    metrics.observe("/a", 1.0, False)
    metrics.observe("/b", 2.0, True)
    metrics.observe("/c", 3.0, False)
    snapshot = metrics.snapshot()
    assert snapshot["requests"] == 3
    assert snapshot["errors"] == 1
    assert snapshot["avg_latency_ms"] == 2.0
    assert len(snapshot["routes"]) <= 2
    assert snapshot["uptime_s"] >= 0
