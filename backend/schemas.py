"""
schemas.py — Pydantic v2 schemas for request/response validation
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, EmailStr, field_validator, model_validator

from backend.models import (
    UserStatus, UserRole, RiskType, RiskLevel, RiskLifecycle,
    ApprovalStatus, ResponseStrategy, PlanWorkflowStatus,
    TrackingStatus, EffectivenessRating, ActivationCodeStatus
)


# ─────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    mobile: Optional[str] = None
    company: Optional[str] = None
    country: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("كلمة المرور يجب أن تكون 8 أحرف على الأقل")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    status: str
    full_name: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# ─────────────────────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: int
    full_name: str
    email: str
    mobile: Optional[str] = None
    company: Optional[str] = None
    country: Optional[str] = None
    role: UserRole
    status: UserStatus
    is_active: bool
    activation_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    company: Optional[str] = None
    country: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# ACTIVATION
# ─────────────────────────────────────────────────────────────

class ActivationRequestCreate(BaseModel):
    payment_reference: Optional[str] = None
    whatsapp_note: Optional[str] = None


class ActivationRequestOut(BaseModel):
    id: int
    user_id: int
    payment_reference: Optional[str] = None
    whatsapp_note: Optional[str] = None
    whatsapp_verified: bool
    status: str
    admin_notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivationCodeVerify(BaseModel):
    code: str


class AdminApproveRequest(BaseModel):
    request_id: int
    action: str  # "approve" | "reject"
    admin_notes: Optional[str] = None
    duration_days: int = 365


class ActivationCodeOut(BaseModel):
    id: int
    user_id: int
    code: str
    status: ActivationCodeStatus
    issued_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────
# PROJECT
# ─────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    project_type: Optional[str] = None
    scope_summary: Optional[str] = None
    key_deliverables: Optional[str] = None
    assumptions: Optional[str] = None
    constraints: Optional[str] = None
    stakeholders: Optional[str] = None
    contract_value: Optional[float] = None
    currency: str = "SAR"
    duration_months: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contingency_pct: float = 10.0
    management_reserve_pct: float = 5.0
    risk_appetite: str = "moderate"
    escalation_threshold_score: int = 15


class ProjectUpdate(ProjectCreate):
    name: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    owner_id: int
    name: str
    project_type: Optional[str] = None
    scope_summary: Optional[str] = None
    contract_value: Optional[float] = None
    currency: str
    duration_months: Optional[int] = None
    risk_appetite: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────
# EXTRACTED CONTEXT
# ─────────────────────────────────────────────────────────────

class ExtractedContextOut(BaseModel):
    id: int
    project_id: int
    project_name: Optional[str] = None
    project_type: Optional[str] = None
    scope_summary: Optional[str] = None
    key_deliverables: Optional[str] = None
    assumptions: Optional[str] = None
    constraints: Optional[str] = None
    stakeholders: Optional[str] = None
    owner_obligations: Optional[str] = None
    consultant_obligations: Optional[str] = None
    contractor_obligations: Optional[str] = None
    potential_risk_triggers: Optional[str] = None
    timeline_clues: Optional[str] = None
    cost_exposure_clues: Optional[str] = None
    extraction_confidence: Optional[float] = None
    user_reviewed: bool

    model_config = {"from_attributes": True}


class ExtractedContextUpdate(BaseModel):
    project_name: Optional[str] = None
    project_type: Optional[str] = None
    scope_summary: Optional[str] = None
    key_deliverables: Optional[str] = None
    assumptions: Optional[str] = None
    constraints: Optional[str] = None
    stakeholders: Optional[str] = None
    owner_obligations: Optional[str] = None
    consultant_obligations: Optional[str] = None
    contractor_obligations: Optional[str] = None
    potential_risk_triggers: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# RISK PLAN
# ─────────────────────────────────────────────────────────────

class RiskPlanCreate(BaseModel):
    project_id: int
    title: str
    version: str = "1.0"
    purpose: Optional[str] = None
    objectives: Optional[str] = None
    methodology: Optional[str] = None
    governance: Optional[str] = None
    roles_responsibilities: Optional[str] = None
    escalation_path: Optional[str] = None
    reporting_frequency: Optional[str] = None
    review_cycle: Optional[str] = None
    risk_categories: Optional[List[str]] = None
    risk_appetite: Optional[str] = None
    risk_thresholds: Optional[str] = None
    probability_scale: Optional[List[Dict[str, Any]]] = None
    impact_scale: Optional[List[Dict[str, Any]]] = None
    scoring_method: Optional[str] = None
    qualitative_method: Optional[str] = None
    quantitative_method: Optional[str] = None
    response_framework: Optional[str] = None
    monitoring_approach: Optional[str] = None
    contingency_reserve_pct: float = 10.0
    management_reserve_pct: float = 5.0


class RiskPlanUpdate(RiskPlanCreate):
    project_id: Optional[int] = None
    title: Optional[str] = None
    workflow_status: Optional[PlanWorkflowStatus] = None


class RiskPlanOut(BaseModel):
    id: int
    project_id: int
    title: str
    version: str
    workflow_status: PlanWorkflowStatus
    risk_appetite: Optional[str] = None
    contingency_reserve_pct: float
    management_reserve_pct: float
    consultant_approved_at: Optional[datetime] = None
    owner_approved_at: Optional[datetime] = None
    effective_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────
# RISK REGISTER
# ─────────────────────────────────────────────────────────────

class RiskRegisterCreate(BaseModel):
    project_id: int
    level: RiskLevel = RiskLevel.project
    risk_type: RiskType = RiskType.threat
    category: str
    subcategory: Optional[str] = None
    cause: Optional[str] = None
    event: Optional[str] = None
    impact_description: Optional[str] = None
    trigger: Optional[str] = None
    description: Optional[str] = None
    probability: int = 1
    cost_impact: int = 1
    time_impact: int = 1
    scope_impact: int = 1
    quality_impact: int = 1
    reputation_impact: int = 1
    stakeholder_impact: int = 1
    response_strategy: Optional[ResponseStrategy] = None
    risk_owner: Optional[str] = None
    action_owner: Optional[str] = None
    due_date: Optional[str] = None
    response_plan: Optional[str] = None
    contingency_plan: Optional[str] = None
    fallback_plan: Optional[str] = None
    residual_probability: Optional[int] = None
    residual_impact: Optional[int] = None
    secondary_risk_description: Optional[str] = None
    comments: Optional[str] = None

    @field_validator("probability", "cost_impact", "time_impact", "scope_impact",
                     "quality_impact", "reputation_impact", "stakeholder_impact")
    @classmethod
    def score_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("يجب أن تكون القيمة بين 1 و 5")
        return v


class RiskRegisterUpdate(RiskRegisterCreate):
    project_id: Optional[int] = None
    category: Optional[str] = None
    approval_status: Optional[ApprovalStatus] = None
    lifecycle_status: Optional[RiskLifecycle] = None


class RiskRegisterOut(BaseModel):
    id: int
    project_id: int
    risk_id: str
    level: RiskLevel
    risk_type: RiskType
    category: str
    subcategory: Optional[str] = None
    cause: Optional[str] = None
    event: Optional[str] = None
    impact_description: Optional[str] = None
    cei_statement: Optional[str] = None
    trigger: Optional[str] = None
    description: Optional[str] = None
    probability: int
    cost_impact: int
    time_impact: int
    scope_impact: int
    quality_impact: int
    reputation_impact: int
    stakeholder_impact: int
    composite_impact: float
    score: float
    priority: str
    response_strategy: Optional[ResponseStrategy] = None
    risk_owner: Optional[str] = None
    action_owner: Optional[str] = None
    due_date: Optional[str] = None
    response_plan: Optional[str] = None
    residual_score: Optional[float] = None
    approval_status: ApprovalStatus
    lifecycle_status: RiskLifecycle
    comments: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────
# RESPONSE TRACKING
# ─────────────────────────────────────────────────────────────

class ResponseTrackingCreate(BaseModel):
    project_id: int
    risk_id: int
    response_action: str
    action_owner: Optional[str] = None
    planned_start: Optional[str] = None
    planned_finish: Optional[str] = None
    actual_finish: Optional[str] = None
    progress_pct: int = 0
    current_status: TrackingStatus = TrackingStatus.not_started
    escalation_required: bool = False
    evidence_note: Optional[str] = None
    effectiveness_rating: EffectivenessRating = EffectivenessRating.not_assessed
    closure_recommendation: Optional[str] = None

    @field_validator("progress_pct")
    @classmethod
    def pct_range(cls, v: int) -> int:
        return max(0, min(100, v))


class ResponseTrackingUpdate(ResponseTrackingCreate):
    project_id: Optional[int] = None
    risk_id: Optional[int] = None
    response_action: Optional[str] = None


class ResponseTrackingOut(BaseModel):
    id: int
    project_id: int
    risk_id: int
    response_action: str
    action_owner: Optional[str] = None
    planned_start: Optional[str] = None
    planned_finish: Optional[str] = None
    actual_finish: Optional[str] = None
    progress_pct: int
    current_status: TrackingStatus
    escalation_required: bool
    evidence_note: Optional[str] = None
    effectiveness_rating: EffectivenessRating
    closure_recommendation: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────
# RACI
# ─────────────────────────────────────────────────────────────

class RACICreate(BaseModel):
    project_id: int
    activity: str
    activity_ar: Optional[str] = None
    project_manager: str = ""
    contractor_team: str = ""
    risk_manager: str = ""
    consultant: str = ""
    owner_rep: str = ""
    portfolio_mgmt: str = ""
    sort_order: int = 0


class RACIOut(BaseModel):
    id: int
    project_id: int
    activity: str
    activity_ar: Optional[str] = None
    project_manager: str
    contractor_team: str
    risk_manager: str
    consultant: str
    owner_rep: str
    portfolio_mgmt: str
    sort_order: int

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    total_risks: int
    high_risks: int
    medium_risks: int
    low_risks: int
    opportunities: int
    open_risks: int
    closed_risks: int
    avg_response_progress: float
    escalated_count: int
    by_category: Dict[str, int]
    by_status: Dict[str, int]
    top_critical: List[Dict[str, Any]]
    trend_monthly: List[Dict[str, Any]]


# ─────────────────────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────────────────────

class MonteCarloRequest(BaseModel):
    project_id: int
    base_cost: float
    iterations: int = 10000
    cost_uncertainty_pct: float = 20.0   # ± percentage
    schedule_uncertainty_pct: float = 15.0


class MonteCarloResult(BaseModel):
    p50_cost: float
    p80_cost: float
    p90_cost: float
    p50_schedule: float
    p80_schedule: float
    p90_schedule: float
    histogram_bins: List[float]
    histogram_counts: List[int]
    cumulative_x: List[float]
    cumulative_y: List[float]
    mean: float
    std_dev: float


class SensitivityRequest(BaseModel):
    project_id: int


class SensitivityResult(BaseModel):
    drivers: List[Dict[str, Any]]   # [{name, low_impact, high_impact, range}]


# ─────────────────────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────────────────────

class AdminUserUpdate(BaseModel):
    status: Optional[UserStatus] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    activation_expires_at: Optional[datetime] = None


class AdminStats(BaseModel):
    total_users: int
    activated_users: int
    pending_users: int
    suspended_users: int
    total_projects: int
    total_risks: int
    total_tracking_items: int
    pending_activation_requests: int


# ─────────────────────────────────────────────────────────────
# GENERIC
# ─────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
