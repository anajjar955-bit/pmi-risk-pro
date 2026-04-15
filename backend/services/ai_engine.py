"""
ai_engine.py — AI extraction from contract text, Monte Carlo simulation,
               Sensitivity (Tornado) analysis, and Trend analysis.

Uses:
  - OpenAI-compatible API (configured via env) OR falls back to
    rule-based heuristics when no key is present.
  - numpy / scipy for statistical calculations.
"""
from __future__ import annotations

import os
import re
import json
import math
import random
import statistics
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
AI_TIMEOUT: int = int(os.getenv("AI_TIMEOUT_SECONDS", "60"))

# Risk categories (authoritative list — users cannot create free-text cats)
RISK_CATEGORIES: List[str] = [
    "مخاطر تقنية",
    "مخاطر تجارية",
    "مخاطر تعاقدية",
    "مخاطر تشغيلية",
    "مخاطر بيئية",
    "مخاطر قانونية وتنظيمية",
    "مخاطر مالية",
    "مخاطر أصحاب المصلحة",
    "مخاطر جودة",
    "مخاطر الموارد البشرية",
    "مخاطر الإمداد والتوريد",
    "مخاطر الأمن والسلامة",
]

SUBCATEGORIES: Dict[str, List[str]] = {
    "مخاطر تقنية": ["تصميم", "أداء", "تكنولوجيا", "اختبار وتشغيل"],
    "مخاطر تجارية": ["سعر السوق", "تضخم", "عملة", "منافسة"],
    "مخاطر تعاقدية": ["تأخر الموافقات", "تغيير نطاق", "خلافات تعاقدية", "عقوبات"],
    "مخاطر تشغيلية": ["جدول زمني", "تنسيق", "واجهات بين الأطراف", "عمليات موقع"],
    "مخاطر بيئية": ["طقس", "بيئة طبيعية", "كوارث", "استدامة"],
    "مخاطر قانونية وتنظيمية": ["تراخيص", "لوائح", "ضرائب", "امتثال"],
    "مخاطر مالية": ["تمويل", "تدفق نقدي", "إفلاس مورد", "ضمان بنكي"],
    "مخاطر أصحاب المصلحة": ["معارضة", "توقعات", "اتصالات", "مجتمع"],
    "مخاطر جودة": ["مواصفات", "اختبار", "قبول", "معايير"],
    "مخاطر الموارد البشرية": ["نقص عمالة", "كفاءة", "دوران", "صحة وسلامة"],
    "مخاطر الإمداد والتوريد": ["توفر مواد", "أسعار مواد", "مورد وحيد", "توصيل"],
    "مخاطر الأمن والسلامة": ["حوادث", "سرقة", "إرهاب", "بيانات"],
}

RESPONSE_STRATEGIES_EN_AR: Dict[str, str] = {
    "avoid": "تجنب",
    "mitigate": "تخفيف",
    "transfer": "نقل",
    "accept_active": "قبول نشط",
    "accept_passive": "قبول سلبي",
    "exploit": "استغلال",
    "enhance": "تعزيز",
    "share": "مشاركة",
}


# ─────────────────────────────────────────────────────────────
# SCORING UTILS
# ─────────────────────────────────────────────────────────────

def compute_composite_impact(
    cost: int, time: int, scope: int, quality: int,
    reputation: int, stakeholder: int,
    weights: Optional[Dict[str, float]] = None
) -> float:
    """Weighted average of impact dimensions."""
    w = weights or {
        "cost": 0.30, "time": 0.25, "scope": 0.15,
        "quality": 0.15, "reputation": 0.08, "stakeholder": 0.07
    }
    total = (
        cost * w["cost"] +
        time * w["time"] +
        scope * w["scope"] +
        quality * w["quality"] +
        reputation * w["reputation"] +
        stakeholder * w["stakeholder"]
    )
    return round(total, 2)


def compute_score(probability: int, composite_impact: float) -> float:
    return round(probability * composite_impact, 2)


