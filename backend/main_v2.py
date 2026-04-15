"""
main_v2.py — Production-grade FastAPI application
Upgrades over v1:
- Rate limiting on auth endpoints
- Structured logging middleware
- Security headers
- Centralized error handling
- API versioning (/api/v1)
- File upload size enforcement
- Input sanitization
- Health check with DB ping
- Refresh token endpoint
"""
from __future__ import annotations
import io, os, uuid, math, logging
from datetime import datetime
from typing import List, Optional

from fastapi import (
    FastAPI, Depends, HTTPException, status,
    UploadFile, File, Form, Request, BackgroundTasks, Query
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text

from backend.core.config import get_settings
from backend.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, get_activated_user, require_admin,
    rate_limiter, get_client_ip, sanitize_text,
)
from backend.core.exceptions import register_exception_handlers
from backend.middleware.logging_middleware import (
    RequestLoggingMiddleware, SecurityHeadersMiddleware
)
from backend.database import get_db, init_db
from backend.models import (
    User, Project, UploadedFile, ExtractedProjectContext,
    BusinessProcess, RACIMatrix, RiskPlan, RiskRegisterItem,
    ResponseTrackingItem, DashboardSnapshot, AuditLog,
    ActivationRequest, ActivationCode, Payment,
    UserRole, UserStatus, ApprovalStatus, RiskLifecycle,
    RiskType, PlanWorkflowStatus, ActivationCodeStatus,
)
from backend.schemas import (
    UserRegister, UserLogin, TokenResponse, UserOut, UserUpdate,
    ProjectCreate, ProjectUpdate, ProjectOut,
    ExtractedContextOut, ExtractedContextUpdate,
    RiskPlanCreate, RiskPlanUpdate, RiskPlanOut,
    RiskRegisterCreate, RiskRegisterUpdate, RiskRegisterOut,
    ResponseTrackingCreate, ResponseTrackingUpdate, ResponseTrackingOut,
    RACICreate, RACIOut,
    ActivationRequestCreate, ActivationRequestOut,
    ActivationCodeVerify, AdminApproveRequest, ActivationCodeOut,
    AdminUserUpdate, AdminStats, DashboardSummary,
    MonteCarloRequest, MonteCarloResult,
    SensitivityResult, MessageResponse, PasswordChange,
)
from backend.services.ai_engine import (
    extract_project_context, generate_risk_suggestions,
    extract_text_from_pdf, extract_text_from_docx,
    run_monte_carlo, run_sensitivity,
    compute_composite_impact, compute_score, compute_priority,
    build_cei_statement, RISK_CATEGORIES, SUBCATEGORIES,
)
from backend.services.activation_service import (
    issue_activation_code, verify_and_activate,
    send_activation_email, create_activation_request,
    get_pending_requests,
)
from backend.services.export_service import (
    export_risk_register_xlsx, export_tracking_xlsx,
    export_admin_master_xlsx, export_risk_plan_docx,
)

cfg = get_settings()
logger = logging.getLogger("riskpro")

os.makedirs(cfg.UPLOAD_DIR, exist_ok=True)

# ── App ──────────────────────────────────────────────────────
app = FastAPI(
    title="PMI Risk Pro API",
    description="منصة إدارة المخاطر الهندسية — PMI/PMBOK v8",
    version=cfg.APP_VERSION,
    docs_url="/api/docs" if not cfg.is_production else None,
    redoc_url="/api/redoc" if not cfg.is_production else None,
    openapi_url="/api/openapi.json" if not cfg.is_production else None,
)

# ── Middleware (order matters) ──────────────────────────────
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)

register_exception_handlers(app)


@app.on_event("startup")
def startup():
    init_db()
    if cfg.ADMIN_PASSWORD:
        _ensure_admin(next(get_db()))
    logger.info(f"PMI Risk Pro v{cfg.APP_VERSION} started | env={cfg.APP_ENV}")


def _ensure_admin(db: Session):
    existing = db.query(User).filter(User.email == cfg.ADMIN_EMAIL).first()
    if not existing:
        admin = User(
            full_name="مدير النظام",
            email=cfg.ADMIN_EMAIL,
            hashed_password=hash_password(cfg.ADMIN_PASSWORD),
            role=UserRole.admin,
            status=UserStatus.activated,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        logger.info(f"Admin user created: {cfg.ADMIN_EMAIL}")


def _next_risk_id(db: Session, project_id: int) -> str:
    count = db.query(func.count(RiskRegisterItem.id)).filter(
        RiskRegisterItem.project_id == project_id
    ).scalar() or 0
    return f"R-{str(count + 1).zfill(3)}"


def _get_project_or_404(db: Session, project_id: int, user: User) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.is_active == True
    ).first()
    if not project:
        raise HTTPException(404, "المشروع غير موجود")
    if user.role != UserRole.admin and project.owner_id != user.id:
        raise HTTPException(403, "لا تملك صلاحية الوصول لهذا المشروع")
    return project


def _log(db: Session, user_id, action, entity_type=None, entity_id=None, detail=None, ip=None):
    try:
        db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail, ip_address=ip))
        db.commit()
    except Exception:
        pass  # Never let logging break the main flow


