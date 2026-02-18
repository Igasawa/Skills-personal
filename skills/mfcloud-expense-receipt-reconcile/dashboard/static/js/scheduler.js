(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const DEFAULT_SCHEDULER_MODE = "preflight";
  const SCHEDULER_MODE_ACTIONS = new Set([
    "preflight",
    "preflight_mf",
    "amazon_download",
    "rakuten_download",
    "amazon_print",
    "rakuten_print",
    "mf_reconcile",
  ]);

  const form = document.getElementById("run-form");
  const enabledEl = document.getElementById("scheduler-enabled");
  const runDateEl = document.getElementById("scheduler-run-date");
  const runTimeEl = document.getElementById("scheduler-run-time");
  const modeEl = document.getElementById("scheduler-mode");
  const catchUpEl = document.getElementById("scheduler-catch-up");
  const recurrenceEl = document.getElementById("scheduler-recurrence");
  const authHandoffEl = document.getElementById("scheduler-auth-handoff");
  const autoStartEl = document.getElementById("scheduler-autostart");
  const refreshEl = document.getElementById("scheduler-refresh");
  const saveEl = document.getElementById("scheduler-save");
  const summaryEl = document.getElementById("scheduler-summary");
  const pageEl = document.querySelector(".page");

  if (
    !form ||
    !enabledEl ||
    !runDateEl ||
    !runTimeEl ||
    !modeEl ||
    !catchUpEl ||
    !recurrenceEl ||
    !authHandoffEl ||
    !autoStartEl ||
    !refreshEl ||
    !saveEl ||
    !summaryEl
  ) {
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
      once: "1回",
      daily: "毎日",
      weekly: "毎週",
      monthly: "毎月",
    };
    return map[code] || code || "1回";
  }

  function getTemplateStepsListEl() {
    const boundListId = String(modeEl.dataset.boundStepList || "").trim();
    if (boundListId && document.getElementById(boundListId)) {
      return document.getElementById(boundListId);
    }
    return form ? form.querySelector("[data-template-steps-list]") : document.querySelector("[data-template-steps-list]");
  }

  function collectTemplateStepActions() {
    const listEl = getTemplateStepsListEl();
    if (!listEl) return [];

    const actionEls = Array.from(listEl.querySelectorAll("[data-template-step-action]"));
    const seen = new Set();
    const actions = [];
    actionEls.forEach((actionEl) => {
      const action = String(actionEl?.value || "").trim();
      if (!action || seen.has(action)) return;
      seen.add(action);
      actions.push(action);
    });

    return actions;
  }

  function collectTemplateStepActionLabelMap() {
    const listEl = getTemplateStepsListEl();
    const labelByAction = Object.create(null);
    if (!listEl) return labelByAction;

    const actionEls = Array.from(listEl.querySelectorAll("[data-template-step-action]"));
    actionEls.forEach((actionEl) => {
      actionEl?.querySelectorAll("option").forEach((option) => {
        const value = String(option.value || "").trim();
        const label = String(option.textContent || "").trim() || value;
        if (!value) return;
        labelByAction[value] = label;
      });
      const selected = String(actionEl?.value || "").trim();
      if (selected && !labelByAction[selected]) {
        labelByAction[selected] = selected;
      }
    });

    return labelByAction;
  }

  function schedulerModeLabel(action, labelByAction) {
    const normalized = String(action || "").trim();
    return labelByAction?.[normalized] || normalized || DEFAULT_SCHEDULER_MODE;
  }

  function ensureSchedulerModeOptionList() {
    const actions = collectTemplateStepActions();
    const dedupedActions = actions.length ? actions : [DEFAULT_SCHEDULER_MODE];
    const unique = [];
    const seen = new Set();

    dedupedActions.forEach((action) => {
      const value = String(action || "").trim() || DEFAULT_SCHEDULER_MODE;
      if (seen.has(value)) return;
      seen.add(value);
      unique.push(value);
    });

    const schedulerActions = unique.filter((action) => SCHEDULER_MODE_ACTIONS.has(action));
    if (!schedulerActions.includes(DEFAULT_SCHEDULER_MODE)) {
      schedulerActions.unshift(DEFAULT_SCHEDULER_MODE);
    }

    const labelByAction = collectTemplateStepActionLabelMap();
    const selectedMode = String(modeEl.value || "").trim() || DEFAULT_SCHEDULER_MODE;
    const selected = schedulerActions.includes(selectedMode) ? selectedMode : DEFAULT_SCHEDULER_MODE;

    modeEl.innerHTML = "";
    schedulerActions.forEach((action) => {
      const option = document.createElement("option");
      option.value = action;
      option.textContent = schedulerModeLabel(action, labelByAction);
      modeEl.appendChild(option);
    });
    modeEl.value = selected;

    return selected;
  }

  function getSchedulerModeValue() {
    return ensureSchedulerModeOptionList();
  }

  function resolveTemplateIdForScheduler() {
    const workflowPageRaw = String(pageEl?.dataset?.workflowPage || "").trim();
    if (workflowPageRaw) {
      try {
        const workflowPage = JSON.parse(workflowPageRaw);
        const workflowPageId = String(workflowPage?.id || "").trim();
        if (workflowPageId) {
          return workflowPageId;
        }
      } catch {
        // Ignore malformed page metadata and continue fallback.
      }
    }

    const templateId = String(form.querySelector("[name=template_id]")?.value || "").trim();
    if (templateId) {
      return templateId;
    }

    return "";
  }

  function buildSchedulerStateUrl() {
    const templateId = resolveTemplateIdForScheduler();
    if (!templateId) return "/api/scheduler/state";
    return `/api/scheduler/state?template_id=${encodeURIComponent(templateId)}`;
  }

  function setBusy(nextBusy) {
    busy = Boolean(nextBusy);
    enabledEl.disabled = busy;
    runDateEl.disabled = busy;
    runTimeEl.disabled = busy;
    modeEl.disabled = busy;
    catchUpEl.disabled = busy;
    recurrenceEl.disabled = busy;
    authHandoffEl.disabled = busy;
    autoStartEl.disabled = busy || autoStartEl.dataset.unsupported === "1";
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
    pieces.push(state.enabled ? "有効" : "無効");
    if (state.next_run_at) {
      pieces.push(`実行予定: ${String(state.next_run_at).replace("T", " ")}`);
    } else if (state.run_date) {
      pieces.push(`次回: ${state.run_date} ${state.run_time || "09:00"}`);
    }
    const recurrence = String(state.recurrence || "once");
    pieces.push(`繰り返し: ${recurrenceLabel(recurrence)}`);
    if (state.last_result && typeof state.last_result === "object") {
      const resultStatus = String(state.last_result.status || "").trim();
      if (resultStatus) {
        pieces.push(`結果: ${resultStatus}`);
      }
    }
    if (state.autostart_supported === false) {
      pieces.push("自動起動: 未対応");
    } else {
      pieces.push(`自動起動: ${state.auto_start_active ? "ON" : "OFF"}`);
    }
    summaryEl.textContent = pieces.join(" / ");
  }

  function applyState(state) {
    enabledEl.checked = Boolean(state.enabled);
    const requestedMode = String(state.mode || DEFAULT_SCHEDULER_MODE);
    modeEl.value = requestedMode;
    modeEl.value = getSchedulerModeValue();

    runDateEl.value = String(state.run_date || "");
    runTimeEl.value = String(state.run_time || "09:00");
    catchUpEl.value = String(state.catch_up_policy || "run_on_startup");
    recurrenceEl.value = String(state.recurrence || "once");
    authHandoffEl.checked = Boolean(state.auth_handoff);

    autoStartEl.dataset.unsupported = state.autostart_supported ? "0" : "1";
    autoStartEl.checked = Boolean(state.auto_start_enabled || state.auto_start_active);
    autoStartEl.disabled = busy || autoStartEl.dataset.unsupported === "1";

    if (!runDateEl.value) {
      runDateEl.value = todayDateString();
    }
    if (!recurrenceEl.value) {
      recurrenceEl.value = "once";
    }
    if (!runTimeEl.value) {
      runTimeEl.value = "09:00";
    }

    renderSummary(state);
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
      enabled: Boolean(enabledEl.checked),
      mode: getSchedulerModeValue(),
      year: formValues.year,
      month: formValues.month,
      mfcloud_url: formValues.mfcloud_url,
      notes: formValues.notes,
      run_date: String(runDateEl.value || "").trim() || null,
      run_time: String(runTimeEl.value || "").trim() || "09:00",
      catch_up_policy: String(catchUpEl.value || "run_on_startup"),
      recurrence: String(recurrenceEl.value || "once"),
      auth_handoff: Boolean(authHandoffEl.checked),
      auto_receipt_name: true,
      mf_draft_create: true,
      auto_start_enabled: Boolean(autoStartEl.checked),
    };

    setBusy(true);
    try {
      const data = await apiSaveState(payload);
      applyState(data || {});
      showToast("タイマー設定を保存しました。", "success");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "scheduler save failed");
      showToast(message, "error");
    } finally {
      setBusy(false);
    }
  }

  enabledEl.addEventListener("change", () => {
    if (enabledEl.checked && !runDateEl.value) {
      runDateEl.value = todayDateString();
    }
  });

  refreshEl.addEventListener("click", () => {
    refreshState();
  });

  saveEl.addEventListener("click", () => {
    saveState();
  });

  const templateStepsListEl = getTemplateStepsListEl();
  const onTemplateStepsChanged = () => {
    getSchedulerModeValue();
  };
  if (templateStepsListEl) {
    templateStepsListEl.addEventListener("template-steps-changed", onTemplateStepsChanged);
  } else {
    document.addEventListener("template-steps-changed", onTemplateStepsChanged);
  }
  document.addEventListener("scheduler-state-updated", () => {
    refreshState();
  });

  if (!runDateEl.value) {
    runDateEl.value = todayDateString();
  }
  if (!runTimeEl.value) {
    runTimeEl.value = "09:00";
  }
  if (!recurrenceEl.value) {
    recurrenceEl.value = "once";
  }

  getSchedulerModeValue();
  refreshState();
})();
