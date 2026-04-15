/**
 * api.js — Axios-based API client for PMI Risk Management Platform
 * Connects the Arabic RTL frontend to the FastAPI backend.
 * All requests include Bearer token auth from localStorage.
 *
 * Usage (plain HTML):
 *   <script src="api.js"></script>
 *   const api = new RiskAPI("http://localhost:8000");
 */

class RiskAPI {
  constructor(baseURL = "http://localhost:8000") {
    this.base = baseURL.replace(/\/$/, "");
    this.token = localStorage.getItem("riskpro_token") || null;
  }

  // ── Internal HTTP helpers ────────────────────────────────────

  _headers(extra = {}) {
    const h = { "Content-Type": "application/json", ...extra };
    if (this.token) h["Authorization"] = `Bearer ${this.token}`;
    return h;
  }

  async _fetch(path, options = {}) {
    const url = `${this.base}${path}`;
    const resp = await fetch(url, {
      headers: this._headers(),
      ...options,
    });
    if (!resp.ok) {
      let errMsg = `HTTP ${resp.status}`;
      try {
        const err = await resp.json();
        errMsg = err.detail || err.message || JSON.stringify(err);
      } catch (_) {}
      throw new Error(errMsg);
    }
    const ct = resp.headers.get("content-type") || "";
    if (ct.includes("application/json")) return resp.json();
    if (ct.includes("spreadsheet") || ct.includes("wordprocessingml") || ct.includes("octet-stream")) {
      return resp.blob();
    }
    return resp.text();
  }

  _post(path, body) {
    return this._fetch(path, { method: "POST", body: JSON.stringify(body) });
  }

  _put(path, body) {
    return this._fetch(path, { method: "PUT", body: JSON.stringify(body) });
  }

  _delete(path) {
    return this._fetch(path, { method: "DELETE" });
  }

  _get(path) {
    return this._fetch(path, { method: "GET" });
  }

  // ── Auth ─────────────────────────────────────────────────────

  async register(fullName, email, password, mobile, company, country) {
    return this._post("/api/auth/register", {
      full_name: fullName, email, password,
      mobile, company, country,
    });
  }

  async login(email, password) {
    const data = await this._post("/api/auth/login", { email, password });
    this.token = data.access_token;
    localStorage.setItem("riskpro_token", this.token);
    localStorage.setItem("riskpro_user", JSON.stringify({
      id: data.user_id, role: data.role,
      status: data.status, full_name: data.full_name,
    }));
    return data;
  }

  logout() {
    this.token = null;
    localStorage.removeItem("riskpro_token");
    localStorage.removeItem("riskpro_user");
  }

  isLoggedIn() {
    return !!this.token;
  }

  currentUser() {
    try {
      return JSON.parse(localStorage.getItem("riskpro_user") || "null");
    } catch { return null; }
  }

  isAdmin() {
    return this.currentUser()?.role === "admin";
  }

  isActivated() {
    const u = this.currentUser();
    return u && (u.status === "activated" || u.role === "admin");
  }

  getMe() { return this._get("/api/auth/me"); }
  updateMe(data) { return this._put("/api/auth/me", data); }
  changePassword(currentPw, newPw) {
    return this._post("/api/auth/change-password", {
      current_password: currentPw, new_password: newPw,
    });
  }

  // ── Activation ───────────────────────────────────────────────

  getActivationStatus() { return this._get("/api/activation/status"); }
  submitActivationRequest(paymentRef, whatsappNote) {
    return this._post("/api/activation/request", {
      payment_reference: paymentRef, whatsapp_note: whatsappNote,
    });
  }
  verifyActivationCode(code) {
    return this._post("/api/activation/verify", { code });
  }

  // ── Projects ─────────────────────────────────────────────────

  listProjects() { return this._get("/api/projects"); }
  getProject(id) { return this._get(`/api/projects/${id}`); }
  createProject(data) { return this._post("/api/projects", data); }
  updateProject(id, data) { return this._put(`/api/projects/${id}`, data); }
  deleteProject(id) { return this._delete(`/api/projects/${id}`); }

  // ── File Upload & AI Extraction ──────────────────────────────

