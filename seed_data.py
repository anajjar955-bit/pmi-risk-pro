"""
seed_data.py — Populate the database with test admin, sample users,
               sample project, risk register items, and tracking log.

Run: python seed_data.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("DATABASE_URL", "sqlite:///./risk_platform.db")
os.environ.setdefault("JWT_SECRET_KEY", "seed-dev-secret-key-change-in-production")
os.environ.setdefault("ADMIN_EMAIL", "anajjar@pmhouse.org")
os.environ.setdefault("ADMIN_PASSWORD", "Admin@123456")

from datetime import datetime, timedelta
from backend.database import SessionLocal, init_db
from backend.models import (
    User, Project, RiskPlan, RiskRegisterItem, ResponseTrackingItem,
    RACIMatrix, ExtractedProjectContext, ActivationCode,
    UserRole, UserStatus, RiskType, RiskLevel, RiskLifecycle,
    ApprovalStatus, ResponseStrategy, PlanWorkflowStatus,
    TrackingStatus, EffectivenessRating, ActivationCodeStatus,
)
from backend.auth import hash_password
from backend.services.ai_engine import (
    compute_composite_impact, compute_score, compute_priority, build_cei_statement
)

init_db()
db = SessionLocal()

print("🌱 بدء تهيئة البيانات الاختبارية...")

# ── 1. Admin user ──────────────────────────────────────────────
admin_email = os.environ["ADMIN_EMAIL"]
admin = db.query(User).filter(User.email == admin_email).first()
if not admin:
    admin = User(
        full_name="أحمد النجار — مدير النظام",
        email=admin_email,
        mobile="+201005394312",
        company="PMHouse",
        country="مصر",
        hashed_password=hash_password(os.environ["ADMIN_PASSWORD"]),
        role=UserRole.admin,
        status=UserStatus.activated,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"  ✅ مدير النظام: {admin_email} / Admin@123456")
else:
    print(f"  ℹ️  مدير النظام موجود مسبقاً: {admin_email}")

# ── 2. Test regular user ───────────────────────────────────────
test_email = "testuser@pmhouse.org"
test_user = db.query(User).filter(User.email == test_email).first()
if not test_user:
    test_user = User(
        full_name="محمد علي الشمري",
        email=test_email,
        mobile="+966501234567",
        company="شركة البناء المتحد",
        country="المملكة العربية السعودية",
        hashed_password=hash_password("Test@123456"),
        role=UserRole.user,
        status=UserStatus.activated,
        is_active=True,
        activation_expires_at=datetime.utcnow() + timedelta(days=365),
    )
    db.add(test_user)
    db.commit()
    db.refresh(test_user)

    # Give test user an activation code (already used)
    code = ActivationCode(
        user_id=test_user.id,
        code="TEST-SEED-1234-5678",
        status=ActivationCodeStatus.used,
        issued_by_admin_id=admin.id,
        expires_at=datetime.utcnow() + timedelta(days=365),
        used_at=datetime.utcnow(),
        duration_days=365,
    )
    db.add(code)
    db.commit()
    print(f"  ✅ مستخدم اختباري: {test_email} / Test@123456")
else:
    print(f"  ℹ️  المستخدم الاختباري موجود مسبقاً")

# ── 3. Sample Project ──────────────────────────────────────────
project = db.query(Project).filter(Project.owner_id == test_user.id).first()
if not project:
    project = Project(
        owner_id=test_user.id,
        name="مشروع إنشاء مجمع سكاني — الرياض، المرحلة الثانية",
        project_type="إنشاءات وبنية تحتية",
        scope_summary=(
            "تصميم وتنفيذ 450 وحدة سكنية مع الخدمات والمرافق المصاحبة "
            "في حي النرجس بالرياض. يشمل المشروع شبكات المياه والصرف الصحي "
            "والكهرباء والطرق الداخلية."
        ),
        key_deliverables="450 وحدة سكنية؛ شبكة طرق داخلية؛ شبكة مياه وصرف صحي؛ حدائق ومرافق مجتمعية",
        assumptions="توفر الأرض خالية من المنازعات؛ اعتماد التصاميم في شهر أبريل 2025",
        constraints="الميزانية ثابتة عند 120 مليون ريال؛ التسليم لا يتجاوز ديسمبر 2027",
        stakeholders="شركة الرياض للتطوير (المالك)؛ شركة البناء المتحد (المقاول)؛ مكتب الهندسة المتقدمة (الاستشاري)",
        contract_value=120_000_000.0,
        currency="SAR",
        duration_months=36,
        start_date="2025-01-01",
        end_date="2027-12-31",
        contingency_pct=10.0,
        management_reserve_pct=5.0,
        risk_appetite="moderate",
        escalation_threshold_score=15,
        is_active=True,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    print(f"  ✅ مشروع اختباري: {project.name} (ID={project.id})")

    # Extracted context
    ctx = ExtractedProjectContext(
        project_id=project.id,
        project_name=project.name,
        project_type=project.project_type,
        scope_summary=project.scope_summary,
        key_deliverables=project.key_deliverables,
        assumptions=project.assumptions,
        constraints=project.constraints,
        stakeholders=project.stakeholders,
        owner_obligations="توفير الأرض؛ إصدار التصاريح؛ دفع المستخلصات في الموعد",
        consultant_obligations="الإشراف على التنفيذ؛ مراجعة المخططات؛ رفع التقارير",
        contractor_obligations="التنفيذ وفق المواصفات؛ الالتزام بالجدول؛ الجودة والسلامة",
        potential_risk_triggers="تأخر الموافقات؛ ارتفاع أسعار الحديد والأسمنت؛ نقص العمالة الماهرة؛ الظروف الجوية",
        timeline_clues="مدة 36 شهراً من يناير 2025 إلى ديسمبر 2027",
        cost_exposure_clues="قيمة العقد 120 مليون ريال؛ احتياطي طارئ 12 مليون",
        extraction_confidence=0.92,
        user_reviewed=True,
    )
    db.add(ctx)
    db.commit()
else:
    print(f"  ℹ️  المشروع الاختباري موجود (ID={project.id})")

# ── 4. Risk Management Plan ────────────────────────────────────
plan = db.query(RiskPlan).filter(RiskPlan.project_id == project.id).first()
if not plan:
    plan = RiskPlan(
        project_id=project.id,
        title=f"خطة إدارة المخاطر — {project.name}",
        version="1.0",
        purpose="تحديد الإطار المنهجي لإدارة مخاطر المشروع وفق معايير PMI وPMBOK الإصدار الثامن",
        objectives="تحديد وتحليل والاستجابة لمخاطر المشروع بصورة منهجية طوال دورة حياة المشروع",
        risk_categories=[
            "مخاطر تقنية", "مخاطر تجارية", "مخاطر تعاقدية",
            "مخاطر تشغيلية", "مخاطر بيئية", "مخاطر قانونية وتنظيمية",
        ],
        risk_appetite="معتدلة — الشركة مستعدة لقبول مخاطر يصل تأثيرها إلى 5% من قيمة العقد",
        risk_thresholds="تصعيد فوري للمخاطر ذات الدرجة ≥ 15 أو التأثير المالي > 6 مليون ريال",
        reporting_frequency="أسبوعي للمخاطر العالية؛ شهري للمخاطر المتوسطة؛ ربع سنوي لجميع المخاطر",
        review_cycle="مراجعة شاملة ربع سنوية + مراجعة طارئة عند حدوث أحداث جوهرية",
        contingency_reserve_pct=10.0,
        management_reserve_pct=5.0,
        workflow_status=PlanWorkflowStatus.under_owner_review,
        drafted_by_id=test_user.id,
        consultant_approved_at=datetime.utcnow() - timedelta(days=5),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    print(f"  ✅ خطة إدارة المخاطر: {plan.title}")

# ── 5. Risk Register Items ─────────────────────────────────────
def add_risk(project_id, risk_id, category, subcategory, risk_type,
             cause, event, impact_desc, trigger,
             prob, cost_i, time_i, scope_i, quality_i, rep_i, stake_i,
             strategy, owner, action_owner, due_date, response_plan,
             res_prob=None, res_impact=None, approval=ApprovalStatus.owner_approved,
             lifecycle=RiskLifecycle.open, description=""):
    existing = db.query(RiskRegisterItem).filter(
        RiskRegisterItem.project_id == project_id,
        RiskRegisterItem.risk_id == risk_id,
    ).first()
    if existing:
        return existing
    composite = compute_composite_impact(cost_i, time_i, scope_i, quality_i, rep_i, stake_i)
    score = compute_score(prob, composite)
    priority = compute_priority(score)
    cei = build_cei_statement(cause, event, impact_desc)
    residual_score = round(res_prob * res_impact, 2) if res_prob and res_impact else None
    risk = RiskRegisterItem(
        project_id=project_id, risk_id=risk_id,
        level=RiskLevel.project, risk_type=risk_type,
        category=category, subcategory=subcategory,
        cause=cause, event=event, impact_description=impact_desc,
        trigger=trigger, description=description,
        probability=prob, cost_impact=cost_i, time_impact=time_i,
        scope_impact=scope_i, quality_impact=quality_i,
        reputation_impact=rep_i, stakeholder_impact=stake_i,
        composite_impact=composite, score=score, priority=priority,
        cei_statement=cei, response_strategy=strategy,
        risk_owner=owner, action_owner=action_owner, due_date=due_date,
        response_plan=response_plan,
        residual_probability=res_prob, residual_impact=res_impact, residual_score=residual_score,
        approval_status=approval, lifecycle_status=lifecycle,
        created_by_id=test_user.id, last_updated_by_id=test_user.id,
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return risk

existing_risks = db.query(RiskRegisterItem).filter(RiskRegisterItem.project_id == project.id).count()
if existing_risks == 0:
    r1 = add_risk(
        project.id, "R-001", "مخاطر تعاقدية", "تأخر الموافقات",
        RiskType.threat,
        "بطء الإجراءات الحكومية وتعقيدها",
        "تأخر إصدار رخصة البناء والتصاريح اللازمة للبدء",
        "تأخر الجدول الزمني وتراكم التكاليف الثابتة بمعدل 500,000 ريال شهرياً",
        "عدم استلام الترخيص خلال 30 يوماً من تاريخ التقديم",
        4, 3, 5, 1, 1, 2, 3,
        ResponseStrategy.avoid, "أحمد النجار", "محمد العمري",
        "2025-04-30",
        "تعيين مستشار حكومي لمتابعة الطلبات؛ تقديم المستندات قبل 60 يوماً من الجدول",
        res_prob=2, res_impact=3,
    )
    r2 = add_risk(
        project.id, "R-002", "مخاطر الإمداد والتوريد", "أسعار مواد",
        RiskType.threat,
        "عدم استقرار أسعار مواد البناء في الأسواق العالمية",
        "ارتفاع تكلفة الحديد والأسمنت بنسبة تتجاوز 15%",
        "تجاوز الميزانية التعاقدية وتقليص هامش الربح للمقاول",
        "ارتفاع مؤشر أسعار مواد البناء بأكثر من 10% لثلاثة أشهر متتالية",
        3, 5, 2, 1, 2, 1, 2,
        ResponseStrategy.transfer, "محمد العمري", "سارة الخالدي",
        "2025-05-31",
        "إبرام عقود توريد بأسعار ثابتة لمدة 12 شهراً؛ شراء مسبق للكميات الأساسية",
        res_prob=2, res_impact=3, approval=ApprovalStatus.owner_approved,
    )
    r3 = add_risk(
        project.id, "R-003", "مخاطر الموارد البشرية", "نقص عمالة",
        RiskType.threat,
        "نقص الكوادر المتخصصة في مجال البناء بسبب المنافسة في السوق",
        "عدم القدرة على تعيين المهندسين والمشرفين المطلوبين في الوقت المحدد",
        "تأثير سلبي على جودة التنفيذ وسرعة الإنجاز والأمان في الموقع",
        "عدم ملء 30% من الوظائف الهندسية الحرجة خلال أول 3 أشهر",
        3, 2, 4, 2, 4, 3, 2,
        ResponseStrategy.mitigate, "سارة الخالدي", "سارة الخالدي",
        "2025-06-30",
        "شراكة مع شركات التوظيف المتخصصة؛ برنامج حوافز للاستقطاب؛ التعاقد مع شركات مقاولات باطنية",
        res_prob=2, res_impact=2,
    )
    r4 = add_risk(
        project.id, "R-004", "مخاطر بيئية", "طقس",
        RiskType.threat,
        "الظروف المناخية الشديدة (عواصف رملية وحرارة مرتفعة) في المنطقة",
        "توقف أعمال البناء الخارجية بسبب الطقس القاسي لفترات ممتدة",
        "تأخير الجدول الزمني بما يصل إلى 45 يوماً وزيادة التكاليف التشغيلية",
        "تحذيرات الطقس الحمراء من الجهات المختصة لأكثر من 5 أيام متتالية",
        2, 2, 3, 1, 1, 1, 1,
        ResponseStrategy.accept_active, "أحمد النجار", "فريق الموقع",
        "2025-12-31",
        "جدولة الأعمال الخارجية في ساعات الصباح الباكر؛ الاحتفاظ بيوم احتياطي أسبوعياً",
        res_prob=2, res_impact=2,
    )
    r5 = add_risk(
        project.id, "R-005", "مخاطر تجارية", "سعر السوق",
        RiskType.opportunity,
        "تحسن ظروف الاقتصاد الكلي وانخفاض أسعار الفائدة",
        "توفر مواد بناء بأسعار أقل من المتوقع نتيجة انخفاض الطلب العالمي",
        "تحقيق وفورات تؤدي إلى ربحية أعلى من المتوقع أو تحسين المواصفات",
        "انخفاض مؤشرات أسعار مواد البناء بأكثر من 8% لربع كامل",
        2, 4, 1, 1, 1, 1, 1,
        ResponseStrategy.exploit, "محمد العمري", "محمد العمري",
        "2025-09-30",
        "مراقبة الأسواق يومياً؛ تخصيص ميزانية لشراء كميات إضافية عند انخفاض الأسعار",
    )
    r6 = add_risk(
        project.id, "R-006", "مخاطر تقنية", "تصميم",
        RiskType.threat,
        "اكتشاف تعارضات بين مخططات التخصصات المختلفة",
        "الحاجة لإعادة تصميم أجزاء هامة من المشروع بعد بدء التنفيذ",
        "تكاليف إضافية غير مخططة وتأخير في الجدول الزمني",
        "اكتشاف تعارض لا يمكن حله بسهولة في مرحلة التنفيذ",
        2, 3, 4, 3, 4, 2, 2,
        ResponseStrategy.mitigate, "سارة الخالدي", "فريق التصميم",
        "2025-03-31",
        "اعتماد نظام BIM للتنسيق ثلاثي الأبعاد؛ اجتماعات تنسيق أسبوعية بين التخصصات",
        res_prob=1, res_impact=2,
    )
    r7 = add_risk(
        project.id, "R-007", "مخاطر قانونية وتنظيمية", "لوائح",
        RiskType.threat,
        "صدور لوائح بناء جديدة أو تعديل الاشتراطات الفنية أثناء التنفيذ",
        "الحاجة لتعديل التصاميم والمواصفات لتلبية الاشتراطات الجديدة",
        "تكاليف إضافية وتأخير في الحصول على شهادات الإتمام",
        "إعلان رسمي عن تعديل الاشتراطات من الجهات التنظيمية",
        2, 3, 3, 2, 2, 1, 2,
        ResponseStrategy.accept_active, "أحمد النجار", "المستشار القانوني",
        "2025-12-31",
        "متابعة مستمرة للتحديثات التنظيمية؛ التواصل المبكر مع الجهات المختصة",
        lifecycle=RiskLifecycle.ongoing,
    )
    r8 = add_risk(
        project.id, "R-008", "مخاطر مالية", "تدفق نقدي",
        RiskType.threat,
        "تأخر دفع المستخلصات من المالك بسبب مشاكل إدارية أو مالية",
        "ضغط على التدفق النقدي للمقاول وصعوبة دفع رواتب ومستحقات الموردين",
        "توقف أعمال البناء جزئياً وتراكم الديون لدى الموردين",
        "تأخر المستخلص الشهري أكثر من 30 يوماً عن الموعد التعاقدي",
        3, 4, 4, 2, 2, 3, 3,
        ResponseStrategy.mitigate, "محمد العمري", "المدير المالي",
        "2025-04-30",
        "الاحتفاظ بسيولة احتياطية تعادل 3 أشهر من التشغيل؛ تفعيل خط ائتمان بنكي",
        res_prob=2, res_impact=3,
        approval=ApprovalStatus.consultant_approved,
    )
    r9 = add_risk(
        project.id, "R-009", "مخاطر أصحاب المصلحة", "مجتمع",
        RiskType.threat,
        "اعتراض سكان المنطقة المجاورة على الأعمال الإنشائية",
        "شكاوى رسمية تؤدي إلى إيقاف مؤقت للعمل بأمر الجهات المختصة",
        "تأخير الجدول وتكاليف إضافية للعلاقات العامة والمعالجة",
        "تقديم أكثر من 5 شكاوى رسمية لمحلية المنطقة",
        2, 2, 3, 1, 2, 4, 3,
        ResponseStrategy.mitigate, "أحمد النجار", "مسؤول العلاقات العامة",
        "2025-04-15",
        "اجتماع مجتمعي تمهيدي قبل بدء الأعمال؛ تحديد ساعات العمل المسموحة",
        lifecycle=RiskLifecycle.closed,
        approval=ApprovalStatus.closed,
    )
    r10 = add_risk(
        project.id, "R-010", "مخاطر الأمن والسلامة", "حوادث",
        RiskType.threat,
        "بيئة العمل المكثفة وتزامن أعمال متعددة في موقع واحد",
        "وقوع حادث سلامة خطير يؤثر على العمالة أو المعدات",
        "خسائر بشرية أو مادية وإيقاف العمل للتحقيق وإعادة التقييم",
        "وقوع أي إصابة تستوجب التوقف عن العمل (LTI)",
        3, 3, 4, 2, 5, 5, 4,
        ResponseStrategy.avoid, "مسؤول السلامة", "مسؤول السلامة",
        "2025-12-31",
        "تطبيق خطة سلامة شاملة ISO 45001؛ تدريب يومي؛ فحص المعدات أسبوعياً؛ صلاحية إيقاف العمل",
        res_prob=1, res_impact=3,
    )
    print(f"  ✅ تم إنشاء 10 مخاطر في سجل المخاطر")

    # ── 6. Response Tracking ───────────────────────────────────
    risks_in_db = db.query(RiskRegisterItem).filter(RiskRegisterItem.project_id == project.id).all()
    tracking_data = [
        (risks_in_db[0], "متابعة أسبوعية مع إدارة التصاريح ورفع تقرير للاستشاري", "أحمد النجار", "2025-01-15", "2025-04-30", None, 65, TrackingStatus.in_progress, False, EffectivenessRating.medium),
        (risks_in_db[1], "إبرام عقود توريد طويلة الأمد بأسعار ثابتة مع موردين معتمدين", "محمد العمري", "2025-02-01", "2025-03-31", "2025-03-28", 100, TrackingStatus.completed, False, EffectivenessRating.high),
        (risks_in_db[2], "فتح مناقصة توظيف دولية واستقطاب خبرات من السوق المصري", "سارة الخالدي", "2025-01-20", "2025-05-15", None, 30, TrackingStatus.delayed, True, EffectivenessRating.low),
        (risks_in_db[3], "جدولة الأعمال الإنشائية في ساعات الصباح مع احتياطي أسبوعي", "فريق الموقع", "2025-01-01", "2025-12-31", None, 50, TrackingStatus.in_progress, False, EffectivenessRating.medium),
        (risks_in_db[5], "تطبيق نظام BIM واجتماعات التنسيق الأسبوعية بين التخصصات", "فريق التصميم", "2025-01-10", "2025-03-31", "2025-03-25", 100, TrackingStatus.completed, False, EffectivenessRating.high),
        (risks_in_db[7], "الاحتفاظ بخط ائتمان بنكي وسيولة احتياطية 3 أشهر", "المدير المالي", "2025-02-01", "2025-04-30", None, 80, TrackingStatus.in_progress, False, EffectivenessRating.high),
    ]
    for risk, action, owner, ps, pf, af, prog, status, escalate, eff in tracking_data:
        item = ResponseTrackingItem(
            project_id=project.id, risk_id=risk.id,
            response_action=action, action_owner=owner,
            planned_start=ps, planned_finish=pf, actual_finish=af,
            progress_pct=prog, current_status=status,
            escalation_required=escalate, effectiveness_rating=eff,
            last_updated_by_id=test_user.id,
        )
        db.add(item)
    db.commit()
    print(f"  ✅ تم إنشاء 6 سجلات متابعة استجابة")

else:
    print(f"  ℹ️  البيانات الاختبارية موجودة مسبقاً ({existing_risks} مخاطر)")

# ── 7. RACI Matrix ─────────────────────────────────────────────
if not db.query(RACIMatrix).filter(RACIMatrix.project_id == project.id).first():
    raci_data = [
        ("تحديد المخاطر", "risk_identification", "A", "R", "R", "C", "I", "I"),
        ("التحليل النوعي", "qualitative_analysis", "C", "R", "A", "C", "I", "I"),
        ("التحليل الكمي", "quantitative_analysis", "C", "C", "R", "A", "I", "I"),
        ("خطط الاستجابة", "response_planning", "A", "R", "R", "C", "I", "I"),
        ("تنفيذ الاستجابات", "response_implementation", "A", "R", "C", "C", "I", "I"),
        ("المراقبة والسيطرة", "monitoring_control", "I", "R", "A", "R", "C", "C"),
        ("التصعيد للإدارة", "escalation", "C", "I", "R", "A", "R", "I"),
        ("تقارير الحوكمة", "governance_reporting", "I", "I", "C", "A", "R", "R"),
        ("اعتماد الخطة", "plan_approval", "C", "I", "C", "C", "A", "R"),
        ("إغلاق المخاطر", "risk_closure", "C", "R", "A", "C", "A", "I"),
    ]
    for i, (ar, en, pm, ct, rm, co, or_, pg) in enumerate(raci_data):
        db.add(RACIMatrix(
            project_id=project.id, activity=en, activity_ar=ar,
            project_manager=pm, contractor_team=ct, risk_manager=rm,
            consultant=co, owner_rep=or_, portfolio_mgmt=pg, sort_order=i,
        ))
    db.commit()
    print("  ✅ مصفوفة RACI تم إنشاؤها")

print("\n✨ تم إعداد البيانات الاختبارية بنجاح!\n")
print("═" * 55)
print("  بيانات تسجيل الدخول:")
print(f"  🔑 المشرف:  {admin_email}  /  Admin@123456")
print(f"  👤 المستخدم: testuser@pmhouse.org  /  Test@123456")
print(f"  📁 معرّف المشروع الاختباري: {project.id}")
print("═" * 55)
print("  لتشغيل الخادم:")
print("  uvicorn backend.main:app --reload --port 8000")
print("  توثيق API: http://localhost:8000/api/docs")
print("═" * 55)

db.close()
