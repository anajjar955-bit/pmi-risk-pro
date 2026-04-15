# 🏗 PMI Risk Pro — تعليمات التشغيل الكاملة

## المتطلبات الأساسية
- Python 3.11 أو أحدث
- pip (مدير حزم Python)

---

## 1. التثبيت المحلي (Local / Replit)

### 1.1 نسخ مجلد المشروع
```bash
# إذا كنت تنسخ من مستودع
cd risk_platform
```

### 1.2 إنشاء البيئة الافتراضية وتثبيت المتطلبات
```bash
python -m venv .venv
source .venv/bin/activate       # Linux / macOS
# أو على Windows:
.venv\Scripts\activate

pip install -r requirements.txt
```

### 1.3 إعداد المتغيرات البيئية
```bash
cp .env.example .env
```
ثم افتح `.env` وعدّل على الأقل:
```
JWT_SECRET_KEY=أدخل_مفتاح_عشوائي_قوي_هنا_64_حرف
ADMIN_PASSWORD=Admin@123456
```
لتوليد مفتاح آمن:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 1.4 تهيئة قاعدة البيانات وإدخال البيانات الاختبارية
```bash
python seed_data.py
```
المخرجات المتوقعة:
```
🌱 بدء تهيئة البيانات الاختبارية...
  ✅ مدير النظام: anajjar@pmhouse.org / Admin@123456
  ✅ مستخدم اختباري: testuser@pmhouse.org / Test@123456
  ✅ مشروع اختباري: مشروع إنشاء مجمع سكاني — الرياض (ID=1)
  ✅ تم إنشاء 10 مخاطر في سجل المخاطر
  ✅ تم إنشاء 6 سجلات متابعة استجابة
  ✅ مصفوفة RACI تم إنشاؤها
```

### 1.5 تشغيل الخادم
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```
أو:
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

### 1.6 فتح الواجهة الأمامية
افتح `frontend/index.html` في المتصفح مباشرة (file://), أو شغّل خادم HTTP بسيط:
```bash
cd frontend
python -m http.server 3000
# ثم افتح: http://localhost:3000
```

---

## 2. التشغيل على Replit

### 2.1 إنشاء Replit جديد من نوع Python
1. ارفع جميع ملفات المشروع
2. في ملف `.replit`:
```toml
run = "uvicorn backend.main:app --host 0.0.0.0 --port 8000"
```
3. في `pyproject.toml`:
```toml
[tool.poetry.dependencies]
python = "^3.11"
```
4. أضف المتغيرات البيئية في قسم Secrets في Replit

### 2.2 عنوان الـ API على Replit
```
https://YOUR-REPLIT-USERNAME.YOUR-REPLIT-SLUG.repl.co
```
عدّل السطر في `frontend/index.html`:
```js
const API_BASE = "https://your-repl-url.repl.co";
```

---

## 3. النشر على Render.com (مجاني)

### 3.1 إعداد render.yaml
```yaml
services:
  - type: web
    name: pmi-risk-pro
    env: python
    buildCommand: pip install -r requirements.txt && python seed_data.py
    startCommand: gunicorn backend.main:app -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
    envVars:
      - key: DATABASE_URL
        value: sqlite:///./risk_platform.db
      - key: JWT_SECRET_KEY
        generateValue: true
      - key: ADMIN_EMAIL
        value: anajjar@pmhouse.org
      - key: ADMIN_PASSWORD
        sync: false
      - key: ALLOWED_ORIGINS
        value: https://your-frontend-url.com
