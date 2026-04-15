"""
activation_service.py — Activation code logic and email dispatch
"""
from __future__ import annotations

import os
import secrets
import string
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import (
    User, ActivationRequest, ActivationCode,
    ActivationCodeStatus, UserStatus
)

# ─────────────────────────────────────────────────────────────
# EMAIL CONFIG (from env)
# ─────────────────────────────────────────────────────────────
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL: str = os.getenv("FROM_EMAIL", "noreply@pmhouse.org")
FROM_NAME: str = os.getenv("FROM_NAME", "منصة PMI Risk Pro")

# ─────────────────────────────────────────────────────────────
# CODE GENERATION
# ─────────────────────────────────────────────────────────────

def generate_activation_code(length: int = 16) -> str:
    """
    Generates a cryptographically secure activation code.
    Format: XXXX-XXXX-XXXX-XXXX (uppercase alphanumeric, no ambiguous chars)
    """
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + string.digits.replace("0", "").replace("1", "")
    raw = "".join(secrets.choice(alphabet) for _ in range(length))
    # Group into 4-char blocks with dashes
    return "-".join(raw[i:i+4] for i in range(0, length, 4))


def issue_activation_code(
    db: Session,
    user: User,
    admin_id: int,
    duration_days: int = 365,
) -> ActivationCode:
    """
    Generate and persist a new activation code for the given user.
    Invalidates any previous unused codes.
    """
    # Revoke previous unused codes
    db.query(ActivationCode).filter(
        ActivationCode.user_id == user.id,
        ActivationCode.status == ActivationCodeStatus.unused,
    ).update({"status": ActivationCodeStatus.revoked})
    db.flush()

    code_str = generate_activation_code()
    expiry = datetime.utcnow() + timedelta(days=duration_days)

    code = ActivationCode(
        user_id=user.id,
        code=code_str,
        status=ActivationCodeStatus.unused,
        issued_by_admin_id=admin_id,
        expires_at=expiry,
        duration_days=duration_days,
    )
    db.add(code)
    db.commit()
    db.refresh(code)
    return code


def verify_and_activate(db: Session, user: User, code_str: str) -> tuple[bool, str]:
    """
    Verify the activation code and activate the user if valid.
    Returns (success: bool, message: str).
    """
    code = db.query(ActivationCode).filter(
        ActivationCode.code == code_str.upper().replace(" ", ""),
        ActivationCode.user_id == user.id,
    ).first()

    if not code:
        return False, "رمز التفعيل غير صحيح"
    if code.status == ActivationCodeStatus.used:
        return False, "تم استخدام هذا الرمز مسبقاً"
    if code.status == ActivationCodeStatus.revoked:
        return False, "تم إلغاء هذا الرمز"
    if code.status == ActivationCodeStatus.expired or code.expires_at < datetime.utcnow():
        code.status = ActivationCodeStatus.expired
        db.commit()
        return False, "انتهت صلاحية رمز التفعيل"

    # Activate
    code.status = ActivationCodeStatus.used
    code.used_at = datetime.utcnow()
    user.status = UserStatus.activated
    user.activation_expires_at = code.expires_at
    db.commit()
    return True, "تم تفعيل حسابك بنجاح"


# ─────────────────────────────────────────────────────────────
# EMAIL DISPATCH
# ─────────────────────────────────────────────────────────────

