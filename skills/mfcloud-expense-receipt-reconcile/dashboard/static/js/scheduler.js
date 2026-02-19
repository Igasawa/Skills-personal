(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));

  const DEFAULT_ACTION_KEY = "preflight";
  const ALLOWED_ACTION_KEYS = new Set([
    "preflight",
    "preflight_mf",
    "amazon_download",
    "rakuten_download",
    "amazon_print",
    "rakuten_print",
    "mf_reconcile",
  ]);

  const form = document.getElementById("run-form");
  const panelEl = document.getElementById("scheduler-panel");
  const toggleEl = document.getElementById("scheduler-toggle");
  const runDateEl = document.getElementById("scheduler-run-date");
  const runTimeEl = document.getElementById("scheduler-run-time");
  const catchUpEl = document.getElementById("scheduler-catch-up");
  const recurrenceEl = document.getElementById("scheduler-recurrence");
  const refreshEl = document.getElementById("scheduler-refresh");
  const saveEl = document.getElementById("scheduler-save");
  const summaryEl = document.getElementById("scheduler-summary");
  const pageEl = document.querySelector(".page");

  if (!form || !panelEl || !toggleEl || !runDateEl || !runTimeEl || !catchUpEl || !recurrenceEl || !refreshEl || !saveEl || !summaryEl) {
    return;
  }

  let busy = false;

  function toInt(value, fallback = null) {
    const n = Number.parseInt(String(value ?? "").trim(), 10);
    return Number.isFinite(n) ? n : fallback;
  }

  function todayDateString() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function recurrenceLabel(code) {
    const map = {
      once: "once",
      daily: "daily",
      weekly: "weekly",
      monthly: "monthly",
    };
    return map[code] || code || "once";
  }

  function normalizeActionKey(value) {
    const actionKey = String(value || "").trim();
    if (!actionKey) return DEFAULT_ACTION_KEY;
    if (ALLOWED_ACTION_KEYS.has(actionKey)) return actionKey;
    return DEFAULT_ACTION_KEY;
  }

  function resolveWorkflowPageMeta() {
    const workflowPageRaw = String(pageEl?.dataset?.workflowPage || "").trim();
    if (!workflowPageRaw) return null;
    try {
      const parsed = JSON.parse(workflowPageRaw);
      if (!parsed || typeof parsed !== "object") return null;
      return parsed;
    } catch {
      return null;
    }
  }

  function resolveTemplateIdForScheduler() {
    const workflowPage = resolveWorkflowPageMeta();
    const workflowPageId = String(workflowPage?.id || "").trim();
    if (workflowPageId) return workflowPageId;

    const templateId = String(form.querySelector("[name=template_id]")?.value || "").trim();
    if (templateId) return templateId;
    return "";
  }

  function resolveSchedulerCardId() {
    const fromPanel = String(panelEl.dataset.schedulerCardId || "").trim();
    if (fromPanel) return fromPanel;

    const workflowPage = resolveWorkflowPageMeta();
    const workflowPageId = String(workflowPage?.id || "").trim();
    if (workflowPageId) return `workflow-page:${workflowPageId}`;

    const templateId = resolveTemplateIdForScheduler();
    if (templateId) return `workflow-template:${templateId}`;

    return "scheduler-default";
  }

  function resolveSchedulerActionKey() {
    return normalizeActionKey(panelEl.dataset.schedulerActionKey || DEFAULT_ACTION_KEY);
  }

  function buildSchedulerStateUrl() {
    const templateId = resolveTemplateIdForScheduler();
    if (!templateId) return "/api/scheduler/state";
    return `/api/scheduler/state?template_id=${encodeURIComponent(templateId)}`;
  }

  function setBusy(nextBusy) {
    busy = Boolean(nextBusy);
    toggleEl.disabled = busy;
    runDateEl.disabled = busy;
    runTimeEl.disabled = busy;
    catchUpEl.disabled = busy;
    recurrenceEl.disabled = busy;
    refreshEl.disabled = busy;
    saveEl.disabled = busy;
  }

  async function apiGetState() {
    const baseUrl = buildSchedulerStateUrl();
    const res = await fetch(`${baseUrl}${baseUrl.includes("?") ? "&" : "?"}_=${Date.now()}`, {
      cache: "no-store",
    }).catch(() => null);
    if (!res) throw new Error("network error");
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    return body;
  }

  async function apiSaveState(payload) {
    const baseUrl = buildSchedulerStateUrl();
    const res = await fetch(baseUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }).catch(() => null);
    if (!res) throw new Error("network error");
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    return body;
  }

  function readFormValues() {
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    const urlEl = form.querySelector("[name=mfcloud_url]");
    const notesEl = form.querySelector("[name=notes]");
    return {
      year: toInt(yearEl?.value, null),
      month: toInt(monthEl?.value, null),
      mfcloud_url: String(urlEl?.value || "").trim(),
      notes: String(notesEl?.value || "").trim(),
    };
  }

  function renderSummary(state) {
    const pieces = [];
    pieces.push(toggleEl.checked ? "ON" : "OFF");

    const cardId = String(state.card_id || "").trim() || resolveSchedulerCardId();
    const actionKey = normalizeActionKey(state.action_key || resolveSchedulerActionKey());
    pieces.push(`card: ${cardId}`);
    pieces.push(`action: ${actionKey}`);

    if (state.next_run_at) {
      pieces.push(`next: ${String(state.next_run_at).replace("T", " ")}`);
    } else if (state.run_date) {
      pieces.push(`next: ${state.run_date} ${state.run_time || "09:00"}`);
    }

    const recurrence = String(state.recurrence || "once");
    pieces.push(`repeat: ${recurrenceLabel(recurrence)}`);

    if (state.last_result && typeof state.last_result === "object") {
      const resultStatus = String(state.last_result.status || "").trim();
      if (resultStatus) {
        pieces.push(`last: ${resultStatus}`);
      }
    }
    summaryEl.textContent = pieces.join(" / ");
  }

  function applyState(state) {
    toggleEl.checked = Boolean(state.enabled);
    runDateEl.value = String(state.run_date || "");
    runTimeEl.value = String(state.run_time || "09:00");
    catchUpEl.value = String(state.catch_up_policy || "run_on_startup");
    recurrenceEl.value = String(state.recurrence || "once");

    if (!runDateEl.value) runDateEl.value = todayDateString();
    if (!runTimeEl.value) runTimeEl.value = "09:00";
    if (!recurrenceEl.value) recurrenceEl.value = "once";

    renderSummary(state || {});
  }

  async function refreshState() {
    setBusy(true);
    try {
      const data = await apiGetState();
      applyState(data || {});
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "scheduler load failed");
      showToast(message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveState() {
    if (busy) return;
    const formValues = readFormValues();
    const payload = {
      enabled: Boolean(toggleEl.checked),
      card_id: resolveSchedulerCardId(),
      action_key: resolveSchedulerActionKey(),
      year: formValues.year,
      month: formValues.month,
      mfcloud_url: formValues.mfcloud_url,
      notes: formValues.notes,
      run_date: String(runDateEl.value || "").trim() || null,
      run_time: String(runTimeEl.value || "").trim() || "09:00",
      catch_up_policy: String(catchUpEl.value || "run_on_startup"),
      recurrence: String(recurrenceEl.value || "once"),
    };

    setBusy(true);
    try {
      const data = await apiSaveState(payload);
      applyState(data || {});
      showToast("Scheduler settings saved.", "success");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "scheduler save failed");
      showToast(message, "error");
    } finally {
      setBusy(false);
    }
  }

  toggleEl.addEventListener("change", () => {
    if (toggleEl.checked && !runDateEl.value) {
      runDateEl.value = todayDateString();
    }
  });

  refreshEl.addEventListener("click", () => {
    refreshState();
  });

  saveEl.addEventListener("click", () => {
    saveState();
  });

  document.addEventListener("scheduler-state-updated", () => {
    refreshState();
  });

  document.addEventListener("scheduler-context-changed", (event) => {
    const detail = event?.detail && typeof event.detail === "object" ? event.detail : {};
    if (detail.card_id != null) {
      panelEl.dataset.schedulerCardId = String(detail.card_id || "").trim();
    }
    if (detail.action_key != null) {
      panelEl.dataset.schedulerActionKey = normalizeActionKey(detail.action_key);
    }
    refreshState();
  });

  if (!runDateEl.value) runDateEl.value = todayDateString();
  if (!runTimeEl.value) runTimeEl.value = "09:00";
  if (!recurrenceEl.value) recurrenceEl.value = "once";

  refreshState();
})();