```

---

## 4. بيانات تسجيل الدخول الاختبارية

| الدور | البريد الإلكتروني | كلمة المرور |
|-------|-------------------|-------------|
| مشرف النظام | anajjar@pmhouse.org | Admin@123456 |
| مستخدم عادي (مفعّل) | testuser@pmhouse.org | Test@123456 |

---

## 5. قائمة مسارات API الكاملة

### Health
| الطريقة | المسار | الوصف |
|---------|--------|-------|
| GET | `/` | التحقق من حالة الخادم |
| GET | `/api/health` | فحص الصحة مع الطابع الزمني |

### Auth — المصادقة
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| POST | `/api/auth/register` | تسجيل مستخدم جديد | — |
| POST | `/api/auth/login` | تسجيل الدخول والحصول على Token | — |
| GET | `/api/auth/me` | بيانات المستخدم الحالي | Bearer |
| PUT | `/api/auth/me` | تحديث البيانات الشخصية | Bearer |
| POST | `/api/auth/change-password` | تغيير كلمة المرور | Bearer |

### Activation — التفعيل
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| POST | `/api/activation/request` | تقديم طلب تفعيل | Bearer |
| POST | `/api/activation/verify` | التحقق من كود التفعيل | Bearer |
| GET | `/api/activation/status` | حالة التفعيل الحالية | Bearer |

### Projects — المشاريع
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| POST | `/api/projects` | إنشاء مشروع جديد | Activated |
| GET | `/api/projects` | قائمة المشاريع | Activated |
| GET | `/api/projects/{id}` | تفاصيل مشروع | Activated |
| PUT | `/api/projects/{id}` | تحديث مشروع | Activated |
| DELETE | `/api/projects/{id}` | أرشفة مشروع | Activated |

### AI Extraction — الاستخراج بالذكاء الاصطناعي
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| POST | `/api/projects/{id}/upload` | رفع ملف PDF/DOCX/TXT | Activated |
| POST | `/api/projects/{id}/extract` | استخراج السياق بالذكاء الاصطناعي | Activated |
| GET | `/api/projects/{id}/context` | الحصول على السياق المستخرج | Activated |
| PUT | `/api/projects/{id}/context` | تحديث السياق المستخرج | Activated |
| POST | `/api/projects/{id}/suggest-risks` | اقتراح مخاطر بالذكاء الاصطناعي | Activated |
| GET | `/api/risk-categories` | قائمة الفئات المعتمدة | Activated |

### Risk Plan — خطة إدارة المخاطر
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| POST | `/api/projects/{id}/risk-plan` | إنشاء خطة | Activated |
| GET | `/api/projects/{id}/risk-plan` | قائمة الخطط | Activated |
| PUT | `/api/projects/{id}/risk-plan/{plan_id}` | تحديث الخطة | Activated |
| POST | `/api/projects/{id}/risk-plan/{plan_id}/advance-workflow` | تقديم في سير العمل | Activated |

**معاملات advance-workflow (action):**
- `submit_consultant` — إرسال للاستشاري
- `approve_consultant` — موافقة الاستشاري
- `submit_owner` — إرسال للمالك
- `approve_owner` — موافقة المالك
- `make_effective` — تفعيل الخطة
- `return` — إعادة للتعديل

### Risk Register — سجل المخاطر
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| POST | `/api/projects/{id}/risks` | إضافة مخاطرة | Activated |
| GET | `/api/projects/{id}/risks` | قائمة المخاطر (مع فلاتر) | Activated |
| GET | `/api/projects/{id}/risks/{risk_id}` | تفاصيل مخاطرة | Activated |
| PUT | `/api/projects/{id}/risks/{risk_id}` | تحديث مخاطرة | Activated |
| DELETE | `/api/projects/{id}/risks/{risk_id}` | إلغاء مخاطرة | Activated |

**فلاتر الاستعلام للقائمة:** `category`, `risk_type`, `lifecycle_status`, `approval_status`, `page`, `page_size`

### Response Tracking — متابعة الاستجابة
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| POST | `/api/projects/{id}/tracking` | إضافة سجل متابعة | Activated |
| GET | `/api/projects/{id}/tracking` | قائمة سجلات المتابعة | Activated |
| PUT | `/api/projects/{id}/tracking/{item_id}` | تحديث سجل | Activated |

### RACI & Business Process
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| GET | `/api/projects/{id}/raci` | مصفوفة RACI | Activated |
| POST | `/api/projects/{id}/raci` | حفظ مصفوفة RACI | Activated |
| GET | `/api/projects/{id}/business-processes` | سير عمليات الأطراف | Activated |

### Dashboard & Analytics
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| GET | `/api/projects/{id}/dashboard` | ملخص لوحة القيادة | Activated |
| POST | `/api/projects/{id}/analytics/monte-carlo` | محاكاة مونت كارلو | Activated |
| GET | `/api/projects/{id}/analytics/sensitivity` | تحليل الحساسية | Activated |

### Exports — التصدير
| الطريقة | المسار | الوصف | الحماية |
|---------|--------|-------|---------|
| GET | `/api/projects/{id}/export/risks` | تصدير سجل المخاطر Excel | Activated |
| GET | `/api/projects/{id}/export/tracking` | تصدير المتابعة Excel | Activated |
| GET | `/api/projects/{id}/export/risk-plan/{plan_id}` | تصدير الخطة Word | Activated |

### Admin — الإدارة (يتطلب دور admin)
| الطريقة | المسار | الوصف |
|---------|--------|-------|
| GET | `/api/admin/stats` | إحصائيات عامة |
| GET | `/api/admin/users` | قائمة المستخدمين |
| PUT | `/api/admin/users/{id}` | تحديث مستخدم |
| GET | `/api/admin/activation-requests` | طلبات التفعيل المعلقة |
| POST | `/api/admin/activation-requests/action` | موافقة/رفض طلب |
| POST | `/api/admin/users/{id}/generate-code` | توليد كود تفعيل |
| GET | `/api/admin/users/{id}/activation-codes` | أكواد مستخدم |
| GET | `/api/admin/projects` | جميع المشاريع |
| GET | `/api/admin/audit-logs` | سجل التدقيق |
| GET | `/api/admin/export/master` | تصدير ماستر Excel |

---

## 6. مسار التفعيل الكامل

```
تسجيل المستخدم
    ↓
المستخدم يدفع عبر PayPal (https://www.paypal.com/ncp/payment/H5MAQK4YA58WJ)
    ↓
المستخدم يرسل إيصال الدفع عبر WhatsApp (+201005394312)
    ↓
المستخدم يقدم طلب تفعيل: POST /api/activation/request
    ↓
المشرف يراجع الطلبات: GET /api/admin/activation-requests
    ↓
المشرف يوافق: POST /api/admin/activation-requests/action (action=approve)
    ↓ (يُرسَل الكود تلقائياً بالبريد الإلكتروني)
المستخدم يدخل الكود: POST /api/activation/verify
    ↓
✅ الحساب مفعّل — وصول كامل للمنصة
```

---

## 7. توثيق API التفاعلي

بعد تشغيل الخادم، افتح:
- **Swagger UI:** http://localhost:8000/api/docs
- **ReDoc:** http://localhost:8000/api/redoc

---

## 8. اختبار سريع بـ curl

```bash
# تسجيل الدخول
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"anajjar@pmhouse.org","password":"Admin@123456"}'

# الحصول على قائمة المشاريع (استبدل TOKEN بالرمز المستلم)
curl -H "Authorization: Bearer TOKEN" \
  http://localhost:8000/api/projects

# الحصول على لوحة القيادة للمشروع 1
curl -H "Authorization: Bearer TOKEN" \
  http://localhost:8000/api/projects/1/dashboard
```
