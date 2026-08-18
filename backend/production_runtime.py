from __future__ import annotations

import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


@dataclass
class _Bucket:
    started: float
    count: int
    touched: float


class BoundedRateLimiter:
    def __init__(self, limit=120, window=60.0, max_keys=10000):
        self.limit = max(1, int(limit)); self.window = max(1.0, float(window)); self.max_keys = max(128, int(max_keys))
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict(); self._lock = Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            for candidate, bucket in list(self._buckets.items()):
                if now - bucket.touched >= self.window: self._buckets.pop(candidate, None)
                else: break
            bucket = self._buckets.get(key)
            if bucket is None or now - bucket.started >= self.window:
                if key in self._buckets: self._buckets.pop(key, None)
                self._buckets[key] = _Bucket(now, 1, now)
                while len(self._buckets) > self.max_keys: self._buckets.popitem(last=False)
                return True, 0
            bucket.touched = now; self._buckets.move_to_end(key)
            if bucket.count >= self.limit:
                return False, max(1, int(self.window - (now - bucket.started)))
            bucket.count += 1
            return True, 0

    def snapshot(self):
        with self._lock:
            return {"keys": len(self._buckets), "limit": self.limit, "window_s": self.window, "max_keys": self.max_keys}


class Metrics:
    def __init__(self):
        self._lock = Lock(); self.requests = 0; self.errors = 0; self.total_latency_ms = 0.0; self.started_at = time.time(); self.routes = {}

    def observe(self, route, latency_ms, error):
        with self._lock:
            self.requests += 1; self.errors += int(error); self.total_latency_ms += latency_ms
            item = self.routes.setdefault(route, {"requests": 0, "errors": 0, "latency_ms": 0.0}); item["requests"] += 1; item["errors"] += int(error); item["latency_ms"] += latency_ms
            if len(self.routes) > 5000: self.routes.pop(next(iter(self.routes)))

    def snapshot(self):
        with self._lock:
            return {"uptime_s": round(max(0.0, time.time() - self.started_at), 2), "requests": self.requests, "errors": self.errors,
                    "avg_latency_ms": round(self.total_latency_ms / self.requests, 2) if self.requests else 0.0,
                    "routes": {k: {"requests": int(v["requests"]), "errors": int(v["errors"]), "avg_latency_ms": round(v["latency_ms"] / max(1, v["requests"]), 2)} for k, v in self.routes.items()}}


class AuditLog:
    def __init__(self): self.enabled = os.getenv("VENTOR_AUDIT_LOG", "1").lower() not in {"0", "false", "no"}
    def event(self, name, **fields): return None


class ProductionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter, metrics, audit, max_body_bytes=2_000_000):
        super().__init__(app); self.limiter = limiter; self.metrics = metrics; self.audit = audit; self.max_body_bytes = max(1024, int(os.getenv("VENTOR_MAX_BODY_BYTES", max_body_bytes)))

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex; start = time.perf_counter()
        client = request.client.host if request.client else "unknown"; allowed, retry = self.limiter.allow(client)
        if not allowed:
            response = JSONResponse({"detail": "Rate limit exceeded", "request_id": request_id}, status_code=429, headers={"Retry-After": str(retry)})
            response.headers["X-Request-ID"] = request_id; return response
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > self.max_body_bytes:
            response = JSONResponse({"detail": "Request body too large", "request_id": request_id}, status_code=413); response.headers["X-Request-ID"] = request_id; return response
        error = False
        try:
            response = await call_next(request); error = response.status_code >= 500; return response
        except Exception:
            error = True; raise
        finally:
            self.metrics.observe(request.url.path, (time.perf_counter() - start) * 1000, error)

    
class ProductionRuntime:
    def __init__(self):
        self.limiter = BoundedRateLimiter(int(os.getenv("VENTOR_RATE_LIMIT", "120")), float(os.getenv("VENTOR_RATE_WINDOW", "60")), int(os.getenv("VENTOR_RATE_MAX_KEYS", "10000")))
        self.metrics = Metrics(); self.audit = AuditLog()
    def snapshot(self): return {"metrics": self.metrics.snapshot(), "rate_limiter": self.limiter.snapshot()}
