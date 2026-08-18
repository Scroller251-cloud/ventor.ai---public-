from __future__ import annotations

import json
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Awaitable, Callable

from fastapi.responses import JSONResponse


@dataclass(slots=True)
class _Bucket:
    started: float
    count: int
    touched: float


class BoundedRateLimiter:
    """Bounded, thread-safe fixed-window limiter with LRU eviction."""

    def __init__(self, limit: int = 120, window: float = 60.0, max_keys: int = 10_000):
        self.limit = max(1, int(limit))
        self.window = max(1.0, float(window))
        self.max_keys = max(1, int(max_keys))
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = Lock()

    def _prune_expired(self, now: float) -> None:
        while self._buckets:
            key, bucket = next(iter(self._buckets.items()))
            if now - bucket.touched < self.window:
                break
            self._buckets.pop(key, None)

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            self._prune_expired(now)
            bucket = self._buckets.get(key)
            if bucket is None or now - bucket.started >= self.window:
                self._buckets.pop(key, None)
                self._buckets[key] = _Bucket(now, 1, now)
                while len(self._buckets) > self.max_keys:
                    self._buckets.popitem(last=False)
                return True, 0
            bucket.touched = now
            self._buckets.move_to_end(key)
            if bucket.count >= self.limit:
                retry = max(1, int(self.window - (now - bucket.started)))
                return False, retry
            bucket.count += 1
            return True, 0

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "keys": len(self._buckets),
                "limit": self.limit,
                "window_s": self.window,
                "max_keys": self.max_keys,
            }


class Metrics:
    """Low-cardinality, bounded in-process metrics."""

    def __init__(self, max_routes: int = 5_000):
        self._lock = Lock()
        self.requests = 0
        self.errors = 0
        self.total_latency_ms = 0.0
        self.started_at = time.monotonic()
        self.max_routes = max(1, int(max_routes))
        self.routes: OrderedDict[str, dict[str, float]] = OrderedDict()

    def observe(self, route: str, latency_ms: float, error: bool) -> None:
        with self._lock:
            self.requests += 1
            self.errors += int(error)
            self.total_latency_ms += max(0.0, float(latency_ms))
            item = self.routes.get(route)
            if item is None:
                item = {"requests": 0.0, "errors": 0.0, "latency_ms": 0.0}
                self.routes[route] = item
            else:
                self.routes.move_to_end(route)
            item["requests"] += 1
            item["errors"] += int(error)
            item["latency_ms"] += max(0.0, float(latency_ms))
            while len(self.routes) > self.max_routes:
                self.routes.popitem(last=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            requests = self.requests
            return {
                "uptime_s": round(max(0.0, time.monotonic() - self.started_at), 2),
                "requests": requests,
                "errors": self.errors,
                "avg_latency_ms": round(self.total_latency_ms / requests, 2) if requests else 0.0,
                "routes": {
                    key: {
                        "requests": int(value["requests"]),
                        "errors": int(value["errors"]),
                        "avg_latency_ms": round(value["latency_ms"] / max(1.0, value["requests"]), 2),
                    }
                    for key, value in self.routes.items()
                },
            }


class AuditLog:
    """Opt-in JSONL audit sink with serialized writes."""

    def __init__(self):
        self.enabled = os.getenv("VENTOR_AUDIT_LOG", "0").lower() not in {"0", "false", "no"}
        self.path = Path(os.getenv("VENTOR_AUDIT_PATH", "backend/data/audit.jsonl"))
        self._lock = Lock()

    def event(self, name: str, **fields: Any) -> None:
        if not self.enabled:
            return
        record = {"ts": time.time(), "event": str(name), **fields}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            with self._lock:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except OSError:
            return


class ProductionMiddleware:
    """Pure ASGI middleware to avoid BaseHTTPMiddleware request/response overhead."""

    def __init__(self, app: Callable[..., Awaitable[Any]], limiter: BoundedRateLimiter,
                 metrics: Metrics, audit: AuditLog, max_body_bytes: int = 2_000_000):
        self.app = app
        self.limiter = limiter
        self.metrics = metrics
        self.audit = audit
        configured = os.getenv("VENTOR_MAX_BODY_BYTES")
        self.max_body_bytes = max(1024, int(configured)) if configured else max(1024, int(max_body_bytes))

    @staticmethod
    def _headers(headers: list[tuple[bytes, bytes]], request_id: str) -> list[tuple[bytes, bytes]]:
        # Avoid duplicate security/request headers if an upstream middleware already supplied them.
        existing = {key.lower() for key, _ in headers}
        additions = [
            (b"x-request-id", request_id.encode("ascii")),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        ]
        return headers + [(key, value) for key, value in additions if key not in existing]

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        request_id_raw = headers.get(b"x-request-id")
        request_id = request_id_raw.decode("ascii", "ignore")[:128] if request_id_raw else uuid.uuid4().hex
        started = time.perf_counter()
        client = scope.get("client")
        client_host = client[0] if client else "unknown"

        allowed, retry = self.limiter.allow(client_host)
        if not allowed:
            response = JSONResponse(
                {"detail": "Rate limit exceeded", "request_id": request_id},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
            await response(scope, receive, send)
            return

        length = headers.get(b"content-length")
        if length:
            try:
                oversized = int(length) > self.max_body_bytes
            except (TypeError, ValueError):
                oversized = True
            if oversized:
                response = JSONResponse(
                    {"detail": "Request body too large", "request_id": request_id},
                    status_code=413,
                )
                await response(scope, receive, send)
                return

        status_code = 500

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
                message = dict(message)
                message["headers"] = self._headers(list(message.get("headers", [])), request_id)
            await send(message)

        error = False
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            error = True
            raise
        finally:
            error = error or status_code >= 500
            self.metrics.observe(scope.get("path", ""), (time.perf_counter() - started) * 1000, error)


class ProductionRuntime:
    def __init__(self):
        self.limiter = BoundedRateLimiter(
            int(os.getenv("VENTOR_RATE_LIMIT", "120")),
            float(os.getenv("VENTOR_RATE_WINDOW", "60")),
            int(os.getenv("VENTOR_RATE_MAX_KEYS", "10000")),
        )
        self.metrics = Metrics(int(os.getenv("VENTOR_METRICS_MAX_ROUTES", "5000")))
        self.audit = AuditLog()

    def snapshot(self) -> dict[str, Any]:
        return {"metrics": self.metrics.snapshot(), "rate_limiter": self.limiter.snapshot()}