def compute_priority(score: float) -> str:
    if score >= 15:
        return "حرجة"
    elif score >= 9:
        return "عالية"
    elif score >= 4:
        return "متوسطة"
    return "منخفضة"


def build_cei_statement(cause: str, event: str, impact: str) -> str:
    """Build the Arabic Cause → Event → Impact composite statement."""
    parts = []
    if cause:
        parts.append(f"بسبب {cause}")
    if event:
        parts.append(f"قد يحدث {event}")
    if impact:
        parts.append(f"مما يؤدي إلى {impact}")
    return " → ".join(parts) if parts else ""


# ─────────────────────────────────────────────────────────────
# AI EXTRACTION
# ─────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """أنت خبير متخصص في تحليل وثائق العقود والمشاريع الهندسية باللغة العربية.
مهمتك استخراج المعلومات الأساسية من نص العقد أو نطاق العمل المقدم.
يجب أن تُعيد الإجابة بتنسيق JSON صحيح فقط دون أي نص إضافي.
"""

EXTRACTION_USER_TEMPLATE = """استخرج المعلومات التالية من النص المرفق وأعدها بصيغة JSON:

{{
  "project_name": "اسم المشروع",
  "project_type": "نوع المشروع (إنشاءات / بنية تحتية / تقنية / خدمات / غير ذلك)",
  "scope_summary": "ملخص نطاق العمل في 2-4 جمل",
  "key_deliverables": "قائمة بالمخرجات الرئيسية مفصولة بفاصلة منقوطة",
  "assumptions": "الافتراضات الأساسية",
  "constraints": "القيود والمحددات",
  "stakeholders": "أصحاب المصلحة الرئيسيين",
  "owner_obligations": "التزامات المالك",
  "consultant_obligations": "التزامات الاستشاري",
  "contractor_obligations": "التزامات المقاول",
  "potential_risk_triggers": "محفزات المخاطر المحتملة مفصولة بفاصلة منقوطة",
  "timeline_clues": "إشارات الجداول الزمنية",
  "cost_exposure_clues": "إشارات التعرض المالي",
  "extraction_confidence": 0.85
}}

