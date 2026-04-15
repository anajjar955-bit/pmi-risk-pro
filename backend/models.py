"""
models.py — Complete SQLAlchemy ORM models for the Risk Management Platform
"""
import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime,
    ForeignKey, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship
from backend.database import Base


# ─────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────

class UserStatus(str, enum.Enum):
    pending_payment = "pending_payment"
    pending_whatsapp = "pending_whatsapp"
    pending_approval = "pending_approval"
    activated = "activated"
    expired = "expired"
    suspended = "suspended"


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class RiskType(str, enum.Enum):
    threat = "threat"
    opportunity = "opportunity"


class RiskLevel(str, enum.Enum):
    project = "project"
    program = "program"
    portfolio = "portfolio"


class RiskLifecycle(str, enum.Enum):
    open = "open"
    closed = "closed"
    ongoing = "ongoing"
    cancelled = "cancelled"


class ApprovalStatus(str, enum.Enum):
    draft = "draft"
    under_consultant_review = "under_consultant_review"
    consultant_approved = "consultant_approved"
    under_owner_review = "under_owner_review"
    owner_approved = "owner_approved"
    returned = "returned"
    implementing = "implementing"
    monitoring = "monitoring"
    closed = "closed"


class ResponseStrategy(str, enum.Enum):
    avoid = "avoid"
    mitigate = "mitigate"
    transfer = "transfer"
    accept_active = "accept_active"
    accept_passive = "accept_passive"
    exploit = "exploit"
    enhance = "enhance"
    share = "share"


class PlanWorkflowStatus(str, enum.Enum):
    drafted = "drafted"
    under_consultant_review = "under_consultant_review"
    consultant_approved = "consultant_approved"
    under_owner_review = "under_owner_review"
    owner_approved = "owner_approved"
    returned = "returned"
    effective = "effective"


class TrackingStatus(str, enum.Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    completed = "completed"
    delayed = "delayed"
    cancelled = "cancelled"


class EffectivenessRating(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"
    not_assessed = "not_assessed"


class ActivationCodeStatus(str, enum.Enum):
    unused = "unused"
    used = "used"
    expired = "expired"
    revoked = "revoked"


# ─────────────────────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(200), nullable=False)
    email = Column(String(200), unique=True, index=True, nullable=False)
    mobile = Column(String(30), nullable=True)
    company = Column(String(200), nullable=True)
    country = Column(String(100), nullable=True)
    hashed_password = Column(String(256), nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.user, nullable=False)
    status = Column(SAEnum(UserStatus), default=UserStatus.pending_payment, nullable=False)
    is_active = Column(Boolean, default=True)
    activation_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    activation_requests = relationship("ActivationRequest", back_populates="user", cascade="all, delete-orphan", foreign_keys="[ActivationRequest.user_id]")
    activation_codes = relationship("ActivationCode", back_populates="user", cascade="all, delete-orphan", foreign_keys="[ActivationCode.user_id]")
    audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────
# ACTIVATION
# ─────────────────────────────────────────────────────────────

class ActivationRequest(Base):
    __tablename__ = "activation_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    payment_reference = Column(String(200), nullable=True)
    payment_screenshot_url = Column(String(500), nullable=True)
    whatsapp_note = Column(Text, nullable=True)
    whatsapp_verified = Column(Boolean, default=False)
    admin_notes = Column(Text, nullable=True)
    reviewed_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="pending")  # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="activation_requests", foreign_keys="[ActivationRequest.user_id]")


class ActivationCode(Base):
    __tablename__ = "activation_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    code = Column(String(64), unique=True, index=True, nullable=False)
    status = Column(SAEnum(ActivationCodeStatus), default=ActivationCodeStatus.unused)
    issued_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    duration_days = Column(Integer, default=365)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="activation_codes", foreign_keys="[ActivationCode.user_id]")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=True)
    currency = Column(String(10), default="USD")
    paypal_transaction_id = Column(String(200), nullable=True)
    payment_proof_url = Column(String(500), nullable=True)
    status = Column(String(50), default="pending")  # pending / confirmed / rejected
    confirmed_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
