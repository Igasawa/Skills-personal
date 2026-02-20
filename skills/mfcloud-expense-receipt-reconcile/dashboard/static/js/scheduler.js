(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const SCHEDULER_SYNC_NOTICE_STORAGE_KEY = "workflowSchedulerSyncNotice";

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
  const templateHintEl = document.getElementById("scheduler-template-hint");
  const syncReasonEl = document.getElementById("scheduler-sync-reason");
  const workflowEventSummaryPanelEl = document.getElementById("workflow-event-summary-panel");
  const workflowEventSummaryRefreshEl = document.getElementById("workflow-event-summary-refresh");
  const workflowEventSummaryMetaEl = document.getElementById("workflow-event-summary-meta");
  const workflowEventSummaryKpisEl = document.getElementById("workflow-event-summary-kpis");
  const workflowEventSummaryReasonClassEl = document.getElementById("workflow-event-summary-reason-class");
  const workflowEventSummaryDuplicateEl = document.getElementById("workflow-event-summary-duplicate");
  const workflowEventSummaryRetryAdviceEl = document.getElementById("workflow-event-summary-retry-advice");
  const workflowEventSummaryRecentEl = document.getElementById("workflow-event-summary-recent");
  const pageEl = document.querySelector(".page");
  const templateStepsListEl = document.getElementById("template-steps-list");

  if (!form || !panelEl || !toggleEl || !runDateEl || !runTimeEl || !catchUpEl || !recurrenceEl || !refreshEl || !saveEl || !summaryEl) {
    return;
  }

  const requireTemplateContext = panelEl.dataset.schedulerRequireTemplate === "1";
  let busy = false;
  let templateContextMissing = false;
  let latestAppliedState = {};
  let syncNoticeApplied = false;

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

  function toYmString(year, month) {
    const y = toInt(year, null);
    const m = toInt(month, null);
    if (!Number.isInteger(y) || !Number.isInteger(m) || y < 2000 || m < 1 || m > 12) return "";
    return `${String(y)}-${String(m).padStart(2, "0")}`;
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

  function toAllowedActionKey(value) {
    const actionKey = String(value || "").trim();
    if (!actionKey) return "";
    if (ALLOWED_ACTION_KEYS.has(actionKey)) return actionKey;
    return "";
  }

  function normalizeActionKey(value) {
    const actionKey = toAllowedActionKey(value);
    if (actionKey) return actionKey;
    return DEFAULT_ACTION_KEY;
  }

  function resolveActionKeyFromTemplateSteps() {
    const firstRow = templateStepsListEl?.querySelector("[data-template-step-row]");
    if (!firstRow) return "";
    const fromDataset = toAllowedActionKey(firstRow.dataset?.templateStepAction);
    if (fromDataset) return fromDataset;
    const actionInput = firstRow.querySelector("[data-template-step-action]");
    return toAllowedActionKey(actionInput?.value);
  }

  function syncSchedulerActionKeyFromTemplateSteps() {
    const fromStep = resolveActionKeyFromTemplateSteps();
    if (!fromStep) return normalizeActionKey(panelEl.dataset.schedulerActionKey || DEFAULT_ACTION_KEY);
    panelEl.dataset.schedulerActionKey = fromStep;
    return fromStep;
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
    const fromPanel = toAllowedActionKey(panelEl.dataset.schedulerActionKey);
    if (fromPanel) return fromPanel;
    const fromStep = resolveActionKeyFromTemplateSteps();
    if (fromStep) return fromStep;
    return DEFAULT_ACTION_KEY;
  }

  function buildSchedulerStateUrl() {
    const templateId = resolveTemplateIdForScheduler();
    if (!templateId) {
      if (requireTemplateContext) return "";
      return "/api/scheduler/state";
    }
    return `/api/scheduler/state?template_id=${encodeURIComponent(templateId)}`;
  }

  function clearSchedulerSyncNotice() {
    if (!syncReasonEl) return;
    syncReasonEl.hidden = true;
    syncReasonEl.textContent = "";
  }

  function consumeSchedulerSyncNotice() {
    if (!syncReasonEl || syncNoticeApplied) return;
    const templateId = resolveTemplateIdForScheduler();
    if (!templateId) return;

    let payload = {};
    try {
      const raw = window.sessionStorage?.getItem(SCHEDULER_SYNC_NOTICE_STORAGE_KEY);
      payload = raw ? JSON.parse(raw) : {};
    } catch {
      payload = {};
    }
    if (!payload || typeof payload !== "object") return;
    const targetTemplateId = String(payload.template_id || "").trim();
    if (targetTemplateId && targetTemplateId !== templateId) return;
    const message = String(payload.message || "").trim();
    if (!message) return;

    syncReasonEl.textContent = `同期結果: ${message}`;
    syncReasonEl.hidden = false;
    syncNoticeApplied = true;
    try {
      window.sessionStorage?.removeItem(SCHEDULER_SYNC_NOTICE_STORAGE_KEY);
    } catch {}
  }

  function setBusy(nextBusy) {
    busy = Boolean(nextBusy);
    const disabled = busy || templateContextMissing;
    toggleEl.disabled = disabled;
    runDateEl.disabled = disabled;
    runTimeEl.disabled = disabled;
    catchUpEl.disabled = disabled;
    recurrenceEl.disabled = disabled;
    refreshEl.disabled = disabled;
    saveEl.disabled = disabled;
  }

  async function apiGetState(baseUrl = buildSchedulerStateUrl()) {
    const res = await fetch(`${baseUrl}${baseUrl.includes("?") ? "&" : "?"}_=${Date.now()}`, {
      cache: "no-store",
    }).catch(() => null);
    if (!res) throw new Error("network error");
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    return body;
  }

  async function apiSaveState(payload, baseUrl = buildSchedulerStateUrl()) {
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

  async function apiGetWorkflowEventSummary(url) {
    const res = await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, {
      cache: "no-store",
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

  function workflowEventSummaryRecentLimit() {
    const raw = String(workflowEventSummaryPanelEl?.dataset?.workflowEventRecentLimit || "").trim();
    const n = toInt(raw, 20);
    if (!Number.isInteger(n)) return 20;
    if (n < 1) return 1;
    if (n > 200) return 200;
    return n;
  }

  function buildWorkflowEventSummaryUrl() {
    const values = readFormValues();
    const ym = toYmString(values.year, values.month);
    if (!ym) return "";
    const recentLimit = workflowEventSummaryRecentLimit();
    return `/api/workflow-events/summary?ym=${encodeURIComponent(ym)}&recent_limit=${recentLimit}`;
  }

  function replaceChildrenText(targetEl, rows) {
    if (!targetEl) return;
    targetEl.innerHTML = "";
    const values = Array.isArray(rows) ? rows : [];
    if (values.length === 0) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "データなし";
      targetEl.appendChild(li);
      return;
    }
    values.forEach((row) => {
      const li = document.createElement("li");
      li.textContent = String(row || "");
      targetEl.appendChild(li);
    });
  }

  function renderWorkflowEventSummaryRecentRows(rows) {
    if (!workflowEventSummaryRecentEl) return;
    workflowEventSummaryRecentEl.innerHTML = "";
    const values = Array.isArray(rows) ? rows : [];
    if (values.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.className = "muted";
      td.textContent = "該当イベントなし";
      tr.appendChild(td);
      workflowEventSummaryRecentEl.appendChild(tr);
      return;
    }

    values.forEach((row) => {
      const current = row && typeof row === "object" ? row : {};
      const tr = document.createElement("tr");

      const at = document.createElement("td");
      at.textContent = String(current.at || "").replace("T", " ") || "-";
      tr.appendChild(at);

      const status = document.createElement("td");
      status.textContent = String(current.status || "") || "-";
      tr.appendChild(status);

      const event = document.createElement("td");
      const eventName = String(current.event_name || "").trim();
      const templateName = String(current.template_name || "").trim();
      event.textContent = eventName || templateName ? `${eventName || "-"} / ${templateName || "-"}` : "-";
      tr.appendChild(event);

      const reason = document.createElement("td");
      const reasonClass = String(current.reason_class || "").trim();
      const reasonCode = String(current.reason_code || "").trim();
      const reasonText = String(current.reason || "").trim();
      reason.textContent = reasonClass || reasonCode || reasonText || "-";
      tr.appendChild(reason);

      const duplicate = document.createElement("td");
      if (current.duplicate === true) {
        duplicate.textContent = "true";
      } else if (current.duplicate === false) {
        duplicate.textContent = "false";
      } else {
        duplicate.textContent = "-";
      }
      tr.appendChild(duplicate);

      workflowEventSummaryRecentEl.appendChild(tr);
    });
  }

  function renderWorkflowEventSummary(summary) {
    if (!workflowEventSummaryPanelEl) return;
    const data = summary && typeof summary === "object" ? summary : {};

    const byStatus = data.by_status && typeof data.by_status === "object" ? data.by_status : {};
    const total = toInt(data.total, 0);
    const ym = String(data.ym || "").trim();
    const lastAt = String(data.last_at || "").trim();
    if (workflowEventSummaryMetaEl) {
      workflowEventSummaryMetaEl.textContent = `${ym || "-"} / total: ${total} / last: ${lastAt || "-"}`;
    }

    if (workflowEventSummaryKpisEl) {
      const kpis = [
        { label: "成功", value: toInt(byStatus.success, 0) },
        { label: "重複スキップ", value: toInt(byStatus.skipped, 0) },
        { label: "拒否", value: toInt(byStatus.rejected, 0) },
        { label: "失敗", value: toInt(byStatus.failed, 0) },
      ];
      workflowEventSummaryKpisEl.innerHTML = "";
      kpis.forEach((item) => {
        const li = document.createElement("li");
        li.className = "workflow-event-summary-kpi";
        const label = document.createElement("span");
        label.className = "workflow-event-summary-kpi-label";
        label.textContent = item.label;
        const value = document.createElement("strong");
        value.className = "workflow-event-summary-kpi-value";
        value.textContent = String(item.value);
        li.appendChild(label);
        li.appendChild(value);
        workflowEventSummaryKpisEl.appendChild(li);
      });
    }

    const reasonClassRows = Array.isArray(data.by_reason_class) ? data.by_reason_class.slice(0, 5) : [];
    replaceChildrenText(
      workflowEventSummaryReasonClassEl,
      reasonClassRows.map((row) => {
        const reasonClass = String(row?.reason_class || "").trim() || "unknown";
        const count = toInt(row?.count, 0);
        return `${reasonClass}: ${count}`;
      }),
    );

    const duplicate = data.duplicate && typeof data.duplicate === "object" ? data.duplicate : {};
    replaceChildrenText(workflowEventSummaryDuplicateEl, [
      `true: ${toInt(duplicate.true, 0)}`,
      `false: ${toInt(duplicate.false, 0)}`,
      `unknown: ${toInt(duplicate.unknown, 0)}`,
    ]);

    const retryAdviceRows = Array.isArray(data.by_retry_advice) ? data.by_retry_advice.slice(0, 5) : [];
    replaceChildrenText(
      workflowEventSummaryRetryAdviceEl,
      retryAdviceRows.map((row) => {
        const retryAdvice = String(row?.retry_advice || "").trim() || "unknown";
        const count = toInt(row?.count, 0);
        return `${retryAdvice}: ${count}`;
      }),
    );

    renderWorkflowEventSummaryRecentRows(Array.isArray(data.recent) ? data.recent : []);
  }

  function renderWorkflowEventSummaryError(message) {
    if (workflowEventSummaryMetaEl) {
      workflowEventSummaryMetaEl.textContent = message || "監査サマリーを取得できませんでした。";
    }
    replaceChildrenText(workflowEventSummaryKpisEl, []);
    replaceChildrenText(workflowEventSummaryReasonClassEl, []);
    replaceChildrenText(workflowEventSummaryDuplicateEl, []);
    replaceChildrenText(workflowEventSummaryRetryAdviceEl, []);
    renderWorkflowEventSummaryRecentRows([]);
  }

  async function refreshWorkflowEventSummary(options = {}) {
    if (!workflowEventSummaryPanelEl) return;
    const opts = options && typeof options === "object" ? options : {};
    const withToast = Boolean(opts.withToast);
    const summaryUrl = buildWorkflowEventSummaryUrl();
    if (!summaryUrl) {
      renderWorkflowEventSummaryError("年月が未設定のため監査サマリーを取得できません。");
      return;
    }
    if (workflowEventSummaryMetaEl) {
      workflowEventSummaryMetaEl.textContent = "監査サマリーを読み込み中...";
    }
    if (workflowEventSummaryRefreshEl) {
      workflowEventSummaryRefreshEl.disabled = true;
    }
    try {
      const data = await apiGetWorkflowEventSummary(summaryUrl);
      renderWorkflowEventSummary(data || {});
      if (withToast) {
        showToast("外部イベント監査サマリーを更新しました。", "success");
      }
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "workflow event summary load failed");
      renderWorkflowEventSummaryError(`監査サマリー取得エラー: ${message}`);
      if (withToast) {
        showToast(message, "error");
      }
    } finally {
      if (workflowEventSummaryRefreshEl) {
        workflowEventSummaryRefreshEl.disabled = false;
      }
    }
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
    latestAppliedState = state || {};
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
    syncSchedulerActionKeyFromTemplateSteps();
    const baseUrl = buildSchedulerStateUrl();
    if (!baseUrl) {
      templateContextMissing = true;
      applyState({
        enabled: false,
        card_id: resolveSchedulerCardId(),
        action_key: resolveSchedulerActionKey(),
        run_date: todayDateString(),
        run_time: "09:00",
        catch_up_policy: "run_on_startup",
        recurrence: "once",
        next_run_at: null,
        last_result: null,
      });
      summaryEl.textContent = "テンプレートを選択するとスケジュール設定を編集できます。";
      if (templateHintEl) templateHintEl.hidden = false;
      clearSchedulerSyncNotice();
      await refreshWorkflowEventSummary();
      setBusy(false);
      return;
    }
    templateContextMissing = false;
    if (templateHintEl) templateHintEl.hidden = true;
    setBusy(true);
    try {
      const data = await apiGetState(baseUrl);
      applyState(data || {});
      consumeSchedulerSyncNotice();
      await refreshWorkflowEventSummary();
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "scheduler load failed");
      showToast(message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveState() {
    if (busy) return;
    syncSchedulerActionKeyFromTemplateSteps();
    const baseUrl = buildSchedulerStateUrl();
    if (!baseUrl) {
      templateContextMissing = true;
      setBusy(false);
      showToast("テンプレートを選択するとスケジュールを保存できます。", "error");
      return;
    }
    templateContextMissing = false;
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
      const data = await apiSaveState(payload, baseUrl);
      applyState(data || {});
      await refreshWorkflowEventSummary();
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

  workflowEventSummaryRefreshEl?.addEventListener("click", () => {
    refreshWorkflowEventSummary({ withToast: true });
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

  templateStepsListEl?.addEventListener("template-steps-changed", () => {
    const previousActionKey = resolveSchedulerActionKey();
    const nextActionKey = syncSchedulerActionKeyFromTemplateSteps();
    if (previousActionKey !== nextActionKey) {
      renderSummary({ ...(latestAppliedState || {}), action_key: nextActionKey });
    }
  });

  if (!runDateEl.value) runDateEl.value = todayDateString();
  if (!runTimeEl.value) runTimeEl.value = "09:00";
  if (!recurrenceEl.value) recurrenceEl.value = "once";

  refreshState();
})();
