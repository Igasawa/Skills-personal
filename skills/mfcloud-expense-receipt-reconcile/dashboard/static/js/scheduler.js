(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));

  const form = document.getElementById("run-form");
  const enabledEl = document.getElementById("scheduler-enabled");
  const runDateEl = document.getElementById("scheduler-run-date");
  const runTimeEl = document.getElementById("scheduler-run-time");
  const modeEl = document.getElementById("scheduler-mode");
  const catchUpEl = document.getElementById("scheduler-catch-up");
  const authHandoffEl = document.getElementById("scheduler-auth-handoff");
  const autoStartEl = document.getElementById("scheduler-autostart");
  const refreshEl = document.getElementById("scheduler-refresh");
  const saveEl = document.getElementById("scheduler-save");
  const summaryEl = document.getElementById("scheduler-summary");

  if (
    !form ||
    !enabledEl ||
    !runDateEl ||
    !runTimeEl ||
    !modeEl ||
    !catchUpEl ||
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

  function setBusy(nextBusy) {
    busy = Boolean(nextBusy);
    enabledEl.disabled = busy;
    runDateEl.disabled = busy;
    runTimeEl.disabled = busy;
    modeEl.disabled = busy;
    catchUpEl.disabled = busy;
    authHandoffEl.disabled = busy;
    autoStartEl.disabled = busy || autoStartEl.dataset.unsupported === "1";
    refreshEl.disabled = busy;
    saveEl.disabled = busy;
  }

  async function apiGetState() {
    const res = await fetch(`/api/scheduler/state?_=${Date.now()}`, { cache: "no-store" }).catch(() => null);
    if (!res) throw new Error("network error");
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    return body;
  }

  async function apiSaveState(payload) {
    const res = await fetch("/api/scheduler/state", {
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
      pieces.push(`次回: ${String(state.next_run_at).replace("T", " ")}`);
    } else if (state.run_date) {
      pieces.push(`設定: ${state.run_date} ${state.run_time || "09:00"}`);
    }
    if (state.last_result && typeof state.last_result === "object") {
      const resultStatus = String(state.last_result.status || "").trim();
      if (resultStatus) {
        pieces.push(`直近: ${resultStatus}`);
      }
    }
    if (state.autostart_supported === false) {
      pieces.push("自動起動: 非対応");
    } else {
      pieces.push(`自動起動: ${state.auto_start_active ? "ON" : "OFF"}`);
    }
    summaryEl.textContent = pieces.join(" / ");
  }

  function applyState(state) {
    enabledEl.checked = Boolean(state.enabled);
    modeEl.value = String(state.mode || "preflight");
    runDateEl.value = String(state.run_date || "");
    runTimeEl.value = String(state.run_time || "09:00");
    catchUpEl.value = String(state.catch_up_policy || "run_on_startup");
    authHandoffEl.checked = Boolean(state.auth_handoff);

    autoStartEl.dataset.unsupported = state.autostart_supported ? "0" : "1";
    autoStartEl.checked = Boolean(state.auto_start_enabled || state.auto_start_active);
    autoStartEl.disabled = busy || autoStartEl.dataset.unsupported === "1";

    if (!runDateEl.value) {
      runDateEl.value = todayDateString();
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
      mode: String(modeEl.value || "preflight"),
      year: formValues.year,
      month: formValues.month,
      mfcloud_url: formValues.mfcloud_url,
      notes: formValues.notes,
      run_date: String(runDateEl.value || "").trim() || null,
      run_time: String(runTimeEl.value || "").trim() || "09:00",
      catch_up_policy: String(catchUpEl.value || "run_on_startup"),
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

  if (!runDateEl.value) {
    runDateEl.value = todayDateString();
  }
  if (!runTimeEl.value) {
    runTimeEl.value = "09:00";
  }

  refreshState();
})();