# PROJECT
# ─────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(300), nullable=False)
    project_type = Column(String(100), nullable=True)
    scope_summary = Column(Text, nullable=True)
    key_deliverables = Column(Text, nullable=True)
    assumptions = Column(Text, nullable=True)
    constraints = Column(Text, nullable=True)
    stakeholders = Column(Text, nullable=True)
    contract_value = Column(Float, nullable=True)
    currency = Column(String(10), default="SAR")
    duration_months = Column(Integer, nullable=True)
    start_date = Column(String(20), nullable=True)
    end_date = Column(String(20), nullable=True)
    contingency_pct = Column(Float, default=10.0)
    management_reserve_pct = Column(Float, default=5.0)
    risk_appetite = Column(String(50), default="moderate")
    escalation_threshold_score = Column(Integer, default=15)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="projects")
    uploaded_files = relationship("UploadedFile", back_populates="project", cascade="all, delete-orphan")
    extracted_context = relationship("ExtractedProjectContext", back_populates="project", uselist=False, cascade="all, delete-orphan")
    business_processes = relationship("BusinessProcess", back_populates="project", cascade="all, delete-orphan")
    raci_matrices = relationship("RACIMatrix", back_populates="project", cascade="all, delete-orphan")
    risk_plans = relationship("RiskPlan", back_populates="project", cascade="all, delete-orphan")
    risk_register_items = relationship("RiskRegisterItem", back_populates="project", cascade="all, delete-orphan")
    response_tracking_items = relationship("ResponseTrackingItem", back_populates="project", cascade="all, delete-orphan")
    dashboard_snapshots = relationship("DashboardSnapshot", back_populates="project", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────
# FILES & EXTRACTION
# ─────────────────────────────────────────────────────────────

class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    filename = Column(String(300), nullable=False)
    original_filename = Column(String(300), nullable=False)
    file_type = Column(String(20), nullable=False)  # pdf / docx / txt
    file_size_bytes = Column(Integer, nullable=True)
    storage_path = Column(String(500), nullable=False)
    extracted_text = Column(Text, nullable=True)
    extraction_status = Column(String(30), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="uploaded_files")


class ExtractedProjectContext(Base):
    __tablename__ = "extracted_project_context"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)
    raw_text = Column(Text, nullable=True)
    project_name = Column(String(300), nullable=True)
    project_type = Column(String(100), nullable=True)
    scope_summary = Column(Text, nullable=True)
    key_deliverables = Column(Text, nullable=True)
    assumptions = Column(Text, nullable=True)
    constraints = Column(Text, nullable=True)
    stakeholders = Column(Text, nullable=True)
    owner_obligations = Column(Text, nullable=True)
    consultant_obligations = Column(Text, nullable=True)
    contractor_obligations = Column(Text, nullable=True)
    potential_risk_triggers = Column(Text, nullable=True)
    timeline_clues = Column(Text, nullable=True)
    cost_exposure_clues = Column(Text, nullable=True)
    ai_model_used = Column(String(100), nullable=True)
    extraction_confidence = Column(Float, nullable=True)
    user_reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="extracted_context")


# ─────────────────────────────────────────────────────────────
# BUSINESS PROCESS & RACI
# ─────────────────────────────────────────────────────────────

class BusinessProcess(Base):
    __tablename__ = "business_processes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    party = Column(String(50), nullable=False)  # contractor / consultant / owner
    steps = Column(JSON, nullable=True)  # list of step dicts
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="business_processes")


class RACIMatrix(Base):
    __tablename__ = "raci_matrices"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    activity = Column(String(300), nullable=False)
    activity_ar = Column(String(300), nullable=True)
    project_manager = Column(String(5), default="")
    contractor_team = Column(String(5), default="")
    risk_manager = Column(String(5), default="")
    consultant = Column(String(5), default="")
    owner_rep = Column(String(5), default="")
    portfolio_mgmt = Column(String(5), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="raci_matrices")


# ─────────────────────────────────────────────────────────────
# RISK PLAN
# ─────────────────────────────────────────────────────────────

class RiskPlan(Base):
    __tablename__ = "risk_plans"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    title = Column(String(300), nullable=False)
    version = Column(String(20), default="1.0")
    purpose = Column(Text, nullable=True)
    objectives = Column(Text, nullable=True)
    methodology = Column(Text, nullable=True)
    governance = Column(Text, nullable=True)
    roles_responsibilities = Column(Text, nullable=True)
    escalation_path = Column(Text, nullable=True)
    reporting_frequency = Column(String(100), nullable=True)
    review_cycle = Column(String(100), nullable=True)
    risk_categories = Column(JSON, nullable=True)
    risk_appetite = Column(String(100), nullable=True)
    risk_thresholds = Column(Text, nullable=True)
    probability_scale = Column(JSON, nullable=True)
    impact_scale = Column(JSON, nullable=True)
    scoring_method = Column(String(100), nullable=True)
    qualitative_method = Column(Text, nullable=True)
    quantitative_method = Column(Text, nullable=True)
    response_framework = Column(Text, nullable=True)
    monitoring_approach = Column(Text, nullable=True)
    contingency_reserve_pct = Column(Float, default=10.0)
    management_reserve_pct = Column(Float, default=5.0)
    workflow_status = Column(SAEnum(PlanWorkflowStatus), default=PlanWorkflowStatus.drafted)
    drafted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    consultant_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    consultant_approved_at = Column(DateTime, nullable=True)
    owner_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    owner_approved_at = Column(DateTime, nullable=True)
    effective_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="risk_plans")