النص:
{text}
"""


async def _call_openai(system_prompt: str, user_prompt: str) -> str:
    """Call OpenAI-compatible API asynchronously."""
    async with httpx.AsyncClient(timeout=AI_TIMEOUT) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "temperature": 0.1,
                "max_tokens": 2000,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _heuristic_extract(text: str) -> Dict[str, Any]:
    """
    Rule-based fallback extraction when no AI key is present.
    Applies Arabic/English regex patterns to extract common fields.
    """
    result: Dict[str, Any] = {
        "project_name": None,
        "project_type": None,
        "scope_summary": None,
        "key_deliverables": None,
        "assumptions": None,
        "constraints": None,
        "stakeholders": None,
        "owner_obligations": None,
        "consultant_obligations": None,
        "contractor_obligations": None,
        "potential_risk_triggers": None,
        "timeline_clues": None,
        "cost_exposure_clues": None,
        "extraction_confidence": 0.45,
    }

    # Project name — look for common Arabic patterns
    name_patterns = [
        r"(?:مشروع|Project)[:\s]+(.{5,80})",
        r"(?:عقد|Contract)[:\s]+(.{5,80})",
    ]
    for pat in name_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["project_name"] = m.group(1).strip()
            break

    # Timeline clues
    timeline_patterns = [
        r"\d+\s*(?:شهر|أشهر|month|months|week|أسبوع|year|سنة)",
        r"(?:مدة|duration|جدول|timeline)[^\n.،]{3,80}",
    ]
    timeline_hits = []
    for pat in timeline_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            timeline_hits.append(m.group(0).strip())
    if timeline_hits:
        result["timeline_clues"] = " | ".join(timeline_hits[:5])

    # Cost clues
    cost_patterns = [
        r"(?:قيمة|تكلفة|مبلغ|value|cost|budget)[^\n.،]{3,80}",
        r"[\d,]+\s*(?:ريال|دولار|درهم|SAR|USD|AED|مليون|billion|million)",
    ]
    cost_hits = []
    for pat in cost_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            cost_hits.append(m.group(0).strip())
    if cost_hits:
        result["cost_exposure_clues"] = " | ".join(cost_hits[:5])

    # Risk triggers
    risk_keywords = [
        "تأخير", "تجاوز", "نقص", "ارتفاع أسعار", "خلاف", "عدم توفر",
        "delay", "cost overrun", "shortage", "dispute", "risk", "خطر"
    ]
    triggers = [kw for kw in risk_keywords if kw.lower() in text.lower()]
    if triggers:
        result["potential_risk_triggers"] = "؛ ".join(triggers)

    # Scope summary — first meaningful paragraph
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if len(p.strip()) > 50]
    if paragraphs:
        result["scope_summary"] = paragraphs[0][:400]

    return result


async def extract_project_context(text: str) -> Dict[str, Any]:
    """
    Main extraction function. Uses AI if key available, else heuristic.
    """
    if OPENAI_API_KEY and len(OPENAI_API_KEY) > 10:
        try:
            prompt = EXTRACTION_USER_TEMPLATE.format(text=text[:8000])
            raw = await _call_openai(EXTRACTION_SYSTEM_PROMPT, prompt)
            # Strip markdown fences if present
            raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
            result = json.loads(raw)
            result["extraction_confidence"] = float(result.get("extraction_confidence", 0.85))
            return result
        except Exception as exc:
            # Graceful degradation to heuristic
            print(f"[AI] extraction failed: {exc}; falling back to heuristic")
    return _heuristic_extract(text)


async def generate_risk_suggestions(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generate a list of suggested risks from the extracted project context.
    Returns structured risk dicts ready for the Risk Register.
    """
    if not OPENAI_API_KEY:
        return _default_risk_suggestions(context)

    system = """أنت خبير إدارة مخاطر محترف معتمد من PMI.
بناءً على سياق المشروع المقدم، قدم قائمة من 8-12 مخاطرة محتملة بصيغة JSON.
أعد فقط مصفوفة JSON دون أي نص إضافي."""

    user = f"""من سياق المشروع التالي:
{json.dumps(context, ensure_ascii=False, indent=2)}

أنشئ قائمة مخاطر بالتنسيق:
[{{
  "category": "من القائمة المعتمدة",
  "risk_type": "threat أو opportunity",
  "cause": "السبب",
  "event": "الحدث المحتمل",
  "impact_description": "وصف التأثير",
  "trigger": "المحفز",
  "probability": 1-5,
  "cost_impact": 1-5,
  "time_impact": 1-5,
  "scope_impact": 1-5,
  "quality_impact": 1-5,
  "reputation_impact": 1-5,
  "stakeholder_impact": 1-5,
  "response_strategy": "avoid/mitigate/transfer/accept_active/exploit/enhance"
}}]"""

    try:
        raw = await _call_openai(system, user)
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
        return json.loads(raw)
    except Exception as exc:
        print(f"[AI] risk suggestion failed: {exc}")
        return _default_risk_suggestions(context)