  async uploadFile(projectId, file) {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${this.base}/api/projects/${projectId}/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}` },
      body: form,
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "فشل رفع الملف");
    }
    return resp.json();
  }

  async extractContext(projectId, text = null, fileId = null) {
    const form = new FormData();
    if (text) form.append("text", text);
    if (fileId) form.append("file_id", String(fileId));
    const resp = await fetch(`${this.base}/api/projects/${projectId}/extract`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}` },
      body: form,
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "فشل الاستخراج");
    }
    return resp.json();
  }

  getContext(projectId) { return this._get(`/api/projects/${projectId}/context`); }
  updateContext(projectId, data) { return this._put(`/api/projects/${projectId}/context`, data); }
  suggestRisks(projectId) { return this._post(`/api/projects/${projectId}/suggest-risks`, {}); }

  // ── Risk Categories ──────────────────────────────────────────

  getRiskCategories() { return this._get("/api/risk-categories"); }

  // ── Business Process ─────────────────────────────────────────

  getBusinessProcesses(projectId) {
    return this._get(`/api/projects/${projectId}/business-processes`);
  }

  // ── RACI ─────────────────────────────────────────────────────

  getRaci(projectId) { return this._get(`/api/projects/${projectId}/raci`); }
  saveRaci(projectId, rows) { return this._post(`/api/projects/${projectId}/raci`, rows); }

  // ── Risk Plan ────────────────────────────────────────────────

  createRiskPlan(projectId, data) {
    return this._post(`/api/projects/${projectId}/risk-plan`, { project_id: projectId, ...data });
  }
  getRiskPlans(projectId) { return this._get(`/api/projects/${projectId}/risk-plan`); }
  updateRiskPlan(projectId, planId, data) {
    return this._put(`/api/projects/${projectId}/risk-plan/${planId}`, data);
  }
  advancePlanWorkflow(projectId, planId, action) {
    return this._post(
      `/api/projects/${projectId}/risk-plan/${planId}/advance-workflow?action=${encodeURIComponent(action)}`,
      {}
    );
  }

  // ── Risk Register ────────────────────────────────────────────

  listRisks(projectId, filters = {}) {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    const qs = params.toString() ? `?${params}` : "";
    return this._get(`/api/projects/${projectId}/risks${qs}`);
  }
  getRisk(projectId, riskId) { return this._get(`/api/projects/${projectId}/risks/${riskId}`); }
  createRisk(projectId, data) {
    return this._post(`/api/projects/${projectId}/risks`, { project_id: projectId, ...data });
  }
  updateRisk(projectId, riskId, data) {
    return this._put(`/api/projects/${projectId}/risks/${riskId}`, data);
  }
  deleteRisk(projectId, riskId) {
    return this._delete(`/api/projects/${projectId}/risks/${riskId}`);
  }

  // ── Response Tracking ────────────────────────────────────────

  listTracking(projectId, escalationOnly = false) {
    const qs = escalationOnly ? "?escalation_only=true" : "";
    return this._get(`/api/projects/${projectId}/tracking${qs}`);
  }
  createTracking(projectId, data) {
    return this._post(`/api/projects/${projectId}/tracking`, { project_id: projectId, ...data });
  }
  updateTracking(projectId, itemId, data) {
    return this._put(`/api/projects/${projectId}/tracking/${itemId}`, data);
  }

  // ── Dashboard ────────────────────────────────────────────────

  getDashboard(projectId) { return this._get(`/api/projects/${projectId}/dashboard`); }

  // ── Analytics ────────────────────────────────────────────────

  runMonteCarlo(projectId, baseCost, uncertaintyPct = 20, iterations = 10000) {
    return this._post(`/api/projects/${projectId}/analytics/monte-carlo`, {
      project_id: projectId,
      base_cost: baseCost,
      cost_uncertainty_pct: uncertaintyPct,
      iterations,
    });
  }
  getSensitivity(projectId) {
    return this._get(`/api/projects/${projectId}/analytics/sensitivity`);
  }

  // ── Exports ──────────────────────────────────────────────────

  async downloadRisksExcel(projectId) {
    const blob = await this._get(`/api/projects/${projectId}/export/risks`);
    this._triggerDownload(blob, `risk_register_${projectId}.xlsx`);
  }
  async downloadTrackingExcel(projectId) {
    const blob = await this._get(`/api/projects/${projectId}/export/tracking`);
    this._triggerDownload(blob, `tracking_${projectId}.xlsx`);
  }
  async downloadRiskPlanDocx(projectId, planId) {
    const blob = await this._get(`/api/projects/${projectId}/export/risk-plan/${planId}`);
    this._triggerDownload(blob, `risk_plan_${projectId}.docx`);
  }
  _triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }

  // ── Admin ────────────────────────────────────────────────────

  adminGetStats() { return this._get("/api/admin/stats"); }
  adminListUsers(page = 1, pageSize = 20, status = null) {
    const qs = status ? `?page=${page}&page_size=${pageSize}&status=${status}` : `?page=${page}&page_size=${pageSize}`;
    return this._get(`/api/admin/users${qs}`);
  }
  adminUpdateUser(userId, data) { return this._put(`/api/admin/users/${userId}`, data); }
  adminGetActivationRequests() { return this._get("/api/admin/activation-requests"); }
  adminProcessActivationRequest(requestId, action, adminNotes = null, durationDays = 365) {
    return this._post("/api/admin/activation-requests/action", {
      request_id: requestId, action, admin_notes: adminNotes, duration_days: durationDays,
    });
  }
  adminGenerateCode(userId, durationDays = 365) {
    return this._post(`/api/admin/users/${userId}/generate-code?duration_days=${durationDays}`, {});
  }
  adminListProjects() { return this._get("/api/admin/projects"); }
  adminGetAuditLogs(page = 1, pageSize = 50) {
    return this._get(`/api/admin/audit-logs?page=${page}&page_size=${pageSize}`);
  }
  async adminDownloadMaster() {
    const blob = await this._get("/api/admin/export/master");
    this._triggerDownload(blob, `master_export_${Date.now()}.xlsx`);
  }

  // ── Health ───────────────────────────────────────────────────

  healthCheck() { return this._get("/api/health"); }
}

// ── Global singleton (used by inline scripts in the HTML widget) ──
window.API = new RiskAPI(
  window.RISK_API_BASE || "http://localhost:8000"
);