# ─────────────────────────────────────────────────────────────
# RISK REGISTER
# ─────────────────────────────────────────────────────────────

class RiskRegisterItem(Base):
    __tablename__ = "risk_register_items"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    risk_id = Column(String(20), nullable=False, index=True)  # e.g. R-001
    level = Column(SAEnum(RiskLevel), default=RiskLevel.project)
    risk_type = Column(SAEnum(RiskType), default=RiskType.threat)
    category = Column(String(100), nullable=False)
    subcategory = Column(String(100), nullable=True)

    # Cause-Event-Impact
    cause = Column(Text, nullable=True)
    event = Column(Text, nullable=True)
    impact_description = Column(Text, nullable=True)
    cei_statement = Column(Text, nullable=True)  # auto-generated composite
    trigger = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    # Scoring
    probability = Column(Integer, default=1)       # 1-5
    cost_impact = Column(Integer, default=1)       # 1-5
    time_impact = Column(Integer, default=1)
    scope_impact = Column(Integer, default=1)
    quality_impact = Column(Integer, default=1)
    reputation_impact = Column(Integer, default=1)
    stakeholder_impact = Column(Integer, default=1)
    composite_impact = Column(Float, default=1.0)  # weighted avg
    score = Column(Float, default=1.0)             # probability × composite_impact
    priority = Column(String(30), default="low")   # low / medium / high / critical

    # Response
    response_strategy = Column(SAEnum(ResponseStrategy), nullable=True)
    risk_owner = Column(String(200), nullable=True)
    action_owner = Column(String(200), nullable=True)
    due_date = Column(String(20), nullable=True)
    response_plan = Column(Text, nullable=True)
    contingency_plan = Column(Text, nullable=True)
    fallback_plan = Column(Text, nullable=True)

    # Residual / Secondary
    residual_probability = Column(Integer, nullable=True)
    residual_impact = Column(Integer, nullable=True)
    residual_score = Column(Float, nullable=True)
    secondary_risk_description = Column(Text, nullable=True)

    # Workflow
    approval_status = Column(SAEnum(ApprovalStatus), default=ApprovalStatus.draft)
    lifecycle_status = Column(SAEnum(RiskLifecycle), default=RiskLifecycle.open)
    comments = Column(Text, nullable=True)
    last_updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="risk_register_items")
    response_tracking = relationship("ResponseTrackingItem", back_populates="risk", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────
# RESPONSE TRACKING
# ─────────────────────────────────────────────────────────────

class ResponseTrackingItem(Base):
    __tablename__ = "response_tracking_items"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    risk_id = Column(Integer, ForeignKey("risk_register_items.id"), nullable=False)
    response_action = Column(Text, nullable=False)
    action_owner = Column(String(200), nullable=True)
    planned_start = Column(String(20), nullable=True)
    planned_finish = Column(String(20), nullable=True)
    actual_finish = Column(String(20), nullable=True)
    progress_pct = Column(Integer, default=0)
    current_status = Column(SAEnum(TrackingStatus), default=TrackingStatus.not_started)
    escalation_required = Column(Boolean, default=False)
    evidence_note = Column(Text, nullable=True)
    effectiveness_rating = Column(SAEnum(EffectivenessRating), default=EffectivenessRating.not_assessed)
    closure_recommendation = Column(Text, nullable=True)
    last_updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="response_tracking_items")
    risk = relationship("RiskRegisterItem", back_populates="response_tracking")


# ─────────────────────────────────────────────────────────────
# DASHBOARD SNAPSHOT
# ─────────────────────────────────────────────────────────────

class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    snapshot_date = Column(DateTime, default=datetime.utcnow)
    total_risks = Column(Integer, default=0)
    high_risks = Column(Integer, default=0)
    medium_risks = Column(Integer, default=0)
    low_risks = Column(Integer, default=0)
    opportunities = Column(Integer, default=0)
    open_risks = Column(Integer, default=0)
    closed_risks = Column(Integer, default=0)
    avg_response_progress = Column(Float, default=0.0)
    escalated_count = Column(Integer, default=0)
    snapshot_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="dashboard_snapshots")


# ─────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(200), nullable=False)
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(60), nullable=True)
    user_agent = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="audit_logs")