def _build_activation_email_ar(user: User, code: ActivationCode) -> MIMEMultipart:
    """Arabic activation email template."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔑 رمز تفعيل حسابك — منصة PMI Risk Pro"
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = user.email

    expiry_str = code.expires_at.strftime("%Y-%m-%d")

    html_body = f"""
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: 'Cairo', Tahoma, Arial, sans-serif; direction: rtl; background: #f0f3f7; margin: 0; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .header {{ background: linear-gradient(135deg, #1B4F72, #2E86AB); padding: 30px; text-align: center; }}
  .header h1 {{ color: #fff; margin: 0; font-size: 22px; }}
  .body {{ padding: 30px; }}
  .code-box {{ background: #f5f7fa; border: 2px dashed #1B4F72; border-radius: 10px; padding: 20px; text-align: center; margin: 20px 0; }}
  .code {{ font-size: 28px; font-weight: bold; color: #1B4F72; letter-spacing: 4px; font-family: monospace; }}
  .info {{ background: #EBF5FB; border-right: 4px solid #2E86AB; padding: 12px 16px; border-radius: 6px; margin: 16px 0; font-size: 14px; color: #1A2535; }}
  .footer {{ background: #f5f7fa; padding: 16px; text-align: center; font-size: 12px; color: #5A6A82; }}
  p {{ color: #1A2535; line-height: 1.8; font-size: 15px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🏗 منصة PMI Risk Pro لإدارة المخاطر</h1>
  </div>
  <div class="body">
    <p>عزيزي <strong>{user.full_name}</strong>،</p>
    <p>نُبشّرك بأن طلب تفعيل حسابك قد تمت الموافقة عليه. فيما يلي رمز التفعيل الخاص بك:</p>
    <div class="code-box">
      <div style="font-size:13px; color:#5A6A82; margin-bottom:10px;">رمز التفعيل</div>
      <div class="code">{code.code}</div>
    </div>
    <div class="info">
      📅 صلاحية الاشتراك: {code.duration_days} يوم — تنتهي في {expiry_str}
    </div>
    <p>لتفعيل حسابك:</p>
    <ol style="line-height:2.2; color:#1A2535;">
      <li>سجّل الدخول إلى المنصة</li>
      <li>انتقل إلى صفحة <strong>التفعيل</strong></li>
      <li>أدخل الرمز أعلاه في حقل رمز التفعيل</li>
      <li>اضغط <strong>تحقق</strong> وستحصل على وصول كامل فوراً</li>
    </ol>
    <p style="color:#E74C3C; font-size:13px;">⚠️ لا تشارك هذا الرمز مع أي شخص. الرمز مخصص لك وحدك.</p>
  </div>
  <div class="footer">
    منصة PMI Risk Pro — جميع الحقوق محفوظة<br>
    للدعم الفني: anajjar@pmhouse.org | واتساب: +201005394312
  </div>
</div>
</body>
</html>
"""

    text_body = f"""
عزيزي {user.full_name}،

رمز تفعيل حسابك في منصة PMI Risk Pro:

{code.code}

صلاحية الاشتراك: {code.duration_days} يوم — تنتهي في {expiry_str}

للتفعيل: سجّل الدخول ← التفعيل ← أدخل الرمز ← تحقق

للدعم: anajjar@pmhouse.org | +201005394312
"""

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def _build_activation_email_en(user: User, code: ActivationCode) -> MIMEMultipart:
    """English activation email template (fallback)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔑 Your Activation Code — PMI Risk Pro Platform"
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = user.email
    expiry_str = code.expires_at.strftime("%Y-%m-%d")
    text_body = f"""Dear {user.full_name},

Your PMI Risk Pro account activation code:

{code.code}

Subscription valid for: {code.duration_days} days — expires {expiry_str}

To activate: Login → Activation page → Enter code → Verify

Support: anajjar@pmhouse.org | +201005394312
"""
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    return msg


def send_activation_email(user: User, code: ActivationCode) -> tuple[bool, str]:
    """
    Send activation code email. Returns (success, message).
    If SMTP is not configured, logs the code to console for dev environments.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[EMAIL-DEV] Activation code for {user.email}: {code.code}")
        return True, "تم تسجيل الكود (بيئة التطوير — SMTP غير مُعدّ)"

    try:
        msg = _build_activation_email_ar(user, code)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, [user.email], msg.as_string())
        return True, "تم إرسال رمز التفعيل بنجاح"
    except smtplib.SMTPAuthenticationError:
        return False, "خطأ في مصادقة خادم البريد — تحقق من SMTP_USER وSMTP_PASSWORD"
    except smtplib.SMTPException as exc:
        return False, f"خطأ في إرسال البريد: {exc}"
    except Exception as exc:
        return False, f"خطأ غير متوقع: {exc}"


# ─────────────────────────────────────────────────────────────
# REQUEST HELPERS
# ─────────────────────────────────────────────────────────────

def create_activation_request(
    db: Session, user_id: int,
    payment_reference: Optional[str] = None,
    whatsapp_note: Optional[str] = None,
) -> ActivationRequest:
    req = ActivationRequest(
        user_id=user_id,
        payment_reference=payment_reference,
        whatsapp_note=whatsapp_note,
        status="pending",
    )
    db.add(req)
    # Update user status
    db.query(User).filter(User.id == user_id).update(
        {"status": UserStatus.pending_approval}
    )
    db.commit()
    db.refresh(req)
    return req


def get_pending_requests(db: Session) -> list[ActivationRequest]:
    return db.query(ActivationRequest).filter(
        ActivationRequest.status == "pending"
    ).order_by(ActivationRequest.created_at.desc()).all()