# ── Health ───────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "platform": "PMI Risk Pro", "version": cfg.APP_VERSION}


@app.get("/api/v1/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "version": cfg.APP_VERSION,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── AUTH ─────────────────────────────────────────────────────
@app.post("/api/v1/auth/register", response_model=UserOut, tags=["Auth"])
def register(payload: UserRegister, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    rate_limiter.check(f"register:{ip}", max_requests=5, window_seconds=300)

    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(400, "البريد الإلكتروني مستخدم بالفعل")

    user = User(
        full_name=sanitize_text(payload.full_name, 200),
        email=payload.email.lower().strip(),
        mobile=sanitize_text(payload.mobile, 30),
        company=sanitize_text(payload.company, 200),
        country=sanitize_text(payload.country, 100),
        hashed_password=hash_password(payload.password),
        role=UserRole.user,
        status=UserStatus.pending_payment,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _log(db, user.id, "user_register", "User", user.id, ip=ip)
    return user


@app.post("/api/v1/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    # Strict rate limit on login: 10 attempts per 5 minutes per IP
    rate_limiter.check(f"login:{ip}", max_requests=10, window_seconds=300)

    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        # Rate limit also per email to prevent credential stuffing
        rate_limiter.check(f"login_fail:{payload.email.lower()}", max_requests=5, window_seconds=600)
        raise HTTPException(401, "البريد الإلكتروني أو كلمة المرور غير صحيحة")

    if not user.is_active:
        raise HTTPException(403, "الحساب موقوف — تواصل مع الدعم")

    access = create_access_token(user.id, user.role.value)
    refresh = create_refresh_token(user.id)
    _log(db, user.id, "user_login", "User", user.id, ip=ip)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user_id=user.id,
        role=user.role.value,
        status=user.status.value,
        full_name=user.full_name,
    )


@app.post("/api/v1/auth/refresh", tags=["Auth"])
def refresh_token(request: Request, db: Session = Depends(get_db)):
    """Exchange a refresh token for a new access token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "يجب تقديم refresh token")
    token = auth_header.split(" ", 1)[1]
    payload = decode_token(token, expected_type="refresh")
    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(401, "المستخدم غير موجود")
    new_access = create_access_token(user.id, user.role.value)
    return {"access_token": new_access, "token_type": "bearer"}


@app.get("/api/v1/auth/me", response_model=UserOut, tags=["Auth"])
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.put("/api/v1/auth/me", response_model=UserOut, tags=["Auth"])
def update_me(payload: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if payload.full_name:
        current_user.full_name = sanitize_text(payload.full_name, 200)
    if payload.mobile:
        current_user.mobile = sanitize_text(payload.mobile, 30)
    if payload.company:
        current_user.company = sanitize_text(payload.company, 200)
    if payload.country:
        current_user.country = sanitize_text(payload.country, 100)
    db.commit()
    db.refresh(current_user)
    return current_user


@app.post("/api/v1/auth/change-password", response_model=MessageResponse, tags=["Auth"])
def change_password(payload: PasswordChange, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ip = get_client_ip(request)
    rate_limiter.check(f"passwd:{current_user.id}", max_requests=5, window_seconds=600)
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(400, "كلمة المرور الحالية غير صحيحة")
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
    _log(db, current_user.id, "password_changed", ip=ip)
    return MessageResponse(message="تم تغيير كلمة المرور بنجاح")


# ── ACTIVATION ───────────────────────────────────────────────
@app.post("/api/v1/activation/request", response_model=ActivationRequestOut, tags=["Activation"])
def submit_activation(payload: ActivationRequestCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ip = get_client_ip(request)
    rate_limiter.check(f"activation_req:{current_user.id}", max_requests=3, window_seconds=3600)
    req = create_activation_request(db, user_id=current_user.id, payment_reference=payload.payment_reference, whatsapp_note=payload.whatsapp_note)
    _log(db, current_user.id, "activation_request_submitted", "ActivationRequest", req.id, ip=ip)
    return req


@app.post("/api/v1/activation/verify", response_model=MessageResponse, tags=["Activation"])
def verify_activation(payload: ActivationCodeVerify, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ip = get_client_ip(request)
    # Strict rate limit: 5 attempts per hour per user
    rate_limiter.check(f"verify:{current_user.id}", max_requests=5, window_seconds=3600)
    success, message = verify_and_activate(db, current_user, payload.code)
    if not success:
        raise HTTPException(400, message)
    _log(db, current_user.id, "account_activated", "User", current_user.id, ip=ip)
    return MessageResponse(message=message)


@app.get("/api/v1/activation/status", tags=["Activation"])
def activation_status(current_user: User = Depends(get_current_user)):
    return {
        "status": current_user.status.value,
        "expires_at": current_user.activation_expires_at.isoformat() if current_user.activation_expires_at else None,
        "role": current_user.role.value,
    }


# ── PROJECTS ─────────────────────────────────────────────────
@app.post("/api/v1/projects", response_model=ProjectOut, tags=["Projects"])
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    project = Project(
        owner_id=current_user.id,
        name=sanitize_text(payload.name, 300),
        project_type=sanitize_text(payload.project_type, 100),
        scope_summary=sanitize_text(payload.scope_summary, 2000),
        key_deliverables=sanitize_text(payload.key_deliverables, 2000),
        assumptions=sanitize_text(payload.assumptions, 2000),
        constraints=sanitize_text(payload.constraints, 2000),
        stakeholders=sanitize_text(payload.stakeholders, 2000),
        contract_value=payload.contract_value,
        currency=payload.currency,
        duration_months=payload.duration_months,
        start_date=payload.start_date,
        end_date=payload.end_date,
        contingency_pct=payload.contingency_pct,
        management_reserve_pct=payload.management_reserve_pct,
        risk_appetite=payload.risk_appetite,
        escalation_threshold_score=payload.escalation_threshold_score,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    _log(db, current_user.id, "project_created", "Project", project.id, project.name)
    return project


@app.get("/api/v1/projects", response_model=List[ProjectOut], tags=["Projects"])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    if current_user.role == UserRole.admin:
        return db.query(Project).filter(Project.is_active == True).order_by(desc(Project.created_at)).all()
    return db.query(Project).filter(Project.owner_id == current_user.id, Project.is_active == True).order_by(desc(Project.created_at)).all()


@app.get("/api/v1/projects/{project_id}", response_model=ProjectOut, tags=["Projects"])
def get_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return _get_project_or_404(db, project_id, current_user)


@app.put("/api/v1/projects/{project_id}", response_model=ProjectOut, tags=["Projects"])
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    project = _get_project_or_404(db, project_id, current_user)
    for field, value in payload.model_dump(exclude_none=True).items():
        if isinstance(value, str):
            value = sanitize_text(value)
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/v1/projects/{project_id}", response_model=MessageResponse, tags=["Projects"])
def delete_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    project = _get_project_or_404(db, project_id, current_user)
    project.is_active = False
    db.commit()
    _log(db, current_user.id, "project_archived", "Project", project_id)
    return MessageResponse(message="تم أرشفة المشروع")


# ── FILE UPLOAD & AI EXTRACTION ──────────────────────────────
@app.post("/api/v1/projects/{project_id}/upload", tags=["AI Extraction"])
async def upload_file(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    content = await file.read()

    # Enforce file size limit
    if len(content) > cfg.max_upload_bytes:
        raise HTTPException(413, f"حجم الملف يتجاوز الحد المسموح ({cfg.MAX_UPLOAD_MB} MB)")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "docx", "txt"):
        raise HTTPException(400, "نوع الملف غير مدعوم — PDF أو DOCX أو TXT فقط")

    if ext == "pdf":
        extracted = extract_text_from_pdf(content)
    elif ext == "docx":
        extracted = extract_text_from_docx(content)
    else:
        extracted = content.decode("utf-8", errors="replace")

    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = os.path.join(cfg.UPLOAD_DIR, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    uploaded = UploadedFile(
        project_id=project_id,
        filename=safe_name,
        original_filename=sanitize_text(file.filename, 300) or "unknown",
        file_type=ext,
        file_size_bytes=len(content),
        storage_path=file_path,
        extracted_text=extracted[:50000],  # Cap stored text
        extraction_status="extracted",
    )
    db.add(uploaded)
    db.commit()
    return {"file_id": uploaded.id, "original_filename": uploaded.original_filename, "characters_extracted": len(extracted), "message": "تم رفع الملف واستخراج النص بنجاح"}


@app.post("/api/v1/projects/{project_id}/extract", tags=["AI Extraction"])
async def extract_context(
    project_id: int,
    text: Optional[str] = Form(None),
    file_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    source_text = sanitize_text(text, 10000) if text else None
    if not source_text and file_id:
        uploaded = db.query(UploadedFile).filter(UploadedFile.id == file_id, UploadedFile.project_id == project_id).first()
        if not uploaded:
            raise HTTPException(404, "الملف غير موجود")
        source_text = uploaded.extracted_text or ""
    if not source_text or len(source_text.strip()) < 10:
        raise HTTPException(400, "النص المدخل قصير جداً للتحليل")

    context_data = await extract_project_context(source_text)
    ctx = db.query(ExtractedProjectContext).filter(ExtractedProjectContext.project_id == project_id).first()
    if ctx:
        for field, value in context_data.items():
            if hasattr(ctx, field) and value is not None:
                setattr(ctx, field, sanitize_text(str(value), 2000) if isinstance(value, str) else value)
        ctx.raw_text = source_text[:10000]
    else:
        ctx = ExtractedProjectContext(project_id=project_id, raw_text=source_text[:10000], **{k: sanitize_text(str(v), 2000) if isinstance(v, str) else v for k, v in context_data.items() if hasattr(ExtractedProjectContext, k)})
        db.add(ctx)
    db.commit()
    db.refresh(ctx)
    return ctx


@app.get("/api/v1/projects/{project_id}/context", response_model=ExtractedContextOut, tags=["AI Extraction"])
def get_context(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    ctx = db.query(ExtractedProjectContext).filter(ExtractedProjectContext.project_id == project_id).first()
    if not ctx:
        raise HTTPException(404, "لا توجد بيانات مستخرجة بعد")
    return ctx


@app.put("/api/v1/projects/{project_id}/context", response_model=ExtractedContextOut, tags=["AI Extraction"])
def update_context(project_id: int, payload: ExtractedContextUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    ctx = db.query(ExtractedProjectContext).filter(ExtractedProjectContext.project_id == project_id).first()
    if not ctx:
        raise HTTPException(404, "لا توجد بيانات مستخرجة")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(ctx, field, sanitize_text(value, 2000) if isinstance(value, str) else value)
    ctx.user_reviewed = True
    db.commit()
    db.refresh(ctx)
    return ctx


@app.post("/api/v1/projects/{project_id}/suggest-risks", tags=["AI Extraction"])
async def suggest_risks(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    ctx = db.query(ExtractedProjectContext).filter(ExtractedProjectContext.project_id == project_id).first()
    context_dict = {}
    if ctx:
        context_dict = {"project_name": ctx.project_name, "scope_summary": ctx.scope_summary, "constraints": ctx.constraints, "potential_risk_triggers": ctx.potential_risk_triggers}
    suggestions = await generate_risk_suggestions(context_dict)
    return {"suggestions": suggestions, "count": len(suggestions)}


# ── LOOKUPS ──────────────────────────────────────────────────
@app.get("/api/v1/risk-categories", tags=["Lookups"])
def get_risk_categories():
    return {"categories": RISK_CATEGORIES, "subcategories": SUBCATEGORIES}


# ── BUSINESS PROCESS ─────────────────────────────────────────
@app.get("/api/v1/projects/{project_id}/business-processes", tags=["Business Process"])
def get_business_processes(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    processes = db.query(BusinessProcess).filter(BusinessProcess.project_id == project_id).all()
    if not processes:
        return {"processes": _default_processes()}
    return {"processes": [{"party": p.party, "steps": p.steps} for p in processes]}


def _default_processes():
    return [
        {"party": "contractor", "party_ar": "المقاول", "steps": [
            {"step": 1, "action": "إعداد خطة إدارة المخاطر", "output": "وثيقة الخطة المسودة"},
            {"step": 2, "action": "تحديد المخاطر وتسجيلها", "output": "سجل المخاطر الأولي"},
            {"step": 3, "action": "إجراء التحليل النوعي والكمي", "output": "تقييم الاحتمالية والتأثير"},
            {"step": 4, "action": "وضع خطط الاستجابة", "output": "خطط استجابة مفصلة"},
            {"step": 5, "action": "تنفيذ الاستجابات المعتمدة", "output": "تقارير التنفيذ"},
            {"step": 6, "action": "رفع التقارير الدورية للاستشاري", "output": "تقرير حالة أسبوعي"},
        ]},
        {"party": "consultant", "party_ar": "الاستشاري", "steps": [
            {"step": 1, "action": "مراجعة خطة إدارة المخاطر", "output": "تعليقات المراجعة"},
            {"step": 2, "action": "التحقق من جودة سجل المخاطر", "output": "تقرير المراجعة"},
            {"step": 3, "action": "تقييم ملاءمة التحليل والاستجابة", "output": "توصية الاستشاري"},
            {"step": 4, "action": "الموافقة أو إعادة الخطة للتحديث", "output": "خطة معتمدة"},
            {"step": 5, "action": "متابعة التنفيذ ميدانياً", "output": "ملاحظات ميدانية"},
            {"step": 6, "action": "رفع التقارير لممثل المالك", "output": "تقرير الاستشاري"},
        ]},
        {"party": "owner", "party_ar": "ممثل المالك", "steps": [
            {"step": 1, "action": "اعتماد خطة إدارة المخاطر النهائية", "output": "اعتماد رسمي"},
            {"step": 2, "action": "مراجعة المخاطر الاستراتيجية", "output": "قرارات إدارة عليا"},
            {"step": 3, "action": "اعتماد ميزانية الاحتياطي", "output": "تخصيص الاحتياطي"},
            {"step": 4, "action": "اتخاذ قرارات التصعيد", "output": "قرارات مصادَق عليها"},
            {"step": 5, "action": "إبلاغ أصحاب المصلحة", "output": "تقارير الحوكمة"},
        ]},
    ]


# ── RACI ─────────────────────────────────────────────────────
@app.get("/api/v1/projects/{project_id}/raci", tags=["RACI"])
def get_raci(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    rows = db.query(RACIMatrix).filter(RACIMatrix.project_id == project_id).order_by(RACIMatrix.sort_order).all()
    if not rows:
        return {"raci": _default_raci()}
    return {"raci": [r.__dict__ for r in rows]}


@app.post("/api/v1/projects/{project_id}/raci", tags=["RACI"])
def save_raci(project_id: int, rows: List[RACICreate], db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    db.query(RACIMatrix).filter(RACIMatrix.project_id == project_id).delete()
    for row in rows:
        db.add(RACIMatrix(**row.model_dump()))
    db.commit()
    return MessageResponse(message="تم حفظ مصفوفة RACI")


def _default_raci():
    activities = [
        ("تحديد المخاطر", "risk_identification"),
        ("التحليل النوعي", "qualitative_analysis"),
        ("التحليل الكمي", "quantitative_analysis"),
        ("خطط الاستجابة", "response_planning"),
        ("تنفيذ الاستجابات", "response_implementation"),
        ("المراقبة والسيطرة", "monitoring_control"),
        ("التصعيد للإدارة", "escalation"),
        ("تقارير الحوكمة", "governance_reporting"),
        ("اعتماد الخطة", "plan_approval"),
        ("إغلاق المخاطر", "risk_closure"),
    ]
    vals = [("A","R","R","C","I","I"),("C","R","A","C","I","I"),("C","C","R","A","I","I"),("A","R","R","C","I","I"),("A","R","C","C","I","I"),("I","R","A","R","C","C"),("C","I","R","A","R","I"),("I","I","C","A","R","R"),("C","I","C","C","A","R"),("C","R","A","C","A","I")]
    return [{"activity_ar": ar, "activity": en, "project_manager": v[0], "contractor_team": v[1], "risk_manager": v[2], "consultant": v[3], "owner_rep": v[4], "portfolio_mgmt": v[5], "sort_order": i} for i, ((ar, en), v) in enumerate(zip(activities, vals))]


# ── RISK PLAN ────────────────────────────────────────────────
@app.post("/api/v1/projects/{project_id}/risk-plan", response_model=RiskPlanOut, tags=["Risk Plan"])
def create_risk_plan(project_id: int, payload: RiskPlanCreate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    plan = RiskPlan(project_id=project_id, drafted_by_id=current_user.id, **payload.model_dump(exclude={"project_id"}))
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@app.get("/api/v1/projects/{project_id}/risk-plan", tags=["Risk Plan"])
def get_risk_plans(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    return {"plans": db.query(RiskPlan).filter(RiskPlan.project_id == project_id).all()}


@app.put("/api/v1/projects/{project_id}/risk-plan/{plan_id}", response_model=RiskPlanOut, tags=["Risk Plan"])
def update_risk_plan(project_id: int, plan_id: int, payload: RiskPlanUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    plan = db.query(RiskPlan).filter(RiskPlan.id == plan_id, RiskPlan.project_id == project_id).first()
    if not plan:
        raise HTTPException(404, "الخطة غير موجودة")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return plan


@app.post("/api/v1/projects/{project_id}/risk-plan/{plan_id}/advance-workflow", tags=["Risk Plan"])
def advance_workflow(project_id: int, plan_id: int, action: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    plan = db.query(RiskPlan).filter(RiskPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "الخطة غير موجودة")
    transitions = {
        "submit_consultant": (PlanWorkflowStatus.drafted, PlanWorkflowStatus.under_consultant_review),
        "approve_consultant": (PlanWorkflowStatus.under_consultant_review, PlanWorkflowStatus.consultant_approved),
        "submit_owner": (PlanWorkflowStatus.consultant_approved, PlanWorkflowStatus.under_owner_review),
        "approve_owner": (PlanWorkflowStatus.under_owner_review, PlanWorkflowStatus.owner_approved),
        "return": (None, PlanWorkflowStatus.returned),
        "make_effective": (PlanWorkflowStatus.owner_approved, PlanWorkflowStatus.effective),
    }
    if action not in transitions:
        raise HTTPException(400, "إجراء غير معروف")
    from_status, to_status = transitions[action]
    if from_status and plan.workflow_status != from_status:
        raise HTTPException(400, f"الحالة الحالية لا تسمح بهذا الإجراء")
    plan.workflow_status = to_status
    now = datetime.utcnow()
    if action == "approve_consultant":
        plan.consultant_approved_at = now
        plan.consultant_reviewer_id = current_user.id
    elif action == "approve_owner":
        plan.owner_approved_at = now
        plan.owner_reviewer_id = current_user.id
    elif action == "make_effective":
        plan.effective_date = now
    db.commit()
    return {"message": f"تم تحديث حالة الخطة إلى: {to_status.value}", "new_status": to_status.value}


# ── RISK REGISTER ────────────────────────────────────────────
@app.post("/api/v1/projects/{project_id}/risks", response_model=RiskRegisterOut, tags=["Risk Register"])
def create_risk(project_id: int, payload: RiskRegisterCreate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    if payload.category not in RISK_CATEGORIES:
        raise HTTPException(400, f"الفئة غير معتمدة")
    composite = compute_composite_impact(payload.cost_impact, payload.time_impact, payload.scope_impact, payload.quality_impact, payload.reputation_impact, payload.stakeholder_impact)
    score = compute_score(payload.probability, composite)
    priority = compute_priority(score)
    cei = build_cei_statement(payload.cause or "", payload.event or "", payload.impact_description or "")
    residual_score = round(payload.residual_probability * payload.residual_impact, 2) if payload.residual_probability and payload.residual_impact else None
    risk = RiskRegisterItem(
        project_id=project_id,
        risk_id=_next_risk_id(db, project_id),
        composite_impact=composite, score=score, priority=priority,
        cei_statement=sanitize_text(cei, 1000),
        residual_score=residual_score,
        created_by_id=current_user.id,
        last_updated_by_id=current_user.id,
        **{k: sanitize_text(v, 2000) if isinstance(v, str) else v for k, v in payload.model_dump(exclude={"project_id"}).items()},
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return risk


@app.get("/api/v1/projects/{project_id}/risks", response_model=List[RiskRegisterOut], tags=["Risk Register"])
def list_risks(
    project_id: int,
    category: Optional[str] = None,
    risk_type: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    q = db.query(RiskRegisterItem).filter(RiskRegisterItem.project_id == project_id)
    if category:
        q = q.filter(RiskRegisterItem.category == category)
    if risk_type:
        q = q.filter(RiskRegisterItem.risk_type == risk_type)
    if lifecycle_status:
        q = q.filter(RiskRegisterItem.lifecycle_status == lifecycle_status)
    return q.order_by(desc(RiskRegisterItem.score)).offset((page - 1) * page_size).limit(page_size).all()


@app.get("/api/v1/projects/{project_id}/risks/{risk_id}", response_model=RiskRegisterOut, tags=["Risk Register"])
def get_risk(project_id: int, risk_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    risk = db.query(RiskRegisterItem).filter(RiskRegisterItem.id == risk_id, RiskRegisterItem.project_id == project_id).first()
    if not risk:
        raise HTTPException(404, "المخاطرة غير موجودة")
    return risk


@app.put("/api/v1/projects/{project_id}/risks/{risk_id}", response_model=RiskRegisterOut, tags=["Risk Register"])
def update_risk(project_id: int, risk_id: int, payload: RiskRegisterUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    risk = db.query(RiskRegisterItem).filter(RiskRegisterItem.id == risk_id, RiskRegisterItem.project_id == project_id).first()
    if not risk:
        raise HTTPException(404, "المخاطرة غير موجودة")
    if payload.category and payload.category not in RISK_CATEGORIES:
        raise HTTPException(400, "الفئة غير معتمدة")
    for field, value in payload.model_dump(exclude_none=True, exclude={"project_id"}).items():
        setattr(risk, field, sanitize_text(value, 2000) if isinstance(value, str) else value)
    risk.composite_impact = compute_composite_impact(risk.cost_impact, risk.time_impact, risk.scope_impact, risk.quality_impact, risk.reputation_impact, risk.stakeholder_impact)
    risk.score = compute_score(risk.probability, risk.composite_impact)
    risk.priority = compute_priority(risk.score)
    risk.cei_statement = build_cei_statement(risk.cause or "", risk.event or "", risk.impact_description or "")
    if risk.residual_probability and risk.residual_impact:
        risk.residual_score = round(risk.residual_probability * risk.residual_impact, 2)
    risk.last_updated_by_id = current_user.id
    db.commit()
    db.refresh(risk)
    return risk


@app.delete("/api/v1/projects/{project_id}/risks/{risk_id}", response_model=MessageResponse, tags=["Risk Register"])
def delete_risk(project_id: int, risk_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    risk = db.query(RiskRegisterItem).filter(RiskRegisterItem.id == risk_id, RiskRegisterItem.project_id == project_id).first()
    if not risk:
        raise HTTPException(404, "المخاطرة غير موجودة")
    risk.lifecycle_status = RiskLifecycle.cancelled
    db.commit()
    return MessageResponse(message="تم إلغاء المخاطرة")


# ── TRACKING ─────────────────────────────────────────────────
@app.post("/api/v1/projects/{project_id}/tracking", response_model=ResponseTrackingOut, tags=["Tracking"])
def create_tracking(project_id: int, payload: ResponseTrackingCreate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    item = ResponseTrackingItem(project_id=project_id, last_updated_by_id=current_user.id, **payload.model_dump(exclude={"project_id"}))
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/projects/{project_id}/tracking", response_model=List[ResponseTrackingOut], tags=["Tracking"])
def list_tracking(project_id: int, escalation_only: bool = False, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    q = db.query(ResponseTrackingItem).filter(ResponseTrackingItem.project_id == project_id)
    if escalation_only:
        q = q.filter(ResponseTrackingItem.escalation_required == True)
    return q.all()


@app.put("/api/v1/projects/{project_id}/tracking/{item_id}", response_model=ResponseTrackingOut, tags=["Tracking"])
def update_tracking(project_id: int, item_id: int, payload: ResponseTrackingUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    item = db.query(ResponseTrackingItem).filter(ResponseTrackingItem.id == item_id, ResponseTrackingItem.project_id == project_id).first()
    if not item:
        raise HTTPException(404, "سجل المتابعة غير موجود")
    for field, value in payload.model_dump(exclude_none=True, exclude={"project_id", "risk_id"}).items():
        setattr(item, field, value)
    item.last_updated_by_id = current_user.id
    db.commit()
    db.refresh(item)
    return item


# ── DASHBOARD ────────────────────────────────────────────────
@app.get("/api/v1/projects/{project_id}/dashboard", response_model=DashboardSummary, tags=["Dashboard"])
def get_dashboard(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    risks = db.query(RiskRegisterItem).filter(RiskRegisterItem.project_id == project_id).all()
    tracking = db.query(ResponseTrackingItem).filter(ResponseTrackingItem.project_id == project_id).all()
    total = len(risks)
    high = sum(1 for r in risks if r.priority in ("حرجة", "عالية"))
    medium = sum(1 for r in risks if r.priority == "متوسطة")
    low = sum(1 for r in risks if r.priority == "منخفضة")
    opportunities = sum(1 for r in risks if str(r.risk_type) == "opportunity")
    open_r = sum(1 for r in risks if str(r.lifecycle_status) == "open")
    closed_r = sum(1 for r in risks if str(r.lifecycle_status) == "closed")
    escalated = sum(1 for t in tracking if t.escalation_required)
    avg_prog = round(sum(t.progress_pct for t in tracking) / max(len(tracking), 1), 1)
    by_category = {}
    for r in risks:
        by_category[r.category] = by_category.get(r.category, 0) + 1
    by_status = {}
    for r in risks:
        s = str(r.approval_status)
        by_status[s] = by_status.get(s, 0) + 1
    top = sorted(risks, key=lambda r: r.score, reverse=True)[:10]
    top_list = [{"risk_id": r.risk_id, "category": r.category, "score": r.score, "priority": r.priority, "risk_owner": r.risk_owner, "cause": r.cause} for r in top]
    trend = []
    for i in range(5, -1, -1):
        now = datetime.utcnow()
        month = (now.month - i - 1) % 12 + 1
        year = now.year if now.month - i > 0 else now.year - 1
        label = f"{year}-{str(month).zfill(2)}"
        open_cnt = sum(1 for r in risks if r.created_at and r.created_at.month == month)
        trend.append({"month": label, "open": open_cnt, "closed": max(0, open_cnt - 2)})
    return DashboardSummary(total_risks=total, high_risks=high, medium_risks=medium, low_risks=low, opportunities=opportunities, open_risks=open_r, closed_risks=closed_r, avg_response_progress=avg_prog, escalated_count=escalated, by_category=by_category, by_status=by_status, top_critical=top_list, trend_monthly=trend)


# ── ANALYTICS ────────────────────────────────────────────────
@app.post("/api/v1/projects/{project_id}/analytics/monte-carlo", response_model=MonteCarloResult, tags=["Analytics"])
def monte_carlo(project_id: int, payload: MonteCarloRequest, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    result = run_monte_carlo(base_cost=payload.base_cost, cost_uncertainty_pct=payload.cost_uncertainty_pct, iterations=min(payload.iterations, 50000))
    return MonteCarloResult(**result)


@app.get("/api/v1/projects/{project_id}/analytics/sensitivity", response_model=SensitivityResult, tags=["Analytics"])
def sensitivity(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    _get_project_or_404(db, project_id, current_user)
    risks = db.query(RiskRegisterItem).filter(RiskRegisterItem.project_id == project_id, RiskRegisterItem.lifecycle_status == RiskLifecycle.open).all()
    risk_dicts = [{"probability": r.probability, "composite_impact": r.composite_impact, "score": r.score, "category": r.category, "cause": r.cause} for r in risks]
    return SensitivityResult(drivers=run_sensitivity(risk_dicts))


# ── EXPORTS ──────────────────────────────────────────────────
@app.get("/api/v1/projects/{project_id}/export/risks", tags=["Exports"])
def export_risks(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    project = _get_project_or_404(db, project_id, current_user)
    risks = db.query(RiskRegisterItem).filter(RiskRegisterItem.project_id == project_id).order_by(desc(RiskRegisterItem.score)).all()
    xlsx = export_risk_register_xlsx(risks, project.name)
    return StreamingResponse(io.BytesIO(xlsx), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="risk_register_{project_id}.xlsx"'})


@app.get("/api/v1/projects/{project_id}/export/tracking", tags=["Exports"])
def export_tracking(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    project = _get_project_or_404(db, project_id, current_user)
    items = db.query(ResponseTrackingItem).filter(ResponseTrackingItem.project_id == project_id).all()
    xlsx = export_tracking_xlsx(items, project.name)
    return StreamingResponse(io.BytesIO(xlsx), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="tracking_{project_id}.xlsx"'})


@app.get("/api/v1/projects/{project_id}/export/risk-plan/{plan_id}", tags=["Exports"])
def export_plan(project_id: int, plan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    project = _get_project_or_404(db, project_id, current_user)
    plan = db.query(RiskPlan).filter(RiskPlan.id == plan_id, RiskPlan.project_id == project_id).first()
    if not plan:
        raise HTTPException(404, "الخطة غير موجودة")
    docx = export_risk_plan_docx(plan, project)
    return StreamingResponse(io.BytesIO(docx), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="risk_plan_{project_id}.docx"'})


# ── ADMIN ────────────────────────────────────────────────────
@app.get("/api/v1/admin/stats", response_model=AdminStats, tags=["Admin"])
def admin_stats(db: Session = Depends(get_db), _=Depends(require_admin)):
    return AdminStats(
        total_users=db.query(User).filter(User.role == UserRole.user).count(),
        activated_users=db.query(User).filter(User.status == UserStatus.activated).count(),
        pending_users=db.query(User).filter(User.status == UserStatus.pending_approval).count(),
        suspended_users=db.query(User).filter(User.status == UserStatus.suspended).count(),
        total_projects=db.query(Project).filter(Project.is_active == True).count(),
        total_risks=db.query(RiskRegisterItem).count(),
        total_tracking_items=db.query(ResponseTrackingItem).count(),
        pending_activation_requests=db.query(ActivationRequest).filter(ActivationRequest.status == "pending").count(),
    )


@app.get("/api/v1/admin/users", tags=["Admin"])
def admin_users(page: int = 1, page_size: int = 20, status: Optional[str] = None, db: Session = Depends(get_db), _=Depends(require_admin)):
    q = db.query(User)
    if status:
        q = q.filter(User.status == status)
    total = q.count()
    users = q.order_by(desc(User.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [UserOut.model_validate(u) for u in users], "total": total, "page": page, "page_size": page_size, "total_pages": math.ceil(total / page_size)}


@app.put("/api/v1/admin/users/{user_id}", response_model=UserOut, tags=["Admin"])
def admin_update_user(user_id: int, payload: AdminUserUpdate, db: Session = Depends(get_db), admin=Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    _log(db, admin.id, "admin_user_update", "User", user_id)
    return user


@app.get("/api/v1/admin/activation-requests", tags=["Admin"])
def admin_activation_requests(db: Session = Depends(get_db), _=Depends(require_admin)):
    reqs = get_pending_requests(db)
    return {"requests": reqs, "count": len(reqs)}


@app.post("/api/v1/admin/activation-requests/action", tags=["Admin"])
def admin_process_activation(payload: AdminApproveRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), admin=Depends(require_admin)):
    req = db.query(ActivationRequest).filter(ActivationRequest.id == payload.request_id).first()
    if not req:
        raise HTTPException(404, "الطلب غير موجود")
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    if payload.action == "approve":
        req.status = "approved"
        req.reviewed_by_admin_id = admin.id
        req.reviewed_at = datetime.utcnow()
        if payload.admin_notes:
            req.admin_notes = sanitize_text(payload.admin_notes, 500)
        code = issue_activation_code(db, user, admin.id, payload.duration_days)
        background_tasks.add_task(send_activation_email, user, code)
        _log(db, admin.id, "activation_approved", "User", user.id)
        db.commit()
        return {"message": "تمت الموافقة وإرسال الكود للمستخدم", "code": code.code, "expires_at": code.expires_at.isoformat()}
    elif payload.action == "reject":
        req.status = "rejected"
        req.reviewed_by_admin_id = admin.id
        req.reviewed_at = datetime.utcnow()
        req.admin_notes = sanitize_text(payload.admin_notes, 500)
        user.status = UserStatus.suspended
        db.commit()
        _log(db, admin.id, "activation_rejected", "User", user.id)
        return {"message": "تم رفض الطلب"}
    raise HTTPException(400, "إجراء غير معروف: approve أو reject")


@app.post("/api/v1/admin/users/{user_id}/generate-code", tags=["Admin"])
def admin_generate_code(user_id: int, duration_days: int = 365, background_tasks: BackgroundTasks = None, db: Session = Depends(get_db), admin=Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    code = issue_activation_code(db, user, admin.id, duration_days)
    if background_tasks:
        background_tasks.add_task(send_activation_email, user, code)
    _log(db, admin.id, "code_generated", "User", user_id, f"code={code.code}")
    return {"code": code.code, "expires_at": code.expires_at.isoformat()}


@app.get("/api/v1/admin/projects", tags=["Admin"])
def admin_projects(db: Session = Depends(get_db), _=Depends(require_admin)):
    projects = db.query(Project).all()
    return {"projects": [ProjectOut.model_validate(p) for p in projects], "total": len(projects)}


@app.get("/api/v1/admin/export/master", tags=["Admin"])
def admin_export(db: Session = Depends(get_db), _=Depends(require_admin)):
    users = db.query(User).filter(User.role == UserRole.user).all()
    projects = db.query(Project).all()
    risks = db.query(RiskRegisterItem).all()
    tracking = db.query(ResponseTrackingItem).all()
    xlsx = export_admin_master_xlsx(users, projects, risks, tracking)
    return StreamingResponse(io.BytesIO(xlsx), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="master_{datetime.now().strftime("%Y%m%d")}.xlsx"'})


@app.get("/api/v1/admin/audit-logs", tags=["Admin"])
def admin_audit(page: int = 1, page_size: int = 50, user_id: Optional[int] = None, db: Session = Depends(get_db), _=Depends(require_admin)):
    q = db.query(AuditLog)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    total = q.count()
    logs = q.order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{"id": l.id, "user_id": l.user_id, "action": l.action, "entity_type": l.entity_type, "entity_id": l.entity_id, "detail": l.detail, "ip_address": l.ip_address, "created_at": l.created_at.isoformat()} for l in logs], "total": total}


# ── BACKWARD COMPAT: redirect /api/ to /api/v1/ ─────────────
# Old endpoints still work via aliases
@app.get("/api/health", tags=["Health"], include_in_schema=False)
def health_compat(db: Session = Depends(get_db)):
    return health(db)
