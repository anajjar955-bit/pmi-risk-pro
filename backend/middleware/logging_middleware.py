"""
middleware/logging_middleware.py — Structured request logging with request IDs.
"""
from __future__ import annotations
import logging, time, uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("riskpro")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    SKIP_PATHS = {"/api/v1/health", "/", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = round((time.perf_counter() - start) * 1000, 1)
            logger.error(f"[{request_id}] {request.method} {request.url.path} → 500 | {duration}ms | {type(exc).__name__}")
            raise
        duration = round((time.perf_counter() - start) * 1000, 1)
        path = request.url.path
        if path not in self.SKIP_PATHS:
            level = logging.WARNING if response.status_code >= 400 else logging.INFO
            client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            if not client_ip and request.client:
                client_ip = request.client.host
            logger.log(level, f"[{request_id}] {request.method} {path} → {response.status_code} | {duration}ms | {client_ip}")
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
