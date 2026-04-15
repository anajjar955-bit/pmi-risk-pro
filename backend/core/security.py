"""
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
