"""
core/exceptions.py — Centralized exception handlers.
No internal stack traces leak to clients in production.
"""
from __future__ import annotations
import logging, traceback
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("riskpro")

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        rid = getattr(request.state, "request_id", "—")
        if exc.status_code >= 500:
            logger.error(f"[{rid}] HTTP {exc.status_code}: {exc.detail}")
        return JSONResponse(status_code=exc.status_code, content={"error": True, "status_code": exc.status_code, "detail": exc.detail, "request_id": rid})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", "—")
        errors = [{"field": " > ".join(str(l) for l in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": True, "status_code": 422, "detail": "بيانات غير صحيحة", "validation_errors": errors, "request_id": rid})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", "—")
        logger.error(f"[{rid}] Unhandled: {request.method} {request.url.path}:\n" + traceback.format_exc())
        from backend.core.config import get_settings
        detail = str(exc) if get_settings().DEBUG else "خطأ داخلي في الخادم — تم تسجيل المشكلة"
        return JSONResponse(status_code=500, content={"error": True, "status_code": 500, "detail": detail, "request_id": rid})
