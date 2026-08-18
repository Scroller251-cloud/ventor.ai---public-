from __future__ import annotations

import json
import os
import time
import uuid
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


@dataclass
class Bucket:
    started: float
    count: int
    touched: float


class RateLimiter:
    """Bounded, thread-safe fixed-window limiter.

    Pruning is amortized instead of scanning the whole key map on every request.
    This keeps attacker-controlled high-cardinality traffic from turning the
    limiter itself into the hot path.
    """
    def __init__(self, limit: int = 60, window: float = 60.0, max_keys: int = 10_000):
        self.limit = max(1, int(limit))
        self.window = max(1.0, float(window))
        self.max_keys = max(128, int(max_keys))
        self._buckets: OrderedDict[str, Bucket] = OrderedDict()
        self._lock = Lock()
        self._ops = 0

    def _prune(self, now: float, force: bool = False) -> None:
        self._ops += 1
        if not force and self._ops % 256:
            return
        while self._buckets:
            key, bucket = next(iter(self._buckets.items()))
            if now - bucket.touched < self.window and len(self._buckets) <= self.max_keys:
                break
            self._buckets.pop(key, None)
        while len(self._buckets) > self.max_keys:
            self._buckets.popitem(last=False)

    def allow(self, key: str) -> tuple[bool, int]:
        key = str(key or "unknown")[:256]
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            bucket = self._buckets.get(key)
            if bucket is None or now - bucket.started >= self.window:
                self._buckets[key] = Bucket(now, 1, now)
                self._buckets.move_to_end(key)
                if len(self._buckets) > self.max_keys:
                    self._prune(now, force=True)
                return True, 0
            bucket.touched = now
            self._buckets.move_to_end(key)
            if bucket.count >= self.limit:
                return False, max(1, int(self.window - (now - bucket.started)))
            bucket.count += 1
            return True, 0

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            self._prune(time.monotonic(), force=True)
            return {"keys": len(self._buckets), "limit": self.limit, "window_s": self.window, "max_keys": self.max_keys}


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.requests = 0
        self.errors = 0
        self.total_latency_ms = 0.0
        self.routes: dict[str, dict[str, float]] = defaultdict(lambda: {"requests": 0, "errors": 0, "latency_ms": 0.0})
        self.started_at = time.time()

    def observe(self, route: str, latency_ms: float, error: bool) -> None:
        with self._lock:
            self.requests += 1
            self.errors += int(error)
            self.total_latency_ms += latency_ms
            item = self.routes[route]
            item["requests"] += 1
            item["errors"] += int(error)
            item["latency_ms"] += latency_ms

    def snapshot(self) -> dict:
        with self._lock:
            total = self.requests or 1
            routes = {
                name: {
                    "requests": int(value["requests"]),
                    "errors": int(value["errors"]),
                    "avg_latency_ms": round(value["latency_ms"] / max(1, value["requests"]), 2),
                }
                for name, value in self.routes.items()
            }
            return {"uptime_s": round(max(0.0, time.time() - self.started_at), 2), "requests": self.requests, "errors": self.errors, "avg_latency_ms": round(self.total_latency_ms / total, 2), "routes": routes}


metrics = Metrics()
rate_limiter = RateLimiter(int(os.getenv("VENTOR_RATE_LIMIT", "120")), float(os.getenv("VENTOR_RATE_WINDOW", "60")), int(os.getenv("VENTOR_RATE_MAX_KEYS", "10000")))
_audit_lock = Lock()


class ProductionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_bytes: int = 2_000_000):
        super().__init__(app)
        self.max_body_bytes = max(1024, int(max_body_bytes))

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        started = time.perf_counter()
        client = request.client.host if request.client else "unknown"
        allowed, retry_after = rate_limiter.allow(client)
        if not allowed:
            response = JSONResponse({"detail": "Rate limit exceeded", "request_id": request_id}, status_code=429, headers={"Retry-After": str(retry_after), "X-Request-ID": request_id})
            return response
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_bytes:
                    return JSONResponse({"detail": "Request body too large", "request_id": request_id}, status_code=413, headers={"X-Request-ID": request_id})
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length", "request_id": request_id}, status_code=400, headers={"X-Request-ID": request_id})
        error = False
        try:
            response = await call_next(request)
            error = response.status_code >= 500
        except Exception:
            error = True
            raise
        finally:
            metrics.observe(request.url.path, (time.perf_counter() - started) * 1000, error)
        response.headers.update({"X-Request-ID": request_id, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Permissions-Policy": "camera=(), microphone=(), geolocation=()"})
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def install_production(app) -> None:
    app.add_middleware(ProductionMiddleware, max_body_bytes=int(os.getenv("VENTOR_MAX_BODY_BYTES", "2000000")))
    origins = [x.strip() for x in os.getenv("VENTOR_CORS_ORIGINS", "").split(",") if x.strip()]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])


def runtime_snapshot() -> dict:
    return {**metrics.snapshot(), "pid": os.getpid(), "python": os.sys.version.split()[0], "memory_db": os.getenv("VENTOR_MEMORY_DB", "backend/data/memory.db"), "rate_limiter": rate_limiter.snapshot()}


def audit_event(event: str, **fields) -> None:
    if os.getenv("VENTOR_AUDIT_LOG", "1").lower() in {"0", "false", "no"}:
        return
    path = Path(os.getenv("VENTOR_AUDIT_PATH", "backend/data/audit.jsonl"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": time.time(), "event": event, **fields}, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _audit_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError:
        pass


async def readiness(providers) -> dict:
    status = providers.status()
    configured = any(v.get("configured") and v.get("healthy") for v in status.values())
    return {"ready": configured, "providers": status, "reason": "at least one healthy provider is configured" if configured else "no healthy provider is configured"}
