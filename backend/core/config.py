# core package
"""
core/exceptions.py — Centralized exception handlers.
No internal stack traces leak to clients in production.
"""
from __future__ import annotations
import logging, traceback
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse"""
core/config.py — Centralized validated configuration.
All settings from environment variables with strict validation.
"""
from __future__ import annotations
import os, secrets
from functools import lru_cache
from typing import List


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./risk_platform.db")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "anajjar@pmhouse.org")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    ALLOWED_ORIGINS: List[str] = [o.strip() for o in os.getenv("ALLOWED_ORIGINS","http://localhost:3000").split(",") if o.strip()]
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "10"))
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "noreply@pmhouse.org")
    FROM_NAME: str = os.getenv("FROM_NAME", "PMI Risk Pro")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    AI_TIMEOUT: int = int(os.getenv("AI_TIMEOUT_SECONDS", "60"))
    RATE_LIMIT_LOGIN: str = os.getenv("RATE_LIMIT_LOGIN", "10/minute")
    RATE_LIMIT_API: str = os.getenv("RATE_LIMIT_API", "120/minute")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_VERSION: str = "2.0.0"
    API_PREFIX: str = "/api/v1"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    def validate(self) -> "Settings":
        if not self.JWT_SECRET_KEY or len(self.JWT_SECRET_KEY) < 32:
            if self.APP_ENV == "production":
                raise RuntimeError("JWT_SECRET_KEY must be ≥32 chars in production")
            self.JWT_SECRET_KEY = secrets.token_hex(32)
            print("⚠️  [DEV] Auto-generated JWT_SECRET_KEY — set in .env for production")
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings().validate()

from starlette.exceptions import HTTPException """
core/security.py — Production-grade auth: JWT + refresh tokens + RBAC + rate limiting
"""
from __future__ import annotations
import hashlib, time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from backend.core.config import get_settings
from backend.database import get_db

cfg = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{cfg.API_PREFIX}/auth/login")

def hash_password(password: str) -> str:
    if len(password) > 72:
        password = hashlib.sha256(password.encode()).hexdigest()
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    if len(plain) > 72:
        plain = hashlib.sha256(plain.encode()).hexdigest()
    return pwd_context.verify(plain, hashed)

def create_access_token(user_id: int, role: str, extra: Optional[dict] = None) -> str:
    expire = datetime.utcnow() + timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "type": "access", "exp": expire, "iat": datetime.utcnow()}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, cfg.JWT_SECRET_KEY, algorithm=cfg.JWT_ALGORITHM)

def create_refresh_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=cfg.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "type": "refresh", "exp": expire, "iat": datetime.utcnow()}
    return jwt.encode(payload, cfg.JWT_SECRET_KEY, algorithm=cfg.JWT_ALGORITHM)

def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, cfg.JWT_SECRET_KEY, algorithms=[cfg.JWT_ALGORITHM])
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=401, detail="نوع الرمز غير صحيح")
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="رمز الجلسة غير صالح أو منتهي الصلاحية", headers={"WWW-Authenticate": "Bearer"}) from exc

class InMemoryRateLimiter:
    def __init__(self):
        self._windows: Dict[str, list] = defaultdict(list)
    def check(self, key: str, max_requests: int, window_seconds: int) -> None:
        now = time.time()
        self._windows[key] = [t for t in self._windows[key] if now - t < window_seconds]
        if len(self._windows[key]) >= max_requests:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"طلبات كثيرة جداً — حاول بعد {window_seconds} ثانية", headers={"Retry-After": str(window_seconds)})
        self._windows[key].append(now)

rate_limiter = InMemoryRateLimiter()

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    from backend.models import User
    payload = decode_token(token, expected_type="access")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="بيانات الجلسة غير مكتملة")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="الحساب موقوف")
    return user

def get_activated_user(current_user=Depends(get_current_user)):
    from backend.models import UserRole, UserStatus
    if current_user.role == UserRole.admin:
        return current_user
    if current_user.status != UserStatus.activated:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="يجب تفعيل الحساب أولاً")
    if current_user.activation_expires_at and current_user.activation_expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="انتهت صلاحية الاشتراك — يرجى التجديد")
    return current_user

def require_admin(current_user=Depends(get_current_user)):
    from backend.models import UserRole
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="هذا المسار للمشرفين فقط")
    return current_user

def sanitize_text(text, max_length: int = 2000):
    if text is None:
        return None
    cleaned = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\r\t")
    return cleaned[:max_length].strip() or None
as StarletteHTTPException

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
