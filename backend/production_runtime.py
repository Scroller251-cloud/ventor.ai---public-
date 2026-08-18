from __future__ import annotations

import json
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


@dataclass(slots=True)
class _Bucket:
    started: float
    count: int
    touched: float


class BoundedRateLimiter:
    """Bounded, thread-safe fixed-window limiter.

    The LRU bound prevents attacker-controlled client identifiers from causing
    unbounded memory growth. For multi-process deployments this remains a
    local guard; a shared reverse-proxy limiter should enforce the global cap.
    """

    def __init__(self, limit: int = 120, window: float = 60.0, max_keys: int = 10_000):
        self.limit = max(1, int(limit))
        self.window = max(1.0, float(window))
        self.max_keys = max(128, int(max_keys))
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
            return {"keys": len(self._buckets), "limit": self.limit, "window_s": self.window, "max_keys": self.max_keys}


class Metrics:
    def __init__(self, max_routes: int = 5_000):
        self._lock = Lock()
        self.requests = 0
        self.errors = 0
        self.total_latency_ms = 0.0
        self.started_at = time.monotonic()
        self.max_routes = max(128, int(max_routes))
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

    def snapshot(self) -> dict:
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
    """Opt-in JSONL audit sink with serialized writes.

    Request middleware deliberately does not write here: synchronous disk I/O
    on every request would make observability a latency bottleneck. Callers
    explicitly record security-sensitive events when needed.
    """

    def __init__(self):
        self.enabled = os.getenv("VENTOR_AUDIT_LOG", "0").lower() not in {"0", "false", "no"}
        self.path = Path(os.getenv("VENTOR_AUDIT_PATH", "backend/data/audit.jsonl"))
        self._lock = Lock()

    def event(self, name: str, **fields) -> None:
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


class ProductionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter, metrics, audit, max_body_bytes=2_000_000):
        super().__init__(app)
        self.limiter = limiter
        self.metrics = metrics
        self.audit = audit
        self.max_body_bytes = max(1024, int(os.getenv("VENTOR_MAX_BODY_BYTES", max_body_bytes)))

    @staticmethod
    def _headers(response, request_id: str) -> None:
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        started = time.perf_counter()
        client = request.client.host if request.client else "unknown"
        allowed, retry = self.limiter.allow(client)
        if not allowed:
            response = JSONResponse(
                {"detail": "Rate limit exceeded", "request_id": request_id},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
            self._headers(response, request_id)
            return response

        length = request.headers.get("content-length")
        if length:
            try:
                oversized = int(length) > self.max_body_bytes
            except ValueError:
                oversized = True
            if oversized:
                response = JSONResponse(
                    {"detail": "Request body too large", "request_id": request_id},
                    status_code=413,
                )
                self._headers(response, request_id)
                return response

        error = False
        try:
            response = await call_next(request)
            error = response.status_code >= 500
            self._headers(response, request_id)
            return response
        except Exception:
            error = True
            raise
        finally:
            self.metrics.observe(request.url.path, (time.perf_counter() - started) * 1000, error)


class ProductionRuntime:
    def __init__(self):
        self.limiter = BoundedRateLimiter(
            int(os.getenv("VENTOR_RATE_LIMIT", "120")),
            float(os.getenv("VENTOR_RATE_WINDOW", "60")),
            int(os.getenv("VENTOR_RATE_MAX_KEYS", "10000")),
        )
        self.metrics = Metrics(int(os.getenv("VENTOR_METRICS_MAX_ROUTES", "5000")))
        self.audit = AuditLog()

    def snapshot(self):
        return {"metrics": self.metrics.snapshot(), "rate_limiter": self.limiter.snapshot()}
