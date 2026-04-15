"""
auth.py — JWT token creation/verification, password hashing, route guards
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, UserRole, UserStatus

# ─────────────────────────────────────────────────────────────
# CONFIG (loaded from env — never hardcoded here)
# ─────────────────────────────────────────────────────────────
SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_IN_ENV_FILE_BEFORE_DEPLOY")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ─────────────────────────────────────────────────────────────
# PASSWORD UTILS
# ─────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ─────────────────────────────────────────────────────────────
# JWT UTILS
# ─────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="رمز الجلسة غير صالح أو منتهي الصلاحية",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─────────────────────────────────────────────────────────────
# DEPENDENCIES
# ─────────────────────────────────────────────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(token)
    user_id: Optional[int] = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="بيانات الجلسة غير مكتملة")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="الحساب موقوف")
    return user


def get_activated_user(current_user: User = Depends(get_current_user)) -> User:
    """Requires user to be fully activated."""
    if current_user.role == UserRole.admin:
        return current_user
    if current_user.status != UserStatus.activated:
        raise HTTPException(
            status_code=403,
            detail="يجب تفعيل الحساب للوصول إلى هذه الخدمة",
        )
    # Check expiry
    if current_user.activation_expires_at and current_user.activation_expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=403,
            detail="انتهت صلاحية الاشتراك — يرجى التجديد",
        )
    return current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Admin-only guard."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=403,
            detail="هذا المسار مخصص للمشرفين فقط",
        )
    return current_user


# ─────────────────────────────────────────────────────────────
# AUDIT HELPER
# ─────────────────────────────────────────────────────────────

def log_action(
    db: Session,
    user_id: Optional[int],
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    detail: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    from backend.models import AuditLog
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail,
        ip_address=ip_address,
    )
    db.add(entry)
    db.commit()