def _default_risk_suggestions(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Baseline risk list for construction/infrastructure projects."""
    return [
        {
            "category": "مخاطر الإمداد والتوريد",
            "risk_type": "threat",
            "cause": "عدم استقرار أسعار المواد في الأسواق العالمية",
            "event": "ارتفاع تكلفة مواد البناء الأساسية بما يتجاوز الميزانية",
            "impact_description": "تجاوز قيمة العقد وتقليص هامش الربح",
            "trigger": "ارتفاع مؤشرات أسعار المواد أكثر من 10%",
            "probability": 3, "cost_impact": 5, "time_impact": 2,
            "scope_impact": 1, "quality_impact": 2, "reputation_impact": 1, "stakeholder_impact": 2,
            "response_strategy": "transfer",
        },
        {
            "category": "مخاطر تعاقدية",
            "risk_type": "threat",
            "cause": "بطء الإجراءات لدى الجهات الحكومية",
            "event": "تأخر إصدار التصاريح والموافقات اللازمة",
            "impact_description": "تأخر الجدول الزمني وتراكم التكاليف الثابتة",
            "trigger": "عدم استلام الموافقة خلال 30 يوماً من تاريخ التقديم",
            "probability": 4, "cost_impact": 3, "time_impact": 5,
            "scope_impact": 1, "quality_impact": 1, "reputation_impact": 2, "stakeholder_impact": 3,
            "response_strategy": "avoid",
        },
        {
            "category": "مخاطر الموارد البشرية",
            "risk_type": "threat",
            "cause": "نقص الكوادر المتخصصة في سوق العمل",
            "event": "عدم القدرة على تعيين الكفاءات التقنية المطلوبة",
            "impact_description": "تأثير سلبي على جودة التنفيذ وسرعة الإنجاز",
            "trigger": "عدم ملء 30% من الوظائف الهندسية خلال أول 3 أشهر",
            "probability": 3, "cost_impact": 2, "time_impact": 4,
            "scope_impact": 2, "quality_impact": 4, "reputation_impact": 3, "stakeholder_impact": 2,
            "response_strategy": "mitigate",
        },
        {
            "category": "مخاطر بيئية",
            "risk_type": "threat",
            "cause": "الظروف المناخية الشديدة في المنطقة",
            "event": "توقف أعمال البناء بسبب العواصف الرملية أو الأمطار",
            "impact_description": "تأخير الجدول الزمني وزيادة التكاليف التشغيلية",
            "trigger": "تحذيرات الطقس من الجهات المختصة",
            "probability": 2, "cost_impact": 2, "time_impact": 3,
            "scope_impact": 1, "quality_impact": 1, "reputation_impact": 1, "stakeholder_impact": 1,
            "response_strategy": "accept_active",
        },
        {
            "category": "مخاطر تجارية",
            "risk_type": "opportunity",
            "cause": "تحسن ظروف الاقتصاد الكلي وانخفاض الفائدة",
            "event": "توفر فرص تمويل أفضل وأسعار مواد أقل",
            "impact_description": "تحقيق وفورات تؤدي إلى ربحية أعلى من المتوقع",
            "trigger": "انخفاض مؤشرات أسعار مواد البناء بأكثر من 8%",
            "probability": 2, "cost_impact": 4, "time_impact": 1,
            "scope_impact": 1, "quality_impact": 1, "reputation_impact": 1, "stakeholder_impact": 1,
            "response_strategy": "exploit",
        },
    ]


# ─────────────────────────────────────────────────────────────
# MONTE CARLO SIMULATION
# ─────────────────────────────────────────────────────────────

def run_monte_carlo(
    base_cost: float,
    cost_uncertainty_pct: float = 20.0,
    schedule_uncertainty_days: float = 60.0,
    iterations: int = 10_000,
    seed: Optional[int] = 42,
) -> Dict[str, Any]:
    """
    Triangular-distribution Monte Carlo for cost and schedule.
    Returns histogram, cumulative, and percentile results.
    """
    rng = random.Random(seed)
    cost_min = base_cost * (1 - cost_uncertainty_pct / 100)
    cost_max = base_cost * (1 + cost_uncertainty_pct / 100)
    cost_mode = base_cost  # most likely = base

    sched_base = schedule_uncertainty_days
    sched_min = sched_base * 0.8
    sched_max = sched_base * 2.5
    sched_mode = sched_base * 1.2

    def triangular(lo: float, hi: float, mode: float) -> float:
        u = rng.random()
        fc = (mode - lo) / (hi - lo)
        if u < fc:
            return lo + math.sqrt(u * (hi - lo) * (mode - lo))
        return hi - math.sqrt((1 - u) * (hi - lo) * (hi - mode))

    cost_samples = [triangular(cost_min, cost_max, cost_mode) for _ in range(iterations)]
    sched_samples = [triangular(sched_min, sched_max, sched_mode) for _ in range(iterations)]

    cost_samples.sort()
    sched_samples.sort()

    def percentile(data: List[float], pct: float) -> float:
        idx = int(math.ceil(pct / 100 * len(data))) - 1
        return round(data[max(0, idx)], 2)

    # Histogram (20 bins)
    n_bins = 20
    cost_min_val = cost_samples[0]
    cost_max_val = cost_samples[-1]
    bin_width = (cost_max_val - cost_min_val) / n_bins
    bins = [cost_min_val + i * bin_width for i in range(n_bins + 1)]
    counts = [0] * n_bins
    for val in cost_samples:
        idx = int((val - cost_min_val) / bin_width)
        if idx >= n_bins:
            idx = n_bins - 1
        counts[idx] += 1

    # Cumulative (50 points)
    step = iterations // 50
    cum_x = [round(cost_samples[i * step], 2) for i in range(50)]
    cum_y = [round((i * step + 1) / iterations * 100, 2) for i in range(50)]

    return {
        "p50_cost": percentile(cost_samples, 50),
        "p80_cost": percentile(cost_samples, 80),
        "p90_cost": percentile(cost_samples, 90),
        "p50_schedule": percentile(sched_samples, 50),
        "p80_schedule": percentile(sched_samples, 80),
        "p90_schedule": percentile(sched_samples, 90),
        "histogram_bins": [round(b, 2) for b in bins[:-1]],
        "histogram_counts": counts,
        "cumulative_x": cum_x,
        "cumulative_y": cum_y,
        "mean": round(statistics.mean(cost_samples), 2),
        "std_dev": round(statistics.stdev(cost_samples), 2),
        "iterations": iterations,
    }


# ─────────────────────────────────────────────────────────────
# SENSITIVITY (TORNADO) ANALYSIS
# ─────────────────────────────────────────────────────────────

def run_sensitivity(risks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Tornado chart: for each risk, compute contribution range to total cost exposure.
    Risks must have: score, cost_impact, probability, category, cause/event.
    """
    if not risks:
        return []

    base_total = sum(r.get("score", 0) for r in risks)
    if base_total == 0:
        return []

    drivers = []
    for risk in risks:
        score = risk.get("score", 0)
        if score == 0:
            continue

        # Low scenario: probability -1 step (min 1)
        low_prob = max(1, risk.get("probability", 1) - 1)
        low_score = low_prob * risk.get("composite_impact", risk.get("cost_impact", 1))
        low_total = base_total - score + low_score
        low_impact = round((low_total - base_total) / max(base_total, 1) * 100, 2)

        # High scenario: probability +1 step (max 5)
        high_prob = min(5, risk.get("probability", 1) + 1)
        high_score = high_prob * risk.get("composite_impact", risk.get("cost_impact", 1))
        high_total = base_total - score + high_score
        high_impact = round((high_total - base_total) / max(base_total, 1) * 100, 2)

        name = (risk.get("cause") or risk.get("category") or "مخاطرة")[:50]
        drivers.append({
            "name": name,
            "category": risk.get("category", ""),
            "low_impact": low_impact,
            "high_impact": high_impact,
            "range": round(abs(high_impact - low_impact), 2),
            "base_score": round(score, 2),
        })

    # Sort by range (widest = most influential)
    drivers.sort(key=lambda d: d["range"], reverse=True)
    return drivers[:10]


# ─────────────────────────────────────────────────────────────
# DOCUMENT EXTRACTION (PDF / DOCX)
# ─────────────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    try:
        import io
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        return "\n\n".join(text_parts)
    except ImportError:
        return "[pdfplumber not installed — install with: pip install pdfplumber]"
    except Exception as exc:
        return f"[PDF extraction error: {exc}]"


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes using python-docx."""
    try:
        import io
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        return "\n\n".join(paragraphs)
    except ImportError:
        return "[python-docx not installed — install with: pip install python-docx]"
    except Exception as exc:
        return f"[DOCX extraction error: {exc}]"
