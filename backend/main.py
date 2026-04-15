"""
main.py — FastAPI application entry point
PMI Risk Management Platform — Production-grade SaaS backend
"""
from __future__ import annotations

import io
import os
import math
import uuid
from datetime import datetime
from typing import List, Optional, Any

from fastapi import (
    FastAPI, Depends, HTTPException, status,
    UploadFile, File, Form, Request, BackgroundTasks, Query
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text

from backend.database import get_db, init_db
from backend.models import (
    User, Project, UploadedFile, ExtractedProjectContext,
    BusinessProcess, RACIMatrix, RiskPlan, RiskRegisterItem,
    ResponseTrackingItem, DashboardSnapshot, AuditLog,
    ActivationRequest, ActivationCode, Payment,
    UserRole, UserStatus, ApprovalStatus, RiskLifecycle,
    RiskType, PlanWorkflowStatus, ActivationCodeStatus
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
    SensitivityRequest, SensitivityResult,
    MessageResponse, PaginatedResponse, PasswordChange,
)
from backend.auth import (
    hash_password, verify_password,
    create_access_token, get_current_user,
    get_activated_user, require_admin, log_action
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

# ─────────────────────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────────────────────

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "anajjar@pmhouse.org")

app = FastAPI(
    title="PMI Risk Management Platform API",
    description="منصة إدارة المخاطر وفق معايير PMI — واجهة برمجية كاملة",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    _ensure_admin(next(get_db()))


def _ensure_admin(db: Session):
    """Create admin user from env if not exists."""
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if not admin_password:
        return
    existing = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if not existing:
        admin = User(
            full_name="مدير النظام",
            email=ADMIN_EMAIL,
            hashed_password=hash_password(admin_password),
            role=UserRole.admin,
            status=UserStatus.activated,
            is_active=True,
        )
        db.add(admin)
        db.commit()


# ─────────────────────────────────────────────────────────────
# HELPER: next risk ID for a project
# ─────────────────────────────────────────────────────────────

def _next_risk_id(db: Session, project_id: int) -> str:
    count = db.query(func.count(RiskRegisterItem.id)).filter(
        RiskRegisterItem.project_id == project_id
    ).scalar() or 0
    return f"R-{str(count + 1).zfill(3)}"


# ─────────────────────────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "platform": "PMI Risk Pro", "version": "1.0.0"}

@app.get("/api/v1/health", tags=["Health"])
@app.post("/api/v1/auth/register", response_model=UserOut, tags=["Auth"])
def register_v1(payload: UserRegister, db: Session = Depends(get_db)):
    return register(payload, db)

@app.post("/api/v1/auth/login", response_model=TokenResponse, tags=["Auth"])
def login_v1(payload: UserLogin, db: Session = Depends(get_db)):
    return login(payload, db)

@app.get("/api/v1/auth/me", response_model=UserOut, tags=["Auth"])
def get_me_v1(current_user: User = Depends(get_current_user)):
    return current_user

@app.post("/api/v1/activation/verify", response_model=MessageResponse, tags=["Activation"])
def verify_v1(payload: ActivationCodeVerify, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return verify_activation_code(payload, db, current_user)

@app.get("/api/v1/activation/status", tags=["Activation"])
def status_v1(current_user: User = Depends(get_current_user)):
    return get_activation_status(current_user)

@app.post("/api/v1/activation/request", tags=["Activation"])
def act_req_v1(payload: ActivationRequestCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return submit_activation_request(payload, db, current_user)
    @app.get("/api/v1/projects", response_model=List[ProjectOut], tags=["Projects"])
def list_projects_v1(db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return list_projects(db, current_user)

@app.post("/api/v1/projects", response_model=ProjectOut, tags=["Projects"])
def create_project_v1(payload: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return create_project(payload, db, current_user)

@app.get("/api/v1/projects/{project_id}", response_model=ProjectOut, tags=["Projects"])
def get_project_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return get_project(project_id, db, current_user)

@app.put("/api/v1/projects/{project_id}", response_model=ProjectOut, tags=["Projects"])
def update_project_v1(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return update_project(project_id, payload, db, current_user)

@app.get("/api/v1/risk-categories", tags=["Lookups"])
def get_risk_categories_v1():
    return get_risk_categories()

@app.get("/api/v1/projects/{project_id}/dashboard", response_model=DashboardSummary, tags=["Dashboard"])
def get_dashboard_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return get_dashboard(project_id, db, current_user)

@app.get("/api/v1/projects/{project_id}/risks", response_model=List[RiskRegisterOut], tags=["Risk Register"])
def list_risks_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return list_risks(project_id, db=db, current_user=current_user)

@app.post("/api/v1/projects/{project_id}/risks", response_model=RiskRegisterOut, tags=["Risk Register"])
def create_risk_v1(project_id: int, payload: RiskRegisterCreate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return create_risk(project_id, payload, db, current_user)

@app.put("/api/v1/projects/{project_id}/risks/{risk_id}", response_model=RiskRegisterOut, tags=["Risk Register"])
def update_risk_v1(project_id: int, risk_id: int, payload: RiskRegisterUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return update_risk(project_id, risk_id, payload, db, current_user)

@app.delete("/api/v1/projects/{project_id}/risks/{risk_id}", response_model=MessageResponse, tags=["Risk Register"])
def delete_risk_v1(project_id: int, risk_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return delete_risk(project_id, risk_id, db, current_user)

@app.get("/api/v1/projects/{project_id}/tracking", response_model=List[ResponseTrackingOut], tags=["Tracking"])
def list_tracking_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return list_tracking(project_id, db=db, current_user=current_user)

@app.put("/api/v1/projects/{project_id}/tracking/{item_id}", response_model=ResponseTrackingOut, tags=["Tracking"])
def update_tracking_v1(project_id: int, item_id: int, payload: ResponseTrackingUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return update_tracking(project_id, item_id, payload, db, current_user)

@app.get("/api/v1/projects/{project_id}/risk-plan", tags=["Risk Plan"])
def get_risk_plans_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return get_risk_plans(project_id, db, current_user)

@app.post("/api/v1/projects/{project_id}/risk-plan", response_model=RiskPlanOut, tags=["Risk Plan"])
def create_risk_plan_v1(project_id: int, payload: RiskPlanCreate, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return create_risk_plan(project_id, payload, db, current_user)

@app.post("/api/v1/projects/{project_id}/risk-plan/{plan_id}/advance-workflow", tags=["Risk Plan"])
def advance_workflow_v1(project_id: int, plan_id: int, action: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return advance_plan_workflow(project_id, plan_id, action, db, current_user)

@app.get("/api/v1/projects/{project_id}/raci", tags=["RACI"])
def get_raci_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return get_raci(project_id, db, current_user)

@app.get("/api/v1/projects/{project_id}/business-processes", tags=["Business Process"])
def get_bp_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return get_business_processes(project_id, db, current_user)

@app.post("/api/v1/projects/{project_id}/analytics/monte-carlo", response_model=MonteCarloResult, tags=["Analytics"])
def monte_carlo_v1(project_id: int, payload: MonteCarloRequest, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return monte_carlo(project_id, payload, db, current_user)

@app.get("/api/v1/projects/{project_id}/analytics/sensitivity", response_model=SensitivityResult, tags=["Analytics"])
def sensitivity_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return sensitivity(project_id, db, current_user)

@app.get("/api/v1/projects/{project_id}/export/risks", tags=["Exports"])
def export_risks_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return export_risks_excel(project_id, db, current_user)

@app.get("/api/v1/projects/{project_id}/export/tracking", tags=["Exports"])
def export_tracking_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return export_tracking_excel(project_id, db, current_user)

@app.get("/api/v1/projects/{project_id}/export/risk-plan/{plan_id}", tags=["Exports"])
def export_plan_v1(project_id: int, plan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return export_risk_plan_word(project_id, plan_id, db, current_user)

@app.post("/api/v1/projects/{project_id}/suggest-risks", tags=["AI"])
async def suggest_risks_v1(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_activated_user)):
    return await suggest_risks(project_id, db, current_user)

@app.get("/api/v1/admin/stats", response_model=AdminStats, tags=["Admin"])
def admin_stats_v1(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_stats(db, admin)

@app.get("/api/v1/admin/users", tags=["Admin"])
def admin_users_v1(page: int = 1, page_size: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_list_users(page, page_size, db=db, _admin=admin)

@app.put("/api/v1/admin/users/{user_id}", response_model=UserOut, tags=["Admin"])
def admin_update_user_v1(user_id: int, payload: AdminUserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_update_user(user_id, payload, db, admin)

@app.get("/api/v1/admin/activation-requests", tags=["Admin"])
def admin_act_req_v1(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_list_activation_requests(db, admin)

@app.post("/api/v1/admin/activation-requests/action", tags=["Admin"])
def admin_act_action_v1(payload: AdminApproveRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_process_activation(payload, background_tasks, db, admin)

@app.post("/api/v1/admin/users/{user_id}/generate-code", tags=["Admin"])
def admin_gen_code_v1(user_id: int, duration_days: int = 365, background_tasks: BackgroundTasks = None, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_generate_code(user_id, duration_days, background_tasks, db, admin)

@app.get("/api/v1/admin/projects", tags=["Admin"])
def admin_projects_v1(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_list_projects(db, admin)

@app.get("/api/v1/admin/export/master", tags=["Admin"])
def admin_export_v1(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return admin_export_master(db, admin)
def health_v1(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "healthy" if db_ok else "degraded", "database": "connected" if db_ok else "error", "version": "2.0.0", "timestamp": datetime.utcnow().isoformat()}
@app.get("/api/health", tags=["Health"])
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ─────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=UserOut, tags=["Auth"])
def register(payload: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, "البريد الإلكتروني مستخدم بالفعل")
    user = User(
        full_name=payload.full_name,
        email=payload.email,
        mobile=payload.mobile,
        company=payload.company,
        country=payload.country,
        hashed_password=hash_password(payload.password),
        role=UserRole.user,
        status=UserStatus.pending_payment,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(db, user.id, "user_register", "User", user.id, f"تسجيل مستخدم جديد: {user.email}")
    return user


@app.post("/api/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(401, "البريد الإلكتروني أو كلمة المرور غير صحيحة")
    if not user.is_active:
        raise HTTPException(403, "الحساب موقوف — تواصل مع الدعم")
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    log_action(db, user.id, "user_login", "User", user.id)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        role=user.role.value,
        status=user.status.value,
        full_name=user.full_name,
    )


@app.get("/api/auth/me", response_model=UserOut, tags=["Auth"])
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.put("/api/auth/me", response_model=UserOut, tags=["Auth"])
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@app.post("/api/auth/change-password", response_model=MessageResponse, tags=["Auth"])
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(400, "كلمة المرور الحالية غير صحيحة")
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return MessageResponse(message="تم تغيير كلمة المرور بنجاح")


# ─────────────────────────────────────────────────────────────
# ACTIVATION ROUTES
# ─────────────────────────────────────────────────────────────

@app.post("/api/activation/request", response_model=ActivationRequestOut, tags=["Activation"])
def submit_activation_request(
    payload: ActivationRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    req = create_activation_request(
        db,
        user_id=current_user.id,
        payment_reference=payload.payment_reference,
        whatsapp_note=payload.whatsapp_note,
    )
    log_action(db, current_user.id, "activation_request_submitted", "ActivationRequest", req.id)
    return req


@app.post("/api/activation/verify", response_model=MessageResponse, tags=["Activation"])
def verify_activation_code(
    payload: ActivationCodeVerify,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    success, message = verify_and_activate(db, current_user, payload.code)
    if not success:
        raise HTTPException(400, message)
    log_action(db, current_user.id, "account_activated", "User", current_user.id)
    return MessageResponse(message=message)


@app.get("/api/activation/status", tags=["Activation"])
def get_activation_status(current_user: User = Depends(get_current_user)):
    return {
        "status": current_user.status.value,
        "expires_at": current_user.activation_expires_at.isoformat() if current_user.activation_expires_at else None,
        "role": current_user.role.value,
    }


# ─────────────────────────────────────────────────────────────
# PROJECT ROUTES
# ─────────────────────────────────────────────────────────────

@app.post("/api/projects", response_model=ProjectOut, tags=["Projects"])
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = Project(owner_id=current_user.id, **payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    log_action(db, current_user.id, "project_created", "Project", project.id, project.name)
    return project


@app.get("/api/projects", response_model=List[ProjectOut], tags=["Projects"])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    if current_user.role == UserRole.admin:
        return db.query(Project).filter(Project.is_active == True).all()
    return db.query(Project).filter(
        Project.owner_id == current_user.id,
        Project.is_active == True
    ).all()


@app.get("/api/projects/{project_id}", response_model=ProjectOut, tags=["Projects"])
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = _get_project_or_404(db, project_id, current_user)
    return project


@app.put("/api/projects/{project_id}", response_model=ProjectOut, tags=["Projects"])
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = _get_project_or_404(db, project_id, current_user)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/projects/{project_id}", response_model=MessageResponse, tags=["Projects"])
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = _get_project_or_404(db, project_id, current_user)
    project.is_active = False
    db.commit()
    return MessageResponse(message="تم أرشفة المشروع")


# ─────────────────────────────────────────────────────────────
# FILE UPLOAD & AI EXTRACTION
# ─────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/upload", tags=["AI Extraction"])
async def upload_contract_file(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = _get_project_or_404(db, project_id, current_user)
    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()

    if ext not in ("pdf", "docx", "txt"):
        raise HTTPException(400, "نوع الملف غير مدعوم — PDF أو DOCX أو TXT فقط")

    # Extract text
    if ext == "pdf":
        extracted_text = extract_text_from_pdf(content)
    elif ext == "docx":
        extracted_text = extract_text_from_docx(content)
    else:
        extracted_text = content.decode("utf-8", errors="replace")

    # Save file
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    uploaded = UploadedFile(
        project_id=project_id,
        filename=safe_name,
        original_filename=file.filename or "unknown",
        file_type=ext,
        file_size_bytes=len(content),
        storage_path=file_path,
        extracted_text=extracted_text,
        extraction_status="extracted",
    )
    db.add(uploaded)
    db.commit()

    return {
        "file_id": uploaded.id,
        "original_filename": uploaded.original_filename,
        "file_type": ext,
        "characters_extracted": len(extracted_text),
        "message": "تم رفع الملف واستخراج النص بنجاح",
    }


@app.post("/api/projects/{project_id}/extract", tags=["AI Extraction"])
async def extract_context(
    project_id: int,
    text: Optional[str] = Form(None),
    file_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = _get_project_or_404(db, project_id, current_user)

    source_text = text
    if not source_text and file_id:
        uploaded = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if not uploaded:
            raise HTTPException(404, "الملف غير موجود")
        source_text = uploaded.extracted_text or ""

    if not source_text or len(source_text.strip()) < 10:
        raise HTTPException(400, "النص المدخل قصير جداً للتحليل")

    context_data = await extract_project_context(source_text)

    # Upsert ExtractedProjectContext
    ctx = db.query(ExtractedProjectContext).filter(
        ExtractedProjectContext.project_id == project_id
    ).first()
    if ctx:
        for field, value in context_data.items():
            if hasattr(ctx, field) and value is not None:
                setattr(ctx, field, value)
        ctx.raw_text = source_text[:10000]
    else:
        ctx = ExtractedProjectContext(
            project_id=project_id,
            raw_text=source_text[:10000],
            **{k: v for k, v in context_data.items() if hasattr(ExtractedProjectContext, k)}
        )
        db.add(ctx)

    db.commit()
    db.refresh(ctx)
    log_action(db, current_user.id, "context_extracted", "Project", project_id)
    return ctx


@app.get("/api/projects/{project_id}/context", response_model=ExtractedContextOut, tags=["AI Extraction"])
def get_extracted_context(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    ctx = db.query(ExtractedProjectContext).filter(
        ExtractedProjectContext.project_id == project_id
    ).first()
    if not ctx:
        raise HTTPException(404, "لا توجد بيانات مستخرجة بعد")
    return ctx


@app.put("/api/projects/{project_id}/context", response_model=ExtractedContextOut, tags=["AI Extraction"])
def update_extracted_context(
    project_id: int,
    payload: ExtractedContextUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    ctx = db.query(ExtractedProjectContext).filter(
        ExtractedProjectContext.project_id == project_id
    ).first()
    if not ctx:
        raise HTTPException(404, "لا توجد بيانات مستخرجة")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(ctx, field, value)
    ctx.user_reviewed = True
    db.commit()
    db.refresh(ctx)
    return ctx


@app.post("/api/projects/{project_id}/suggest-risks", tags=["AI Extraction"])
async def suggest_risks(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    ctx = db.query(ExtractedProjectContext).filter(
        ExtractedProjectContext.project_id == project_id
    ).first()
    context_dict = {}
    if ctx:
        context_dict = {
            "project_name": ctx.project_name,
            "scope_summary": ctx.scope_summary,
            "constraints": ctx.constraints,
            "potential_risk_triggers": ctx.potential_risk_triggers,
        }
    suggestions = await generate_risk_suggestions(context_dict)
    return {"suggestions": suggestions, "count": len(suggestions)}


# ─────────────────────────────────────────────────────────────
# RISK CATEGORIES (lookup)
# ─────────────────────────────────────────────────────────────

@app.get("/api/risk-categories", tags=["Lookups"])
def get_risk_categories():
    return {"categories": RISK_CATEGORIES, "subcategories": SUBCATEGORIES}


# ─────────────────────────────────────────────────────────────
# BUSINESS PROCESS
# ─────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/business-processes", tags=["Business Process"])
def get_business_processes(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    processes = db.query(BusinessProcess).filter(BusinessProcess.project_id == project_id).all()
    if not processes:
        # Return default processes
        return {"processes": _default_business_processes()}
    return {"processes": [{"party": p.party, "steps": p.steps, "version": p.version} for p in processes]}


def _default_business_processes():
    return [
        {
            "party": "contractor",
            "party_ar": "المقاول",
            "steps": [
                {"step": 1, "action": "إعداد خطة إدارة المخاطر", "output": "وثيقة الخطة المسودة"},
                {"step": 2, "action": "تحديد المخاطر وتسجيلها في السجل", "output": "سجل المخاطر الأولي"},
                {"step": 3, "action": "إجراء التحليل النوعي والكمي", "output": "تقييم الاحتمالية والتأثير"},
                {"step": 4, "action": "وضع خطط الاستجابة للمخاطر", "output": "خطط استجابة مفصلة"},
                {"step": 5, "action": "تنفيذ الاستجابات المعتمدة", "output": "تقارير التنفيذ"},
                {"step": 6, "action": "رفع التقارير الدورية للاستشاري", "output": "تقرير حالة أسبوعي/شهري"},
                {"step": 7, "action": "تحديث السجل وطلب إغلاق المخاطر المنتهية", "output": "سجل محدّث"},
            ],
        },
        {
            "party": "consultant",
            "party_ar": "الاستشاري",
            "steps": [
                {"step": 1, "action": "مراجعة خطة إدارة المخاطر المُعدّة من المقاول", "output": "تعليقات المراجعة"},
                {"step": 2, "action": "التحقق من اكتمال وجودة سجل المخاطر", "output": "تقرير المراجعة"},
                {"step": 3, "action": "تقييم ملاءمة التحليل وخطط الاستجابة", "output": "توصية الاستشاري"},
                {"step": 4, "action": "الموافقة أو إعادة الخطة للتحديث", "output": "خطة معتمدة أو مُعادة"},
                {"step": 5, "action": "متابعة تنفيذ الاستجابات ميدانياً", "output": "ملاحظات ميدانية"},
                {"step": 6, "action": "رفع التقارير لممثل المالك", "output": "تقرير الاستشاري للمالك"},
                {"step": 7, "action": "التوصية بتصعيد المخاطر الحرجة", "output": "طلب تصعيد رسمي"},
            ],
        },
        {
            "party": "owner",
            "party_ar": "ممثل المالك",
            "steps": [
                {"step": 1, "action": "اعتماد خطة إدارة المخاطر النهائية", "output": "اعتماد رسمي"},
                {"step": 2, "action": "مراجعة المخاطر الاستراتيجية عالية الأولوية", "output": "قرارات إدارة عليا"},
                {"step": 3, "action": "اعتماد الميزانية الاحتياطية للطوارئ", "output": "تخصيص الاحتياطي"},
                {"step": 4, "action": "اتخاذ قرارات التصعيد للمخاطر الحرجة", "output": "قرارات مصادَق عليها"},
                {"step": 5, "action": "إبلاغ أصحاب المصلحة والجهات العليا", "output": "تقارير الحوكمة"},
                {"step": 6, "action": "قرار إغلاق أو إعادة تقييم المخاطر الكبرى", "output": "قرار الإغلاق الرسمي"},
            ],
        },
    ]


# ─────────────────────────────────────────────────────────────
# RACI MATRIX
# ─────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/raci", tags=["RACI"])
def get_raci(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    rows = db.query(RACIMatrix).filter(
        RACIMatrix.project_id == project_id
    ).order_by(RACIMatrix.sort_order).all()
    if not rows:
        return {"raci": _default_raci()}
    return {"raci": [r.__dict__ for r in rows]}


@app.post("/api/projects/{project_id}/raci", tags=["RACI"])
def upsert_raci(
    project_id: int,
    rows: List[RACICreate],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    db.query(RACIMatrix).filter(RACIMatrix.project_id == project_id).delete()
    for row in rows:
        r = RACIMatrix(**row.model_dump())
        db.add(r)
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
    raci_values = [
        ("A", "R", "R", "C", "I", "I"),
        ("C", "R", "A", "C", "I", "I"),
        ("C", "C", "R", "A", "I", "I"),
        ("A", "R", "R", "C", "I", "I"),
        ("A", "R", "C", "C", "I", "I"),
        ("I", "R", "A", "R", "C", "C"),
        ("C", "I", "R", "A", "R", "I"),
        ("I", "I", "C", "A", "R", "R"),
        ("C", "I", "C", "C", "A", "R"),
        ("C", "R", "A", "C", "A", "I"),
    ]
    result = []
    for i, ((ar, en), vals) in enumerate(zip(activities, raci_values)):
        result.append({
            "activity_ar": ar,
            "activity": en,
            "project_manager": vals[0],
            "contractor_team": vals[1],
            "risk_manager": vals[2],
            "consultant": vals[3],
            "owner_rep": vals[4],
            "portfolio_mgmt": vals[5],
            "sort_order": i,
        })
    return result


# ─────────────────────────────────────────────────────────────
# RISK PLAN
# ─────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/risk-plan", response_model=RiskPlanOut, tags=["Risk Plan"])
def create_risk_plan(
    project_id: int,
    payload: RiskPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    plan = RiskPlan(project_id=project_id, drafted_by_id=current_user.id, **payload.model_dump(exclude={"project_id"}))
    db.add(plan)
    db.commit()
    db.refresh(plan)
    log_action(db, current_user.id, "risk_plan_created", "RiskPlan", plan.id)
    return plan


@app.get("/api/projects/{project_id}/risk-plan", tags=["Risk Plan"])
def get_risk_plans(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    plans = db.query(RiskPlan).filter(RiskPlan.project_id == project_id).all()
    return {"plans": plans}


@app.put("/api/projects/{project_id}/risk-plan/{plan_id}", response_model=RiskPlanOut, tags=["Risk Plan"])
def update_risk_plan(
    project_id: int,
    plan_id: int,
    payload: RiskPlanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    plan = db.query(RiskPlan).filter(RiskPlan.id == plan_id, RiskPlan.project_id == project_id).first()
    if not plan:
        raise HTTPException(404, "خطة المخاطر غير موجودة")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    log_action(db, current_user.id, "risk_plan_updated", "RiskPlan", plan.id)
    return plan


@app.post("/api/projects/{project_id}/risk-plan/{plan_id}/advance-workflow", tags=["Risk Plan"])
def advance_plan_workflow(
    project_id: int,
    plan_id: int,
    action: str = Query(..., description="submit_consultant | approve_consultant | submit_owner | approve_owner | return | make_effective"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
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
        raise HTTPException(400, f"الحالة الحالية لا تسمح بهذا الإجراء: {plan.workflow_status}")

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
    log_action(db, current_user.id, f"plan_workflow_{action}", "RiskPlan", plan.id)
    return {"message": f"تم تحديث حالة الخطة إلى: {to_status.value}", "new_status": to_status.value}


# ─────────────────────────────────────────────────────────────
# RISK REGISTER
# ─────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/risks", response_model=RiskRegisterOut, tags=["Risk Register"])
def create_risk(
    project_id: int,
    payload: RiskRegisterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)

    # Validate category
    if payload.category not in RISK_CATEGORIES:
        raise HTTPException(400, f"الفئة غير معتمدة. الفئات المتاحة: {', '.join(RISK_CATEGORIES)}")

    composite = compute_composite_impact(
        payload.cost_impact, payload.time_impact, payload.scope_impact,
        payload.quality_impact, payload.reputation_impact, payload.stakeholder_impact
    )
    score = compute_score(payload.probability, composite)
    priority = compute_priority(score)
    cei = build_cei_statement(
        payload.cause or "", payload.event or "", payload.impact_description or ""
    )

    # Residual
    residual_score = None
    if payload.residual_probability and payload.residual_impact:
        residual_score = round(payload.residual_probability * payload.residual_impact, 2)

    risk = RiskRegisterItem(
        project_id=project_id,
        risk_id=_next_risk_id(db, project_id),
        composite_impact=composite,
        score=score,
        priority=priority,
        cei_statement=cei,
        residual_score=residual_score,
        created_by_id=current_user.id,
        last_updated_by_id=current_user.id,
        **payload.model_dump(exclude={"project_id"}),
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    log_action(db, current_user.id, "risk_created", "RiskRegisterItem", risk.id, risk.risk_id)
    return risk


@app.get("/api/projects/{project_id}/risks", response_model=List[RiskRegisterOut], tags=["Risk Register"])
def list_risks(
    project_id: int,
    category: Optional[str] = None,
    risk_type: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
    approval_status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
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
    if approval_status:
        q = q.filter(RiskRegisterItem.approval_status == approval_status)
    return q.order_by(desc(RiskRegisterItem.score)).offset((page - 1) * page_size).limit(page_size).all()


@app.get("/api/projects/{project_id}/risks/{risk_id}", response_model=RiskRegisterOut, tags=["Risk Register"])
def get_risk(
    project_id: int,
    risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    risk = db.query(RiskRegisterItem).filter(
        RiskRegisterItem.id == risk_id, RiskRegisterItem.project_id == project_id
    ).first()
    if not risk:
        raise HTTPException(404, "المخاطرة غير موجودة")
    return risk


@app.put("/api/projects/{project_id}/risks/{risk_id}", response_model=RiskRegisterOut, tags=["Risk Register"])
def update_risk(
    project_id: int,
    risk_id: int,
    payload: RiskRegisterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    risk = db.query(RiskRegisterItem).filter(
        RiskRegisterItem.id == risk_id, RiskRegisterItem.project_id == project_id
    ).first()
    if not risk:
        raise HTTPException(404, "المخاطرة غير موجودة")

    if payload.category and payload.category not in RISK_CATEGORIES:
        raise HTTPException(400, "الفئة غير معتمدة")

    for field, value in payload.model_dump(exclude_none=True, exclude={"project_id"}).items():
        setattr(risk, field, value)

    # Recalculate scores
    risk.composite_impact = compute_composite_impact(
        risk.cost_impact, risk.time_impact, risk.scope_impact,
        risk.quality_impact, risk.reputation_impact, risk.stakeholder_impact
    )
    risk.score = compute_score(risk.probability, risk.composite_impact)
    risk.priority = compute_priority(risk.score)
    risk.cei_statement = build_cei_statement(risk.cause or "", risk.event or "", risk.impact_description or "")
    if risk.residual_probability and risk.residual_impact:
        risk.residual_score = round(risk.residual_probability * risk.residual_impact, 2)
    risk.last_updated_by_id = current_user.id

    db.commit()
    db.refresh(risk)
    log_action(db, current_user.id, "risk_updated", "RiskRegisterItem", risk.id, risk.risk_id)
    return risk


@app.delete("/api/projects/{project_id}/risks/{risk_id}", response_model=MessageResponse, tags=["Risk Register"])
def delete_risk(
    project_id: int,
    risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    risk = db.query(RiskRegisterItem).filter(
        RiskRegisterItem.id == risk_id, RiskRegisterItem.project_id == project_id
    ).first()
    if not risk:
        raise HTTPException(404, "المخاطرة غير موجودة")
    risk.lifecycle_status = RiskLifecycle.cancelled
    db.commit()
    return MessageResponse(message="تم إلغاء المخاطرة")


# ─────────────────────────────────────────────────────────────
# RESPONSE TRACKING
# ─────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/tracking", response_model=ResponseTrackingOut, tags=["Response Tracking"])
def create_tracking(
    project_id: int,
    payload: ResponseTrackingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    item = ResponseTrackingItem(
        project_id=project_id,
        last_updated_by_id=current_user.id,
        **payload.model_dump(exclude={"project_id"}),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/projects/{project_id}/tracking", response_model=List[ResponseTrackingOut], tags=["Response Tracking"])
def list_tracking(
    project_id: int,
    escalation_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    q = db.query(ResponseTrackingItem).filter(ResponseTrackingItem.project_id == project_id)
    if escalation_only:
        q = q.filter(ResponseTrackingItem.escalation_required == True)
    return q.all()


@app.put("/api/projects/{project_id}/tracking/{item_id}", response_model=ResponseTrackingOut, tags=["Response Tracking"])
def update_tracking(
    project_id: int,
    item_id: int,
    payload: ResponseTrackingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    item = db.query(ResponseTrackingItem).filter(
        ResponseTrackingItem.id == item_id, ResponseTrackingItem.project_id == project_id
    ).first()
    if not item:
        raise HTTPException(404, "سجل المتابعة غير موجود")
    for field, value in payload.model_dump(exclude_none=True, exclude={"project_id", "risk_id"}).items():
        setattr(item, field, value)
    item.last_updated_by_id = current_user.id
    db.commit()
    db.refresh(item)
    return item


# ─────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/dashboard", response_model=DashboardSummary, tags=["Dashboard"])
def get_dashboard(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
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

    by_category: dict = {}
    for r in risks:
        by_category[r.category] = by_category.get(r.category, 0) + 1

    by_status: dict = {}
    for r in risks:
        s = str(r.approval_status)
        by_status[s] = by_status.get(s, 0) + 1

    top_critical = sorted(risks, key=lambda r: r.score, reverse=True)[:10]
    top_list = [
        {
            "risk_id": r.risk_id, "category": r.category,
            "score": r.score, "priority": r.priority,
            "risk_owner": r.risk_owner, "cause": r.cause,
        }
        for r in top_critical
    ]

    # Monthly trend (last 6 months) — simplified
    trend = []
    for i in range(5, -1, -1):
        from datetime import date
        import calendar
        now = datetime.utcnow()
        month = (now.month - i - 1) % 12 + 1
        year = now.year if now.month - i > 0 else now.year - 1
        label = f"{year}-{str(month).zfill(2)}"
        open_cnt = sum(1 for r in risks if r.created_at and r.created_at.month == month)
        trend.append({"month": label, "open": open_cnt, "closed": max(0, open_cnt - 2)})

    return DashboardSummary(
        total_risks=total, high_risks=high, medium_risks=medium, low_risks=low,
        opportunities=opportunities, open_risks=open_r, closed_risks=closed_r,
        avg_response_progress=avg_prog, escalated_count=escalated,
        by_category=by_category, by_status=by_status,
        top_critical=top_list, trend_monthly=trend,
    )


# ─────────────────────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/analytics/monte-carlo", response_model=MonteCarloResult, tags=["Analytics"])
def monte_carlo(
    project_id: int,
    payload: MonteCarloRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    result = run_monte_carlo(
        base_cost=payload.base_cost,
        cost_uncertainty_pct=payload.cost_uncertainty_pct,
        iterations=min(payload.iterations, 50000),
    )
    return MonteCarloResult(**result)


@app.get("/api/projects/{project_id}/analytics/sensitivity", response_model=SensitivityResult, tags=["Analytics"])
def sensitivity(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    _get_project_or_404(db, project_id, current_user)
    risks = db.query(RiskRegisterItem).filter(
        RiskRegisterItem.project_id == project_id,
        RiskRegisterItem.lifecycle_status == RiskLifecycle.open,
    ).all()
    risk_dicts = [
        {
            "probability": r.probability,
            "composite_impact": r.composite_impact,
            "score": r.score,
            "category": r.category,
            "cause": r.cause,
        }
        for r in risks
    ]
    drivers = run_sensitivity(risk_dicts)
    return SensitivityResult(drivers=drivers)


# ─────────────────────────────────────────────────────────────
# EXPORTS
# ─────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/export/risks", tags=["Exports"])
def export_risks_excel(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = _get_project_or_404(db, project_id, current_user)
    risks = db.query(RiskRegisterItem).filter(
        RiskRegisterItem.project_id == project_id
    ).order_by(desc(RiskRegisterItem.score)).all()
    xlsx_bytes = export_risk_register_xlsx(risks, project.name)
    filename = f"risk_register_{project_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/projects/{project_id}/export/tracking", tags=["Exports"])
def export_tracking_excel(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = _get_project_or_404(db, project_id, current_user)
    items = db.query(ResponseTrackingItem).filter(
        ResponseTrackingItem.project_id == project_id
    ).all()
    xlsx_bytes = export_tracking_xlsx(items, project.name)
    filename = f"response_tracking_{project_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/projects/{project_id}/export/risk-plan/{plan_id}", tags=["Exports"])
def export_risk_plan_word(
    project_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_activated_user),
):
    project = _get_project_or_404(db, project_id, current_user)
    plan = db.query(RiskPlan).filter(RiskPlan.id == plan_id, RiskPlan.project_id == project_id).first()
    if not plan:
        raise HTTPException(404, "الخطة غير موجودة")
    docx_bytes = export_risk_plan_docx(plan, project)
    filename = f"risk_plan_{project_id}_{datetime.now().strftime('%Y%m%d')}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────
# ADMIN ROUTES — all protected by require_admin
# ─────────────────────────────────────────────────────────────

@app.get("/api/admin/stats", response_model=AdminStats, tags=["Admin"])
def admin_stats(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return AdminStats(
        total_users=db.query(User).filter(User.role == UserRole.user).count(),
        activated_users=db.query(User).filter(User.status == UserStatus.activated).count(),
        pending_users=db.query(User).filter(User.status == UserStatus.pending_approval).count(),
        suspended_users=db.query(User).filter(User.status == UserStatus.suspended).count(),
        total_projects=db.query(Project).filter(Project.is_active == True).count(),
        total_risks=db.query(RiskRegisterItem).count(),
        total_tracking_items=db.query(ResponseTrackingItem).count(),
        pending_activation_requests=db.query(ActivationRequest).filter(
            ActivationRequest.status == "pending"
        ).count(),
    )


@app.get("/api/admin/users", tags=["Admin"])
def admin_list_users(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    q = db.query(User)
    if status:
        q = q.filter(User.status == status)
    total = q.count()
    users = q.order_by(desc(User.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [UserOut.model_validate(u) for u in users],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size),
    }


@app.put("/api/admin/users/{user_id}", response_model=UserOut, tags=["Admin"])
def admin_update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    log_action(db, admin.id, "admin_user_update", "User", user_id, str(payload.model_dump(exclude_none=True)))
    return user


@app.get("/api/admin/activation-requests", tags=["Admin"])
def admin_list_activation_requests(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    requests = get_pending_requests(db)
    return {"requests": requests, "count": len(requests)}


@app.post("/api/admin/activation-requests/action", tags=["Admin"])
def admin_process_activation(
    payload: AdminApproveRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
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
            req.admin_notes = payload.admin_notes
        user.status = UserStatus.pending_approval  # stays until code verified

        # Issue code and send email in background
        code = issue_activation_code(db, user, admin.id, payload.duration_days)
        background_tasks.add_task(send_activation_email, user, code)
        log_action(db, admin.id, "activation_approved", "User", user.id, f"code={code.code}")
        db.commit()
        return {
            "message": "تمت الموافقة وإرسال الكود للمستخدم",
            "code": code.code,
            "expires_at": code.expires_at.isoformat(),
        }

    elif payload.action == "reject":
        req.status = "rejected"
        req.reviewed_by_admin_id = admin.id
        req.reviewed_at = datetime.utcnow()
        req.admin_notes = payload.admin_notes
        user.status = UserStatus.suspended
        db.commit()
        log_action(db, admin.id, "activation_rejected", "User", user.id)
        return {"message": "تم رفض الطلب"}

    raise HTTPException(400, "إجراء غير معروف: يجب أن يكون approve أو reject")


@app.get("/api/admin/users/{user_id}/activation-codes", tags=["Admin"])
def admin_get_user_codes(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    codes = db.query(ActivationCode).filter(ActivationCode.user_id == user_id).all()
    return {"codes": [ActivationCodeOut.model_validate(c) for c in codes]}


@app.post("/api/admin/users/{user_id}/generate-code", tags=["Admin"])
def admin_generate_code(
    user_id: int,
    duration_days: int = 365,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    code = issue_activation_code(db, user, admin.id, duration_days)
    if background_tasks:
        background_tasks.add_task(send_activation_email, user, code)
    log_action(db, admin.id, "code_generated", "User", user_id, f"code={code.code}")
    return {"code": code.code, "expires_at": code.expires_at.isoformat()}


@app.get("/api/admin/projects", tags=["Admin"])
def admin_list_projects(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    projects = db.query(Project).all()
    return {"projects": [ProjectOut.model_validate(p) for p in projects], "total": len(projects)}


@app.get("/api/admin/export/master", tags=["Admin"])
def admin_export_master(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    users = db.query(User).filter(User.role == UserRole.user).all()
    projects = db.query(Project).all()
    risks = db.query(RiskRegisterItem).all()
    tracking = db.query(ResponseTrackingItem).all()
    xlsx_bytes = export_admin_master_xlsx(users, projects, risks, tracking)
    filename = f"master_export_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/admin/audit-logs", tags=["Admin"])
def admin_audit_logs(
    page: int = 1,
    page_size: int = 50,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    q = db.query(AuditLog)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    total = q.count()
    logs = q.order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [
            {
                "id": log.id, "user_id": log.user_id, "action": log.action,
                "entity_type": log.entity_type, "entity_id": log.entity_id,
                "detail": log.detail, "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
        "total": total,
    }


@app.get("/api/admin/payments", tags=["Admin"])
def admin_list_payments(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    payments = db.query(Payment).order_by(desc(Payment.created_at)).all()
    return {"payments": payments}


# ─────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def _get_project_or_404(db: Session, project_id: int, user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "المشروع غير موجود")
    if user.role != UserRole.admin and project.owner_id != user.id:
        raise HTTPException(403, "لا تملك صلاحية الوصول لهذا المشروع")
    return project
