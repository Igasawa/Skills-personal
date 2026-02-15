(function () {
  // UI copy is centralized in this file.
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const form = document.getElementById("run-form");
  const logEl = document.getElementById("run-log");
  const errorBox = document.getElementById("error-box");
  const stopButton = document.getElementById("stop-run");
  const wizardNext = document.getElementById("wizard-next");
  const latestRunDotEl = document.querySelector("[data-latest-run-dot]");
  const latestRunStatusEl = document.querySelector("[data-latest-run-status]");
  const latestRunTimeEl = document.querySelector("[data-latest-run-time]");
  const latestRunIdEl = document.querySelector("[data-latest-run-id]");
  const latestRunYmEl = document.querySelector("[data-latest-run-ym]");
  const latestRunLinkEl = document.querySelector("[data-latest-run-link]");
  const logRunIdEl = document.querySelector("[data-log-run-id]");
  const logRunStatusEl = document.querySelector("[data-log-run-status]");

  const runStatusById = {};
  let awaitingRunFinalization = false;
  let stepRetryTimer = null;
  let activeLogRunId = "";
  let stepRefreshInFlight = false;
  let stepRefreshStartedAt = 0;
  let stepFocusTimer = null;
  let autoReloadScheduled = false;
  const REQUEST_TIMEOUT_MS = 12000;
  const STEP_REFRESH_STALE_MS = 15000;
  const archiveStateOverrides = Object.create(null);

  const monthCloseChecklistKeys = ["expense_submission", "document_printout", "mf_accounting_link"];
  const YM_STORAGE_KEY = "mfcloud.dashboard.selectedYm";
  const YM_PATTERN = /^(\d{4})-(\d{2})$/;

  function normalizeYm(yearValue, monthValue) {
    const year = Number.parseInt(String(yearValue ?? "").trim(), 10);
    const month = Number.parseInt(String(monthValue ?? "").trim(), 10);
    if (!Number.isInteger(year) || year < 1) return "";
    if (!Number.isInteger(month) || month < 1 || month > 12) return "";
    return `${year.toString().padStart(4, "0")}-${String(month).padStart(2, "0")}`;
  }

  function parseYm(ymValue) {
    const text = String(ymValue || "").trim();
    const match = text.match(YM_PATTERN);
    if (!match) return null;
    const year = Number.parseInt(match[1], 10);
    const month = Number.parseInt(match[2], 10);
    if (!Number.isInteger(year) || year < 1) return null;
    if (!Number.isInteger(month) || month < 1 || month > 12) return null;
    return { year, month, ym: `${year.toString().padStart(4, "0")}-${String(month).padStart(2, "0")}` };
  }

  function readYmFromQueryString() {
    if (typeof window === "undefined") return "";
    try {
      const params = new URLSearchParams(window.location.search || "");
      return normalizeYm(params.get("year"), params.get("month"));
    } catch {
      return "";
    }
  }

  function readYmFromLocalStorage() {
    if (typeof window === "undefined" || !window.localStorage) return "";
    try {
      const raw = window.localStorage.getItem(YM_STORAGE_KEY);
      const parsed = parseYm(raw);
      return parsed ? parsed.ym : "";
    } catch {
      return "";
    }
  }

  function persistYmSelection(ymValue) {
    const parsed = parseYm(ymValue);
    if (!parsed || typeof window === "undefined") return;
    try {
      if (window.localStorage) {
        window.localStorage.setItem(YM_STORAGE_KEY, parsed.ym);
      }
    } catch {
      // Best-effort only.
    }
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("year", String(parsed.year));
      url.searchParams.set("month", String(parsed.month));
      const nextUrl = `${url.pathname}${url.search}${url.hash}`;
      window.history.replaceState(window.history.state, "", nextUrl);
    } catch {
      // Best-effort only.
    }
  }

  function restoreYmSelection() {
    if (!form) return;
    const queryYm = readYmFromQueryString();
    const savedYm = queryYm || readYmFromLocalStorage();
    if (savedYm) setYmToForm(savedYm);
    persistYmSelection(getYmFromForm());
  }

  function normalizeChecklistState(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const normalized = {};
    monthCloseChecklistKeys.forEach((key) => {
      normalized[key] = source[key] === true;
    });
    return normalized;
  }

  // Month Close Checklist state
  let checklistState = normalizeChecklistState({});

  function isChecklistComplete() {
    return monthCloseChecklistKeys.every((key) => checklistState[key] === true);
  }

  function formatDateTimeInJst(dateValue) {
    const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("sv-SE", {
      timeZone: "Asia/Tokyo",
      hour12: false,
    });
  }

  function nowIsoLikeInJst() {
    const text = formatDateTimeInJst(new Date());
    return text ? text.replace(" ", "T") : "";
  }

  async function apiGetJson(url) {
    const sep = url.includes("?") ? "&" : "?";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await fetch(`${url}${sep}_=${Date.now()}`, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  function showError(message) {
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }

  function clearError() {
    if (!errorBox) return;
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
  }

  function scheduleStepSync() {
    refreshSteps({ force: true });
    [800, 2000, 4500, 9000].forEach((delayMs) => {
      setTimeout(() => {
        refreshSteps({ force: true });
      }, delayMs);
    });
  }

  async function fetchStatus(runId) {
    return apiGetJson(`/api/runs/${runId}`);
  }

  function isStepReflected(data, mode) {
    const normalizedMode = String(mode || "").trim();
    if (!normalizedMode) return true;
    if (!data || typeof data !== "object") return false;
    if (String(data.running_mode || "").trim()) return false;
    if (normalizedMode === "preflight") return Boolean(data.preflight?.done);
    if (normalizedMode === "preflight_mf") return Boolean(data.preflight?.done);
    if (normalizedMode === "amazon_download") return Boolean(data.amazon?.downloaded);
    if (normalizedMode === "rakuten_download") return Boolean(data.rakuten?.downloaded);
    if (normalizedMode === "amazon_print") return Boolean(data.amazon?.confirmed && data.amazon?.printed);
    if (normalizedMode === "rakuten_print") return Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    if (normalizedMode === "provider_ingest") {
      return Boolean(data.providers?.step_done);
    }
    if (normalizedMode === "mf_reconcile") return Boolean(data.mf?.step_done ?? data.mf?.reconciled);
    return true;
  }

  async function syncAfterRunCompletion(expectedMode) {
    const delays = [0, 500, 1300, 2600, 5000, 9000];
    for (const delayMs of delays) {
      if (delayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
      const data = await refreshSteps({ force: true });
      if (isStepReflected(data, expectedMode)) return true;
    }
    return false;
  }

  function startLogPolling(runId) {
    activeLogRunId = String(runId || "").trim();
    clearInterval(window.__logTimer);
    if (!activeLogRunId) return;
    window.__logTimer = setInterval(() => {
      if (!activeLogRunId) return;
      refreshLog(activeLogRunId);
    }, 2000);
  }

  function stopLogPolling(runId) {
    const target = String(runId || "").trim();
    if (target && activeLogRunId && target !== activeLogRunId) return;
    clearInterval(window.__logTimer);
    activeLogRunId = "";
  }

  function normalizeStatusForDot(statusRaw) {
    const status = String(statusRaw || "").trim().toLowerCase();
    if (!status) return "";
    if (status === "running" || status === "started") return "running";
    if (status === "success" || status === "ok") return "success";
    if (status === "failed" || status === "error" || status === "cancelled") return "failed";
    return "";
  }

  function toYmText(params) {
    if (!params || typeof params !== "object") return "";
    const year = Number.parseInt(params.year, 10);
    const month = Number.parseInt(params.month, 10);
    if (!Number.isInteger(year) || !Number.isInteger(month) || month < 1 || month > 12) return "";
    return `${year}-${String(month).padStart(2, "0")}`;
  }

  function updateRunSummary(meta) {
    if (!meta || typeof meta !== "object") return;
    const runId = String(meta.run_id || "").trim();
    const statusRaw = String(meta.status || "").trim();
    const startedAt = String(meta.started_at || "").trim();
    const ymText = toYmText(meta.params);

    if (latestRunDotEl) {
      latestRunDotEl.classList.remove("success", "failed", "running");
      const dotClass = normalizeStatusForDot(statusRaw);
      if (dotClass) latestRunDotEl.classList.add(dotClass);
    }
    if (latestRunStatusEl && statusRaw) latestRunStatusEl.textContent = statusRaw;
    if (latestRunTimeEl && startedAt) latestRunTimeEl.textContent = startedAt;
    if (latestRunIdEl && runId) latestRunIdEl.textContent = runId;
    if (latestRunYmEl && ymText) latestRunYmEl.textContent = ymText;
    if (latestRunLinkEl && ymText) {
      latestRunLinkEl.href = `/runs/${ymText}`;
      latestRunLinkEl.classList.remove("disabled");
      latestRunLinkEl.removeAttribute("aria-disabled");
      latestRunLinkEl.removeAttribute("tabindex");
    }

    // 繧ｻ繧ｯ繧ｷ繝ｧ繝ｳ蜈ｨ菴薙・繧ｹ繝・・繧ｿ繧ｹ繧ｯ繝ｩ繧ｹ繧呈峩譁ｰ
    const section = document.querySelector("[data-latest-run-section]");
    if (section) {
      section.classList.remove("success", "failed", "running");
      const dotClass = normalizeStatusForDot(statusRaw);
      if (dotClass) section.classList.add(dotClass);
    }

    if (logRunIdEl && runId) logRunIdEl.textContent = `Run: ${runId}`;
    if (logRunStatusEl && statusRaw) logRunStatusEl.textContent = statusRaw;

    if (stopButton) {
      if (runId) stopButton.dataset.runId = runId;
      stopButton.disabled = statusRaw !== "running";
    }
  }

  async function refreshLog(runId) {
    if (!runId) return;
    if (activeLogRunId && String(runId) !== activeLogRunId) return;
    const data = await fetchStatus(runId);
    if (!data) return;
    updateRunSummary(data.run);

    if (logEl) logEl.textContent = data.log_tail || "";

    const status = String(data.run?.status || "");
    const previousStatus = runStatusById[runId];
    if (status && previousStatus && previousStatus !== status) {
      if (status === "failed") {
        showToast("螳溯｡後↓螟ｱ謨励＠縺ｾ縺励◆縲ゅΟ繧ｰ繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・, "error");
      } else if (status === "success") {
        showToast("螳溯｡後′螳御ｺ・＠縺ｾ縺励◆縲・, "success");
      }
    }
    if (status) {
      runStatusById[runId] = status;
    }

    if (status === "failed") {
      showError("螳溯｡後↓螟ｱ謨励＠縺ｾ縺励◆縲ゅΟ繧ｰ繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・);
    }

    if (status && status !== "running") {
      const shouldAutoReload = awaitingRunFinalization && status === "success" && !autoReloadScheduled;
      awaitingRunFinalization = false;
      stopLogPolling(runId);
      scheduleStepSync();
      const finishedMode = String(data.run?.params?.mode || "");
      syncAfterRunCompletion(finishedMode)
        .catch(() => {})
        .finally(() => {
          if (!shouldAutoReload) return;
          autoReloadScheduled = true;
          setTimeout(() => {
            window.location.reload();
          }, 1200);
        });
    }
  }

  function buildPayload(mode) {
    if (!form) return null;
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    const mfcloudEl = form.querySelector("[name=mfcloud_url]");
    const notesEl = form.querySelector("[name=notes]");
    const rakutenOrdersEl = form.querySelector("[name=rakuten_orders_url]");
    return {
      year: Number(yearEl?.value || 0),
      month: Number(monthEl?.value || 0),
      mfcloud_url: (mfcloudEl?.value || "").trim(),
      notes: (notesEl?.value || "").trim(),
      rakuten_orders_url: (rakutenOrdersEl?.value || "").trim(),
      auth_handoff: true,
      auto_receipt_name: true,
      mode,
    };
  }

  async function startRun(mode) {
    const payload = buildPayload(mode);
    if (!payload) return;

    clearError();
    showToast("螳溯｡後ｒ髢句ｧ九＠縺ｦ縺・∪縺・..", "success");

    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const message = toFriendlyMessage(data.detail);
        showError(message);
        showToast(message, "error");
        return;
      }

      const data = await res.json();
      if (logEl) {
        logEl.dataset.runId = data.run_id;
        logEl.textContent = "螳溯｡後ｒ髢句ｧ九＠縺ｾ縺励◆縲ゅΟ繧ｰ繧呈峩譁ｰ荳ｭ...";
      }

      awaitingRunFinalization = true;
      updateRunSummary({
        run_id: data.run_id,
        status: "running",
        started_at: new Date().toLocaleString("ja-JP", { hour12: false }),
        params: { year: payload.year, month: payload.month },
      });
      runStatusById[data.run_id] = "running";
      showToast("螳溯｡後ｒ髢句ｧ九＠縺ｾ縺励◆縲・, "success");

      startLogPolling(data.run_id);
      refreshLog(data.run_id);
      scheduleStepSync();
    } catch {
      awaitingRunFinalization = false;
      const message = "螳溯｡碁幕蟋九↓螟ｱ謨励＠縺ｾ縺励◆縲ょ・隧ｦ陦後＠縺ｦ縺上□縺輔＞縲・;
      showError(message);
      showToast(message, "error");
    }
  }

  function nextYm(ym) {
    const parsed = parseYm(ym);
    if (!parsed) return "";
    const year = parsed.year;
    const month = parsed.month;
    if (month >= 12) return `${year + 1}-01`;
    return `${year}-${String(month + 1).padStart(2, "0")}`;
  }

  function setYmToForm(ym) {
    const parsed = parseYm(ym);
    if (!parsed || !form) return;
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    if (yearEl) yearEl.value = String(parsed.year);
    if (monthEl) monthEl.value = String(parsed.month);
    persistYmSelection(parsed.ym);
  }

  function prependArchiveHistoryRow(entry) {
    if (!entry || typeof entry !== "object") return;
    const list = document.querySelector("[data-archive-history-list]");
    if (!(list instanceof HTMLElement)) return;
    const empty = list.querySelector("[data-archive-history-empty]");
    if (empty) empty.remove();

    const ym = String(entry.ym || "").trim();
    const ts = String(entry.ts || "").trim();
    const actionLabel = String(entry.action_label || "").trim() || "繧｢繝ｼ繧ｫ繧､繝・;
    const href = String(entry.archive_url || "").trim() || (ym ? `/runs/${ym}/archived-receipts` : "#");

    const item = document.createElement("li");
    item.className = "archive-history-item";
    const text = document.createElement("span");
    text.className = "muted";
    text.textContent = `${ts || "-"} / ${ym || "-"} / ${actionLabel}`;
    const link = document.createElement("a");
    link.className = "secondary";
    link.href = href;
    link.textContent = "繧｢繝ｼ繧ｫ繧､繝悶ｒ髢九￥";
    item.appendChild(text);
    item.appendChild(link);
    list.prepend(item);
  }

  async function runArchiveAction(action, buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }
    const normalizedAction = String(action || "").trim();
    if (!normalizedAction) return;

    clearError();
    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    const isMonthClose = normalizedAction === "month_close";
    showToast(isMonthClose ? "譛域ｬ｡繧ｯ繝ｭ繝ｼ繧ｺ繧貞ｮ溯｡後＠縺ｦ縺・∪縺・.." : "繧｢繝ｼ繧ｫ繧､繝悶ｒ菴懈・縺励※縺・∪縺・..", "success");

    try {
      const endpoint = isMonthClose ? `/api/month-close/${ym}` : `/api/archive/${ym}`;
      const res = await fetch(endpoint, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || (isMonthClose ? "譛域ｬ｡繧ｯ繝ｭ繝ｼ繧ｺ縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・ : "繧｢繝ｼ繧ｫ繧､繝紋ｽ懈・縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・));
        showError(message);
        showToast(message, "error");
        return;
      }
      const archivedTo = String(data.archived_to || "").trim();
      archiveStateOverrides[ym] = {
        created: true,
        created_at: nowIsoLikeInJst(),
        archived_to: archivedTo || null,
        include_pdfs: Boolean(data.include_pdfs),
        include_debug: Boolean(data.include_debug),
        cleanup: Boolean(data.cleanup),
      };
      const cleanupRemoved = Number(data.cleanup_removed || 0);
      const cleanupSuffix = Number.isFinite(cleanupRemoved) ? ` / 繧ｯ繝ｪ繝ｼ繝ｳ繧｢繝・・ ${cleanupRemoved}莉ｶ` : "";
      const baseMessage = isMonthClose ? "譛域ｬ｡繧ｯ繝ｭ繝ｼ繧ｺ縺悟ｮ御ｺ・＠縺ｾ縺励◆" : "繧｢繝ｼ繧ｫ繧､繝悶ｒ菴懈・縺励∪縺励◆";
      let message = archivedTo ? `${baseMessage}: ${archivedTo}${cleanupSuffix}` : `${baseMessage}縲・{cleanupSuffix}`;
      if (isMonthClose) {
        const next = nextYm(ym);
        if (next) {
          setYmToForm(next);
          if (window.__stepState) window.__stepState = null;
          message += ` / 繧ｦ繧｣繧ｶ繝ｼ繝峨ｒ ${next} 縺ｫ蛻・ｊ譖ｿ縺医∪縺励◆縲Ａ;
        }
      }
      prependArchiveHistoryRow(data.history_entry || null);
      showToast(message, "success");
    } catch {
      const message = normalizedAction === "month_close" ? "譛域ｬ｡繧ｯ繝ｭ繝ｼ繧ｺ縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・ : "繧｢繝ｼ繧ｫ繧､繝紋ｽ懈・縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) {
        delete buttonEl.dataset.busy;
      }
      refreshSteps({ force: true });
    }
  }

  async function archiveOutputs(buttonEl) {
    return runArchiveAction("archive_outputs", buttonEl);
  }

  async function monthClose(buttonEl) {
    return runArchiveAction("month_close", buttonEl);
  }

  async function openManualInbox(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    try {
      const res = await fetch(`/api/folders/${ym}/manual-inbox`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "蜈ｱ騾壹ヵ繧ｩ繝ｫ繝繧帝幕縺代∪縺帙ｓ縺ｧ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath ? `蜈ｱ騾壹ヵ繧ｩ繝ｫ繝繧帝幕縺阪∪縺励◆: ${openedPath}` : "蜈ｱ騾壹ヵ繧ｩ繝ｫ繝繧帝幕縺阪∪縺励◆縲・;
      showToast(message, "success");
    } catch {
      const message = "蜈ｱ騾壹ヵ繧ｩ繝ｫ繝繧帝幕縺代∪縺帙ｓ縺ｧ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function importManualReceipts(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("謇句虚鬆伜庶譖ｸ縺ｮ蜿悶ｊ霎ｼ縺ｿ繧帝幕蟋九＠縺ｾ縺・..", "success");
    try {
      const res = await fetch(`/api/manual/${ym}/import`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "鬆伜庶譖ｸ蜿悶ｊ霎ｼ縺ｿ縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.found_pdfs ?? 0), 10) || 0;
      const imported = Number.parseInt(String(data.imported ?? 0), 10) || 0;
      const skipped = Number.parseInt(String(data.skipped_duplicates ?? 0), 10) || 0;
      const failed = Number.parseInt(String(data.failed ?? 0), 10) || 0;
      const message = `謇句虚鬆伜庶譖ｸ蜿悶ｊ霎ｼ縺ｿ: 逋ｺ隕・${found}莉ｶ / 蜿冶ｾｼ ${imported}莉ｶ / 驥崎､・${skipped}莉ｶ / 螟ｱ謨・${failed}莉ｶ`;
      showToast(message, failed > 0 ? "error" : "success");
      if (failed > 0) {
        showError(message);
      }
    } catch {
      const message = "鬆伜庶譖ｸ蜿悶ｊ霎ｼ縺ｿ縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function openMfBulkInbox(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    try {
      const res = await fetch(`/api/folders/${ym}/mf-bulk-inbox`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝臥畑繝輔か繝ｫ繝繧帝幕縺代∪縺帙ｓ縺ｧ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath
        ? `MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝臥畑繝輔か繝ｫ繝繧帝幕縺阪∪縺励◆: ${openedPath}`
        : "MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝臥畑繝輔か繝ｫ繝繧帝幕縺阪∪縺励◆縲・;
      showToast(message, "success");
    } catch {
      const message = "MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝臥畑繝輔か繝ｫ繝繧帝幕縺代∪縺帙ｓ縺ｧ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function runMfBulkUpload(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝峨ｒ髢句ｧ九＠縺ｾ縺・..", "success");
    try {
      const res = await fetch(`/api/mf-bulk-upload/${ym}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝峨↓螟ｱ謨励＠縺ｾ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.files_found ?? 0), 10) || 0;
      const submitted = Number.parseInt(String(data.submitted_count ?? 0), 10) || 0;
      const queued = Number.parseInt(String(data.queued_count ?? 0), 10) || 0;
      const readCount = Number.parseInt(String(data.read_count ?? 0), 10) || 0;
      const archivedDir = String(data.archived_dir || "").trim();
      const details = archivedDir ? ` / 菫晉ｮ｡: ${archivedDir}` : "";
      const message = `MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝・ 逋ｺ隕・${found}莉ｶ / 隱ｭ霎ｼ ${readCount}莉ｶ / 繧ｭ繝･繝ｼ ${queued}莉ｶ / 騾∽ｿ｡ ${submitted}莉ｶ${details}`;
      showToast(message, "success");
    } catch {
      const message = "MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝峨↓螟ｱ謨励＠縺ｾ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function openMfCsvInbox(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    try {
      const res = await fetch(`/api/folders/${ym}/mf-csv-inbox`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "莠､騾夊ｲｻCSV繧､繝ｳ繝昴・繝育畑繝輔か繝ｫ繝繧帝幕縺代∪縺帙ｓ縺ｧ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath
        ? `莠､騾夊ｲｻCSV繧､繝ｳ繝昴・繝育畑繝輔か繝ｫ繝繧帝幕縺阪∪縺励◆: ${openedPath}`
        : "莠､騾夊ｲｻCSV繧､繝ｳ繝昴・繝育畑繝輔か繝ｫ繝繧帝幕縺阪∪縺励◆縲・;
      showToast(message, "success");
    } catch {
      const message = "莠､騾夊ｲｻCSV繧､繝ｳ繝昴・繝育畑繝輔か繝ｫ繝繧帝幕縺代∪縺帙ｓ縺ｧ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function runMfCsvImport(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("莠､騾夊ｲｻCSV繧､繝ｳ繝昴・繝医ｒ髢句ｧ九＠縺ｾ縺・..", "success");
    try {
      const res = await fetch(`/api/mf-csv-import/${ym}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "莠､騾夊ｲｻCSV繧､繝ｳ繝昴・繝医↓螟ｱ謨励＠縺ｾ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.files_found ?? 0), 10) || 0;
      const submitted = Number.parseInt(String(data.submitted_count ?? 0), 10) || 0;
      const queued = Number.parseInt(String(data.queued_count ?? 0), 10) || 0;
      const archivedDir = String(data.archived_dir || "").trim();
      const details = archivedDir ? ` / 菫晉ｮ｡: ${archivedDir}` : "";
      const message = `莠､騾夊ｲｻCSV繧､繝ｳ繝昴・繝・ 逋ｺ隕・${found}莉ｶ / 繧ｭ繝･繝ｼ ${queued}莉ｶ / 騾∽ｿ｡ ${submitted}莉ｶ${details}`;
      showToast(message, "success");
    } catch {
      const message = "莠､騾夊ｲｻCSV繧､繝ｳ繝昴・繝医↓螟ｱ謨励＠縺ｾ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  function runManualAction(action, buttonEl) {
    if (action === "open_inbox") {
      openManualInbox(buttonEl);
      return;
    }
    if (action === "import_receipts") {
      importManualReceipts(buttonEl);
      return;
    }
    if (action === "open_mf_bulk_inbox") {
      openMfBulkInbox(buttonEl);
      return;
    }
    if (action === "run_mf_bulk_upload") {
      runMfBulkUpload(buttonEl);
      return;
    }
    if (action === "open_mf_csv_inbox") {
      openMfCsvInbox(buttonEl);
      return;
    }
    if (action === "run_mf_csv_import") {
      runMfCsvImport(buttonEl);
    }
  }

  function providerLabel(provider) {
    const key = String(provider || "").trim().toLowerCase();
    if (key === "chatgpt") return "ChatGPT";
    if (key === "claude") return "Claude";
    if (key === "gamma") return "Gamma";
    if (key === "aquavoice") return "Aqua Voice";
    return key || "provider";
  }

  async function openProviderInbox(provider, buttonEl) {
    const ym = getYmFromForm();
    const normalizedProvider = String(provider || "").trim().toLowerCase();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }
    if (!normalizedProvider) {
      showToast("蟇ｾ雎｡繧ｵ繝ｼ繝薙せ縺梧欠螳壹＆繧後※縺・∪縺帙ｓ縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    try {
      const res = await fetch(`/api/folders/${ym}/provider-inbox/${encodeURIComponent(normalizedProvider)}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "繧ｵ繝ｼ繝薙せ蛻･繝輔か繝ｫ繝繧帝幕縺代∪縺帙ｓ縺ｧ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const label = providerLabel(normalizedProvider);
      const message = openedPath ? `${label}繝輔か繝ｫ繝繧帝幕縺阪∪縺励◆: ${openedPath}` : `${label}繝輔か繝ｫ繝繧帝幕縺阪∪縺励◆縲Ａ;
      showToast(message, "success");
    } catch {
      const message = "繧ｵ繝ｼ繝薙せ蛻･繝輔か繝ｫ繝繧帝幕縺代∪縺帙ｓ縺ｧ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function importProviderReceipts(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("蜈ｱ騾壹ヵ繧ｩ繝ｫ繝縺ｮ鬆伜庶譖ｸ繧貞叙繧願ｾｼ縺ｿ荳ｭ...", "success");
    try {
      const res = await fetch(`/api/providers/${ym}/import`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "蜈ｱ騾壹ヵ繧ｩ繝ｫ繝蜿悶ｊ霎ｼ縺ｿ縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.found_files ?? 0), 10) || 0;
      const imported = Number.parseInt(String(data.imported ?? 0), 10) || 0;
      const skipped = Number.parseInt(String(data.skipped_duplicates ?? 0), 10) || 0;
      const failed = Number.parseInt(String(data.failed ?? 0), 10) || 0;
      const message = `蜈ｱ騾壹ヵ繧ｩ繝ｫ繝蜿悶ｊ霎ｼ縺ｿ: 讀懷・ ${found}莉ｶ / 蜿冶ｾｼ ${imported}莉ｶ / 驥崎､・${skipped}莉ｶ / 螟ｱ謨・${failed}莉ｶ`;
      const manualActionRequired = Boolean(data.manual_action_required) || skipped > 0 || failed > 0;
      if (!manualActionRequired) {
        showToast(message, "success");
        return;
      }

      const details = [message, "繧ｹ繧ｭ繝・・/螟ｱ謨怜・縺ｯMF縺ｸ閾ｪ蜍墓ｷｻ莉倥＆繧後※縺・∪縺帙ｓ縲よ焔蜍墓ｷｻ莉倥＠縺ｦ縺上□縺輔＞縲・];
      let skippedFolderPath = String(data.skipped_dir || "").trim();
      if (skipped > 0) {
        const openSkippedRes = await fetch(`/api/folders/${ym}/provider-skipped/latest`, { method: "POST" });
        const openSkippedData = await openSkippedRes.json().catch(() => ({}));
        if (openSkippedRes.ok) {
          const opened = String(openSkippedData.path || "").trim();
          if (opened) skippedFolderPath = opened;
        }
      }
      if (skippedFolderPath) {
        details.push(`譛ｪ豺ｻ莉倅ｸ隕ｧ繝輔か繝ｫ繝: ${skippedFolderPath}`);
      }
      const skippedFiles = Array.isArray(data.skipped_files)
        ? data.skipped_files.map((value) => String(value || "").trim()).filter((value) => value)
        : [];
      if (skippedFiles.length > 0) {
        const preview = skippedFiles.slice(0, 8);
        const suffix = skippedFiles.length > preview.length ? ` 縺ｻ縺・{skippedFiles.length - preview.length}莉ｶ` : "";
        details.push(`譛ｪ豺ｻ莉倥ヵ繧｡繧､繝ｫ: ${preview.join(", ")}${suffix}`);
      }
      const errorMessage = details.join("\n");
      showError(errorMessage);
      showToast("蜈ｱ騾壹ヵ繧ｩ繝ｫ繝蜿悶ｊ霎ｼ縺ｿ縺ｧ繧ｹ繧ｭ繝・・/螟ｱ謨励′逋ｺ逕溘＠縺ｾ縺励◆縲よ焔蜍墓ｷｻ莉倥′蠢・ｦ√〒縺吶・, "error");
    } catch {
      const message = "蜈ｱ騾壹ヵ繧ｩ繝ｫ繝蜿悶ｊ霎ｼ縺ｿ縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function printProviderReceipts(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("蜈ｱ騾壹ヵ繧ｩ繝ｫ繝蜿冶ｾｼ貂医∩縺ｮPDF繧堤ｵ仙粋縺励※縺・∪縺・..", "success");
    try {
      const res = await fetch(`/api/providers/${ym}/print-run`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "蜈ｱ騾壹ヵ繧ｩ繝ｫ繝荳諡ｬ蜊ｰ蛻ｷ縺ｮ髢句ｧ九↓螟ｱ謨励＠縺ｾ縺励◆縲・);
        showError(message);
        showToast(message, "error");
        return;
      }
      const count = Number.parseInt(String(data.count ?? 0), 10) || 0;
      const message = `蜈ｱ騾壹ヵ繧ｩ繝ｫ繝蜿冶ｾｼ蛻・・邨仙粋PDF繧帝幕縺阪∪縺励◆・亥ｯｾ雎｡ ${Math.max(0, count)} 莉ｶ・峨Ａ;
      showToast(message, "success");
    } catch {
      const message = "蜈ｱ騾壹ヵ繧ｩ繝ｫ繝荳諡ｬ蜊ｰ蛻ｷ縺ｮ髢句ｧ九↓螟ｱ謨励＠縺ｾ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  function runProviderAction(action, provider, buttonEl) {
    if (action === "open_shared_inbox") {
      openManualInbox(buttonEl);
      return;
    }
    if (action === "open_provider_inbox") {
      openProviderInbox(provider, buttonEl);
      return;
    }
    if (action === "import_provider_receipts") {
      importProviderReceipts(buttonEl);
      return;
    }
    if (action === "print_provider_receipts") {
      printProviderReceipts(buttonEl);
      return;
    }
  }

  async function resetStep(stepId, buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ蜈･蜉帙＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }
    const labelByStep = {
      amazon_download: "Amazon繧ｫ繝ｼ繝・/ 蜿門ｾ・,
      amazon_decide_print: "Amazon繧ｫ繝ｼ繝・/ 髯､螟門愛譁ｭ繝ｻ蜊ｰ蛻ｷ・亥ｮ御ｺ・ｨ倬鹸縺ｾ縺ｧ・・,
      rakuten_download: "讌ｽ螟ｩ繧ｫ繝ｼ繝・/ 蜿門ｾ・,
      rakuten_decide_print: "讌ｽ螟ｩ繧ｫ繝ｼ繝・/ 髯､螟門愛譁ｭ繝ｻ蜊ｰ蛻ｷ・亥ｮ御ｺ・ｨ倬鹸縺ｾ縺ｧ・・,
    };
    const label = labelByStep[String(stepId || "")] || String(stepId || "");
    const confirmed = window.confirm(`縲・{label}縲阪ｒ繝ｪ繧ｻ繝・ヨ縺励∪縺吶ょｿ・ｦ√↑繧牙ｮ溯｡御ｸｭ繧ｸ繝ｧ繝悶ｒ蛛懈ｭ｢縺励∪縺吶らｶ夊｡後＠縺ｾ縺吶°・歔);
    if (!confirmed) return;

    if (buttonEl) buttonEl.disabled = true;
    clearError();
    try {
      const res = await fetch(`/api/steps/${ym}/reset/${encodeURIComponent(stepId)}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "Step reset failed.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const cancelledCount = Array.isArray(data.cancelled_runs) ? data.cancelled_runs.length : 0;
      showToast(cancelledCount > 0 ? `繝ｪ繧ｻ繝・ヨ螳御ｺ・ 螳溯｡御ｸｭ繧ｸ繝ｧ繝・${cancelledCount} 莉ｶ繧貞●豁｢縺励∪縺励◆縲Ａ : "繝ｪ繧ｻ繝・ヨ縺悟ｮ御ｺ・＠縺ｾ縺励◆縲・, "success");
      scheduleStepSync();
      if (activeLogRunId) {
        refreshLog(activeLogRunId);
      }
    } catch {
      const message = "繝ｪ繧ｻ繝・ヨ縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) buttonEl.disabled = false;
    }
  }

  function getYmFromForm() {
    if (!form) return "";
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    return normalizeYm(yearEl?.value, monthEl?.value);
  }

  function setStepStatus(id, state) {
    const el = document.querySelector(`[data-step-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (id === "mf_reconcile" && state !== "running") {
      el.textContent = "螳溯｡悟庄";
      el.classList.add("pending");
      return;
    }
    if (state === "done") {
      el.textContent = "螳御ｺ・;
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "螳溯｡御ｸｭ";
      el.classList.add("running");
      return;
    }
    el.textContent = "譛ｪ螳溯｡・;
    el.classList.add("pending");
  }

  function setTaskStatus(id, state) {
    const el = document.querySelector(`[data-task-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (state === "done") {
      el.textContent = "螳御ｺ・;
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "螳溯｡御ｸｭ";
      el.classList.add("running");
      return;
    }
    el.textContent = "譛ｪ螳溯｡・;
    el.classList.add("pending");
  }

  function renderNextStep(message, href, reason = "", linkLabel = "") {
    if (!wizardNext) return;
    wizardNext.innerHTML = "";
    if (!message) {
      wizardNext.classList.add("hidden");
      return;
    }
    wizardNext.classList.remove("hidden");
    const text = document.createElement("span");
    text.textContent = message;
    wizardNext.appendChild(text);
    if (reason) {
      const reasonEl = document.createElement("span");
      reasonEl.className = "muted next-step-reason";
      reasonEl.textContent = reason;
      wizardNext.appendChild(reasonEl);
    }
    if (!href) return;
    const link = document.createElement("a");
    link.href = href;
    link.className = "secondary";
    link.textContent = String(linkLabel || "髢九￥").trim() || "髢九￥";
    if (String(href || "").trim().startsWith("#")) {
      link.href = href;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        navigateToStep(href);
      });
    }
    wizardNext.appendChild(link);
  }

  const FALLBACK_WIZARD_HREF = "#wizard";
  const FALLBACK_GUIDANCE_LIMIT = 8;

  function recordWizardFallback({ type, runningMode = "", nextStep = "", nextStepReason = "", href = "" }) {
    const entry = {
      ts: Date.now(),
      type: String(type || "").trim() || "unknown",
      runningMode: String(runningMode || "").trim(),
      nextStep: String(nextStep || "").trim(),
      nextStepReason: String(nextStepReason || "").trim(),
      href: String(href || FALLBACK_WIZARD_HREF).trim() || FALLBACK_WIZARD_HREF,
    };
    const log = Array.isArray(window.__wizardFallbackLog) ? window.__wizardFallbackLog : [];
    const last = log.length ? log[log.length - 1] : null;
    const shouldAppend =
      !last ||
      last.type !== entry.type ||
      last.runningMode !== entry.runningMode ||
      last.nextStep !== entry.nextStep ||
      last.nextStepReason !== entry.nextStepReason ||
      last.href !== entry.href;
    if (shouldAppend) {
      log.push(entry);
      if (log.length > FALLBACK_GUIDANCE_LIMIT) {
        log.shift();
      }
      window.__wizardFallbackLog = log;
    }
    const wizard = document.getElementById("wizard");
    if (!wizard) return;
    wizard.dataset.nextStepFallbackType = entry.type;
    wizard.dataset.nextStepFallbackStep = entry.nextStep;
    wizard.dataset.nextStepFallbackMode = entry.runningMode;
    wizard.dataset.nextStepFallbackReason = entry.nextStepReason;
    wizard.dataset.nextStepFallbackHref = entry.href;
    wizard.dataset.nextStepFallbackAt = String(entry.ts);
    wizard.dataset.nextStepFallbackCount = String(log.length);
  }

  function navigateToStep(href) {
    if (!href || typeof href !== "string") return;
    const id = href.trim();
    if (!id.startsWith("#")) return;
    const target = document.querySelector(id);
    if (!target) {
      showToast("蟇ｾ雎｡繧ｻ繧ｯ繧ｷ繝ｧ繝ｳ縺瑚ｦ九▽縺九ｊ縺ｾ縺帙ｓ縲・, "warning");
      return;
    }

    if (stepFocusTimer) {
      clearTimeout(stepFocusTimer);
      stepFocusTimer = null;
    }

    target.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    const hadTabIndex = target.hasAttribute("tabindex");
    target.setAttribute("tabindex", "-1");
    const focusTarget =
      target.matches("button, a, input, select, textarea, [tabindex]")
      ? target
      : target.querySelector("button, a, input, select, textarea, [tabindex]");
    const focusable = focusTarget || target;
    if (typeof focusable.focus === "function") {
      try {
        focusable.focus({ preventScroll: true });
      } catch {
        focusable.focus();
      }
    }
    target.classList.add("step-focus");
    stepFocusTimer = setTimeout(() => {
      target.classList.remove("step-focus");
      if (!hadTabIndex) {
        target.removeAttribute("tabindex");
      }
      stepFocusTimer = null;
    }, 1400);
  }

  function inferNextStepFromFlags(data) {
    if (!data || typeof data !== "object") return "done";
    if (!data.preflight?.done) return "preflight";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const amazonPending = Boolean(data.amazon?.downloaded && !amazonDone);
    const rakutenPending = Boolean(data.rakuten?.downloaded && !rakutenDone);
    const providerPendingCount = Number.parseInt(String(data.providers?.pending_total ?? 0), 10);
    const providerPending = Number.isFinite(providerPendingCount) ? providerPendingCount > 0 : false;
    if (amazonPending) return "amazon_decide_print";
    if (rakutenPending) return "rakuten_decide_print";
    if (!data.amazon?.downloaded && !data.rakuten?.downloaded) return "amazon_or_rakuten_download";
    if (!data.amazon?.downloaded) return "amazon_download";
    if (!data.rakuten?.downloaded) return "rakuten_download";
    if (providerPending) return "provider_ingest";
    const mfDone = Boolean(data.mf?.step_done ?? data.mf?.reconciled);
    if (!mfDone && (Boolean(data.mf_bulk_upload?.done || data.mf_csv_import?.done))) return "mf_bulk_upload_task";
    const canReconcile =
      "can_reconcile" in data ? Boolean(data.can_reconcile) : (Boolean(data.amazon?.downloaded || data.rakuten?.downloaded) && !(amazonPending || rakutenPending));
    if (!mfDone && canReconcile) return "mf_reconcile";
    if (!mfDone) return "mf_reconcile";
    return "done";
  }

  const KNOWN_NEXT_STEP_VALUES = new Set([
      "preflight_mf",
      "preflight",
      "amazon_or_rakuten_download",
      "amazon_download",
      "amazon_decide_print",
      "rakuten_download",
      "rakuten_decide_print",
      "amazon_print",
      "rakuten_print",
      "provider_ingest",
      "import_provider_receipts",
      "mf_bulk_upload_task",
      "mf_bulk_upload",
      "mf_csv_import",
      "mf_reconcile",
      "done",
  ]);

  function normalizeNextStepValue(rawValue) {
    return String(rawValue || "").trim().toLowerCase();
  }

  function isKnownNextStep(rawValue) {
    return KNOWN_NEXT_STEP_VALUES.has(normalizeNextStepValue(rawValue));
  }

  function resolveNextStep(data) {
    const apiNextStep = normalizeNextStepValue(data?.next_step);
    if (isKnownNextStep(apiNextStep)) {
      return apiNextStep;
    }
    const inferred = inferNextStepFromFlags(data);
    if (apiNextStep) {
      recordWizardFallback({
        type: "next_step_unknown",
        runningMode: String(data?.running_mode || ""),
        nextStep: apiNextStep,
        nextStepReason: String(data?.next_step_reason || "").trim(),
        href: FALLBACK_WIZARD_HREF,
      });
    }
    return inferred;
  }

  function formatArchiveTimeForDisplay(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const normalized = text.includes("T") ? text : text.replace(" ", "T");
    if (/(Z|[+-]\d{2}:?\d{2})$/.test(normalized)) {
      const jstText = formatDateTimeInJst(normalized);
      if (jstText) return `${jstText} JST`;
    }
    const basicMatch = normalized.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
    if (basicMatch) return `${basicMatch[1]} ${basicMatch[2]} JST`;
    return text;
  }

  function archivePageHref(ym) {
    const value = String(ym || "").trim();
    if (!/^\d{4}-\d{2}$/.test(value)) return "";
    const wizard = document.getElementById("wizard");
    const template = String(wizard?.dataset?.archiveHrefTemplate || "").trim();
    if (template && template.includes("__YM__")) {
      return template.replace("__YM__", encodeURIComponent(value));
    }
    return `/runs/${value}/archived-receipts`;
  }

  function applyArchivePageLink(ym) {
    document.querySelectorAll("[data-archive-page-link]").forEach((link) => {
      if (!(link instanceof HTMLAnchorElement)) return;
      const fallbackHref = String(link.dataset.fallbackHref || link.getAttribute("href") || "").trim();
      const href = archivePageHref(ym) || fallbackHref || "#";
      link.href = href;
      if (href === "#") {
        link.classList.add("disabled");
        link.setAttribute("aria-disabled", "true");
        link.setAttribute("tabindex", "-1");
      } else {
        link.classList.remove("disabled");
        link.removeAttribute("aria-disabled");
        link.removeAttribute("tabindex");
      }
    });
  }

  function computeNextStep(data, ym) {
    const nextStep = resolveNextStep(data);
    const apiNextStep = normalizeNextStepValue(data?.next_step);
    const apiNextStepWasUnknown = apiNextStep && !isKnownNextStep(apiNextStep);
    const nextStepKey = String(nextStep || "").trim();
    const runningMode = String(data?.running_mode || "").trim();
    const nextStepReasonCode = String(data?.next_step_reason || "").trim();
    const nextStepGuidance = {
      preflight: {
        message: "縺ｾ縺壹・蜑肴署譚｡莉ｶ縺ｮ遒ｺ隱阪°繧蛾ｲ繧√※縺上□縺輔＞縲・,
        reason: "繝ｭ繧ｰ繧､繝ｳ迥ｶ諷九→譛域ｬ｡諠・ｱ繧堤｢ｺ隱阪＠縺ｦ縲∝ｮ溯｡悟庄閭ｽ譚｡莉ｶ繧偵◎繧阪∴縺ｾ縺吶・,
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      amazon_or_rakuten_download: {
        message: "縺ｾ縺壹・ Amazon 縺区･ｽ螟ｩ縺ｮ縺・★繧後°縺ｮ鬆伜庶譖ｸ蜿門ｾ励ｒ蜈医↓螳溯｡後＠縺ｦ縺上□縺輔＞縲・,
        reason: "蟆代↑縺上→繧・遉ｾ蛻・・鬆伜庶譖ｸ蜿門ｾ励′蠢・ｦ√〒縺吶よ悴蜿門ｾ励′縺ゅｋ縺ｨ谺｡縺ｮ蜃ｦ逅・↓騾ｲ繧√∪縺帙ｓ縲・,
        linkLabel: "Amazon・乗･ｽ螟ｩ 蜿門ｾ励∈",
      },
      amazon_download: {
        message: "Amazon 縺ｮ鬆伜庶譖ｸ繧貞叙蠕励＠縺ｦ縺上□縺輔＞縲・,
        reason: "Amazon 蛛ｴ縺ｮ蟇ｾ雎｡譛医ョ繝ｼ繧ｿ繧貞叙蠕励＠縺ｦ縲∵ｬ｡縺ｮ髯､螟門愛譁ｭ繝ｻ蜊ｰ蛻ｷ縺ｸ騾ｲ縺ｿ縺ｾ縺吶・,
        linkLabel: "Amazon 蜿門ｾ励∈",
      },
      amazon_decide_print: {
        message: "Amazon 縺ｮ髯､螟冶ｨｭ螳壹・蜊ｰ蛻ｷ蟇ｾ雎｡繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・,
        reason: "髯､螟門ｯｾ雎｡繧堤｢ｺ螳壹＠縺ｦ蜊ｰ蛻ｷ螳御ｺ・∪縺ｧ騾ｲ繧√ｋ縺ｨ迥ｶ諷九′菫晏ｭ倥＆繧後∪縺吶・,
        linkLabel: "Amazon 髯､螟悶・蜊ｰ蛻ｷ縺ｸ",
      },
      amazon_print: {
        message: "Amazon縺ｮ蜊ｰ蛻ｷ螳御ｺ・ｾ・■繧ｹ繝・・繧ｿ繧ｹ繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・,
        reason: "Amazon縺ｮ蜊ｰ蛻ｷ蜃ｦ逅・′螳御ｺ・＠縲∝ｿ・ｦ√↓蠢懊§縺ｦ遒ｺ隱阪・蜿肴丐繧定｡後▲縺ｦ縺上□縺輔＞縲・,
        linkLabel: "Amazon縺ｮ蜊ｰ蛻ｷ繧ｹ繝・・繧ｿ繧ｹ縺ｸ",
      },
      rakuten_download: {
        message: "讌ｽ螟ｩ縺ｮ鬆伜庶譖ｸ繧貞叙蠕励＠縺ｦ縺上□縺輔＞縲・,
        reason: "讌ｽ螟ｩ蛛ｴ縺ｮ蟇ｾ雎｡譛医ョ繝ｼ繧ｿ繧貞叙蠕励＠縺ｦ縲∵ｬ｡縺ｮ髯､螟門愛譁ｭ繝ｻ蜊ｰ蛻ｷ縺ｸ騾ｲ縺ｿ縺ｾ縺吶・,
        linkLabel: "讌ｽ螟ｩ 蜿門ｾ励∈",
      },
      rakuten_print: {
        message: "讌ｽ螟ｩ縺ｮ蜊ｰ蛻ｷ螳御ｺ・ｾ・■繧ｹ繝・・繧ｿ繧ｹ繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・,
        reason: "讌ｽ螟ｩ縺ｮ蜊ｰ蛻ｷ蜃ｦ逅・′螳御ｺ・＠縲∝ｿ・ｦ√↓蠢懊§縺ｦ遒ｺ隱阪・蜿肴丐繧定｡後▲縺ｦ縺上□縺輔＞縲・,
        linkLabel: "讌ｽ螟ｩ縺ｮ蜊ｰ蛻ｷ繧ｹ繝・・繧ｿ繧ｹ縺ｸ",
      },
      rakuten_decide_print: {
        message: "讌ｽ螟ｩ縺ｮ髯､螟冶ｨｭ螳壹・蜊ｰ蛻ｷ蟇ｾ雎｡繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・,
        reason: "髯､螟門ｯｾ雎｡繧堤｢ｺ螳壹＠縺ｦ蜊ｰ蛻ｷ螳御ｺ・∪縺ｧ騾ｲ繧√ｋ縺ｨ迥ｶ諷九′菫晏ｭ倥＆繧後∪縺吶・,
        linkLabel: "讌ｽ螟ｩ 髯､螟悶・蜊ｰ蛻ｷ縺ｸ",
      },
      mf_reconcile: {
        message: "MF騾｣謳ｺ縺ｮ遯∝粋縺帛ｮ溯｡後∈騾ｲ繧√※縺上□縺輔＞縲・,
        reason: "蜿悶ｊ霎ｼ縺ｿ貂医∩繝・・繧ｿ繧樽F縺ｮ荳区嶌縺堺ｽ懈・縺ｸ蜿肴丐縺励∪縺吶・,
        linkLabel: "MF 遯∝粋菴懈･ｭ縺ｸ",
      },
      preflight_mf: {
        message: "MF蜀榊叙蠕励・縺ｿ縺ｮ繧ｹ繝・ャ繝励ｒ螳御ｺ・＠縺ｦ縺上□縺輔＞縲・,
        reason: "MF蜀榊叙蠕怜ｾ後√ム繝・す繝･繝懊・繝峨・譛譁ｰ迥ｶ諷九ｒ遒ｺ隱阪＠縺ｦ谺｡縺ｮ菴懈･ｭ縺ｫ騾ｲ繧薙〒縺上□縺輔＞縲・,
        linkLabel: "MF蜀榊叙蠕励ｒ遒ｺ隱・,
      },
      mf_bulk_upload_task: {
        message: "Step 4: MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝画焔鬆・′縺ゅｊ縺ｾ縺吶・,
        reason: "MF蜷代￠縺ｮ謇句・蜉帙ヵ繧｡繧､繝ｫ縺檎畑諢上〒縺阪※縺・ｋ蝣ｴ蜷医∝叙繧願ｾｼ縺ｿ繧貞ｮ溯｡後＠縺ｦ縺上□縺輔＞縲・,
        linkLabel: "MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝峨ｒ髢九￥",
      },
      import_provider_receipts: {
        message: "Provider蜿悶ｊ霎ｼ縺ｿ繧ｹ繝・ャ繝励ｒ螳溯｡後＠縺ｦ縺上□縺輔＞縲・,
        reason: "螟夜Κ繝吶Φ繝繝ｼ縺ｮ譛ｪ蜃ｦ逅・SV繧樽F遯∝粋蜑阪↓蜿悶ｊ霎ｼ繧薙〒蜿肴丐縺励※縺上□縺輔＞縲・,
        linkLabel: "Provider蜿悶ｊ霎ｼ縺ｿ縺ｸ騾ｲ繧",
      },
      mf_bulk_upload: {
        message: "MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝峨ｒ螳溯｡後＠縺ｦ縺上□縺輔＞縲・,
        reason: "MF縺ｮ繧､繝ｳ繝昴・繝育判髱｢繧帝幕縺・※縲∝ｯｾ雎｡譛医・荳区嶌縺榊ｯｾ雎｡繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・,
        linkLabel: "MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝峨ｒ髢九￥",
      },
      mf_csv_import: {
        message: "MF CSV繧､繝ｳ繝昴・繝医ｒ螳溯｡後＠縺ｦ縺上□縺輔＞縲・,
        reason: "CSV繧樽F蠖｢蠑上∈謠・∴縺溘≧縺医〒蜿悶ｊ霎ｼ縺ｿ繧貞ｮ溯｡後＠縺ｦ縺上□縺輔＞縲・,
        linkLabel: "MF CSV繧､繝ｳ繝昴・繝医ｒ髢九￥",
      },
      done: {
        message: "縺吶∋縺ｦ螳御ｺ・＠縺ｾ縺励◆縲よ怦谺｡繧｢繝ｼ繧ｫ繧､繝悶ｒ螳溯｡後〒縺阪∪縺吶・,
        reason: "譛蠕後↓譛域ｬ｡繧ｯ繝ｭ繝ｼ繧ｺ繧・い繝ｼ繧ｫ繧､繝悶ｒ螳溯｡後＠縺ｦ縲∵ｬ｡譛磯°逕ｨ縺ｫ蛯吶∴縺ｾ縺吶・,
        linkLabel: "譛域ｬ｡繧ｯ繝ｭ繝ｼ繧ｺ縺ｸ",
      },
      fallback: {
        message: "蜃ｦ逅・・蜿門ｾ励↓譎る俣縺後°縺九▲縺ｦ縺・∪縺吶よ峩譁ｰ繧貞ｾ・▲縺ｦ縺上□縺輔＞縲・,
        reason: "繝舌ャ繧ｯ繧ｨ繝ｳ繝峨°繧画怙譁ｰ迥ｶ諷九ｒ蜿肴丐縺吶ｋ縺ｾ縺ｧ謨ｰ遘貞ｾ・▲縺ｦ蜀榊叙蠕励＠縺ｦ縺上□縺輔＞縲・,
      },
    };

    const runningModeGuidance = {
      preflight: {
        message: "貅門ｙ蜃ｦ逅・ｒ螳溯｡御ｸｭ縺ｧ縺吶・,
        reason: "蜃ｦ逅・′螳御ｺ・☆繧九∪縺ｧ蠕・ｩ溘＠縺ｦ縺上□縺輔＞縲ょｮ御ｺ・ｾ後↓谺｡縺ｮ謫堺ｽ懊′閾ｪ蜍輔〒譖ｴ譁ｰ縺輔ｌ縺ｾ縺吶・,
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      preflight_mf: {
        message: "MF蜀榊叙蠕励ｒ螳溯｡御ｸｭ縺ｧ縺吶・,
        reason: "MF蜀榊叙蠕怜・逅・ｒ螳御ｺ・☆繧九∪縺ｧ縲・ｲ陦悟ｮ御ｺ・ｾ後・迥ｶ諷区峩譁ｰ繧貞ｾ・▲縺ｦ縺上□縺輔＞縲・,
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      amazon_download: {
        message: "Amazon 鬆伜庶譖ｸ蜿門ｾ励ｒ螳溯｡御ｸｭ縺ｧ縺吶・,
        reason: "蜿門ｾ励′螳御ｺ・☆繧九→谺｡縺ｮ蟾･遞九∈騾ｲ繧√ｋ迥ｶ諷九↓縺ｪ繧翫∪縺吶ょｮ御ｺ・∪縺ｧ縺雁ｾ・■縺上□縺輔＞縲・,
        linkLabel: "Amazon 蜿門ｾ鈴ｲ陦檎憾豕√∈",
      },
      amazon_print: {
        message: "Amazon 蜊ｰ蛻ｷ蜃ｦ逅・ｒ螳溯｡御ｸｭ縺ｧ縺吶・,
        reason: "髯､螟悶・蜊ｰ蛻ｷ縺ｮ騾ｲ陦御ｸｭ縺ｧ縺吶ょｮ御ｺ・ｾ後↓迥ｶ諷九′蜿肴丐縺輔ｌ縲∵ｬ｡縺ｮ譯亥・縺ｸ騾ｲ縺ｿ縺ｾ縺吶・,
        linkLabel: "Amazon 蜊ｰ蛻ｷ迥ｶ豕√∈",
      },
      rakuten_download: {
        message: "讌ｽ螟ｩ鬆伜庶譖ｸ蜿門ｾ励ｒ螳溯｡御ｸｭ縺ｧ縺吶・,
        reason: "蜿門ｾ励′螳御ｺ・☆繧九→谺｡縺ｮ蟾･遞九∈騾ｲ繧√ｋ迥ｶ諷九↓縺ｪ繧翫∪縺吶ょｮ御ｺ・∪縺ｧ縺雁ｾ・■縺上□縺輔＞縲・,
        linkLabel: "讌ｽ螟ｩ 蜿門ｾ鈴ｲ陦檎憾豕√∈",
      },
      rakuten_print: {
        message: "讌ｽ螟ｩ 蜊ｰ蛻ｷ蜃ｦ逅・ｒ螳溯｡御ｸｭ縺ｧ縺吶・,
        reason: "髯､螟悶・蜊ｰ蛻ｷ縺ｮ騾ｲ陦御ｸｭ縺ｧ縺吶ょｮ御ｺ・ｾ後↓迥ｶ諷九′蜿肴丐縺輔ｌ縲∵ｬ｡縺ｮ譯亥・縺ｸ騾ｲ縺ｿ縺ｾ縺吶・,
        linkLabel: "讌ｽ螟ｩ 蜊ｰ蛻ｷ迥ｶ豕√∈",
      },
      mf_reconcile: {
        message: "MF遯∝粋縺帙ｒ螳溯｡御ｸｭ縺ｧ縺吶・,
        reason: "遯∝粋縺帛ｮ御ｺ・∪縺ｧ證ｫ縺上♀蠕・■縺上□縺輔＞縲ょｮ御ｺ・ｾ後↓荳区嶌縺阪・菴懈・迥ｶ豕√′譖ｴ譁ｰ縺輔ｌ縺ｾ縺吶・,
        linkLabel: "MF遯∝粋迥ｶ豕√∈",
      },
      provider_ingest: {
        message: "Provider receipt intake is running.",
        reason: "Provider files are being inspected and applied to the workflow. Please wait for completion before continuing.",
        linkLabel: "Open provider receipt step",
      },
      import_provider_receipts: {
        message: "Provider receipt import is running.",
        reason:
          "The provider import is in progress. If there are issues, review provider folders and retry after completion.",
        linkLabel: "Open provider ingest step",
      },
      mf_bulk_upload: {
        message: "MF bulk upload is running.",
        reason:
          "The MF bulk upload job is running. Verify uploaded files and wait for completion before reconciliation.",
        linkLabel: "Open MF bulk upload step",
      },
      mf_csv_import: {
        message: "MF CSV import is running.",
        reason: "The MF CSV import is running. If needed, check file format and dedupe rules after completion.",
        linkLabel: "Open MF CSV import step",
      },
    };

    const nextStepAnchors = {
      preflight: "#step-preflight",
      preflight_mf: "#step-preflight",
      amazon_or_rakuten_download: "#step-amazon-download",
      amazon_download: "#step-amazon-download",
      amazon_decide_print: "#step-amazon-decide-print",
      rakuten_download: "#step-rakuten-download",
      rakuten_decide_print: "#step-rakuten-decide-print",
      rakuten_print: "#step-rakuten-decide-print",
      amazon_print: "#step-amazon-decide-print",
      provider_ingest: "#step-provider-ingest",
      import_provider_receipts: "#step-provider-ingest",
      mf_bulk_upload_task: "#step-mf-bulk-upload-task",
      mf_bulk_upload: "#step-mf-bulk-upload-task",
      mf_csv_import: "#step-mf-bulk-upload-task",
      mf_reconcile: "#step-mf-reconcile",
      done: "#step-month-close",
    };

    const fallbackHref = FALLBACK_WIZARD_HREF;
    const nextTargetHref = nextStepAnchors[nextStepKey] || fallbackHref;
    const runningTargetHref = nextStepAnchors[runningMode] || nextTargetHref || FALLBACK_WIZARD_HREF;
    if (runningMode) {
      const runningGuidance = runningModeGuidance[runningMode];
      if (runningTargetHref === fallbackHref) {
        recordWizardFallback({
          type: "running_mode_anchor",
          runningMode,
          nextStep: nextStepKey,
          nextStepReason: nextStepReasonCode,
          href: runningTargetHref,
        });
      }
      return {
        message: runningGuidance?.message || `${runningMode} 繧貞ｮ溯｡御ｸｭ縺ｧ縺吶Ａ,
        reason:
          runningGuidance?.reason ||
          "蛻･縺ｮ蜃ｦ逅・′騾ｲ陦御ｸｭ縺ｧ縺吶ょｮ御ｺ・☆繧九∪縺ｧ蠕・ｩ溘＠縺ｦ縺上□縺輔＞縲・,
        href: runningTargetHref,
        linkLabel: runningGuidance?.linkLabel || (runningTargetHref === FALLBACK_WIZARD_HREF ? "謇矩・ｒ遒ｺ隱・ : "騾ｲ謐励ｒ遒ｺ隱・),
      };
    }

    const reasonHint = {
      preflight_required: {
        reason: "貅門ｙ繝輔Ο繝ｼ縺梧悴螳御ｺ・〒縺吶ゅ∪縺壼燕謠占ｨｭ螳壹・螳御ｺ・′蠢・ｦ√〒縺吶・,
      },
      source_download_required: {
        message: "Amazon 縺区･ｽ螟ｩ縺ｮ縺ｩ縺｡繧峨°縺ｮ鬆伜庶譖ｸ蜿門ｾ励ｒ蜈医↓螳溯｡後＠縺ｦ縺上□縺輔＞縲・,
        reason: "蟆代↑縺上→繧・遉ｾ蛻・・蟇ｾ雎｡譛医ョ繝ｼ繧ｿ繧貞叙蠕励＠縺ｦ縺上□縺輔＞縲・,
      },
      amazon_download_required: {
        message: "Amazon 縺ｮ鬆伜庶譖ｸ繧貞叙蠕励＠縺ｦ縺上□縺輔＞縲・,
        reason: "蟇ｾ雎｡譛亥・繧貞叙蠕励☆繧九→谺｡縺ｮ髯､螟悶・蜊ｰ蛻ｷ蟾･遞九∈騾ｲ繧√∪縺吶・,
      },
      rakuten_download_required: {
        message: "讌ｽ螟ｩ縺ｮ鬆伜庶譖ｸ繧貞叙蠕励＠縺ｦ縺上□縺輔＞縲・,
        reason: "蟇ｾ雎｡譛亥・繧貞叙蠕励☆繧九→谺｡縺ｮ髯､螟悶・蜊ｰ蛻ｷ蟾･遞九∈騾ｲ繧√∪縺吶・,
      },
      amazon_print_pending: {
        message: "Amazon 縺ｮ髯､螟冶ｨｭ螳壹・蜊ｰ蛻ｷ蟇ｾ雎｡繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・,
        reason: "髯､螟門ｯｾ雎｡縺ｮ遒ｺ螳壹→蜊ｰ蛻ｷ螳御ｺ・ｒ陦後≧縺ｨ谺｡蟾･遞九∈騾ｲ縺ｿ縺ｾ縺吶・,
      },
      rakuten_print_pending: {
        message: "讌ｽ螟ｩ縺ｮ髯､螟冶ｨｭ螳壹・蜊ｰ蛻ｷ蟇ｾ雎｡繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・,
        reason: "髯､螟門ｯｾ雎｡縺ｮ遒ｺ螳壹→蜊ｰ蛻ｷ螳御ｺ・ｒ陦後≧縺ｨ谺｡蟾･遞九∈騾ｲ縺ｿ縺ｾ縺吶・,
      },
      provider_ingest_pending: {
        message: "螟夜ΚCSV縺ｮ蜿悶ｊ霎ｼ縺ｿ繧貞ｮ溯｡後＠縺ｦ縺上□縺輔＞縲・,
        reason: "Amazon/讌ｽ螟ｩ縺ｧ蜿門ｾ励＠縺阪ｌ縺ｪ縺・・繧貞・騾壹ヵ繧ｩ繝ｫ繝縺九ｉ蜿悶ｊ霎ｼ繧薙〒縺上□縺輔＞縲・,
      },
      mf_reconcile_ready: {
        message: "MF騾｣謳ｺ縺ｮ遯∝粋縺帛ｮ溯｡後∈騾ｲ繧√※縺上□縺輔＞縲・,
        reason: "蜿悶ｊ霎ｼ縺ｿ貂医∩繝・・繧ｿ繧樽F縺ｮ荳区嶌縺堺ｽ懈・縺ｸ蜿肴丐縺吶ｋ貅門ｙ縺梧紛縺・∪縺励◆縲・,
      },
      workflow_complete: {
        message: "縺吶∋縺ｦ螳御ｺ・＠縺ｾ縺励◆縲よ怦谺｡繧｢繝ｼ繧ｫ繧､繝悶ｒ螳溯｡後〒縺阪∪縺吶・,
        reason: "譛邨ら｢ｺ隱阪→縺励※譛域ｬ｡繧ｯ繝ｭ繝ｼ繧ｺ繧・い繝ｼ繧ｫ繧､繝悶〒谺｡譛域ｺ門ｙ縺ｫ騾ｲ繧薙〒縺上□縺輔＞縲・,
      },
    };

    const href = nextTargetHref;
    if (href === fallbackHref) {
      recordWizardFallback({
        type: "next_step_anchor",
        runningMode,
        nextStep: nextStepKey,
        nextStepReason: nextStepReasonCode,
        href,
      });
    }
    const baseGuidance = nextStepGuidance[nextStepKey] || nextStepGuidance.fallback;
    const reasonGuidance = reasonHint[nextStepReasonCode];
    const reasonKnown = Object.prototype.hasOwnProperty.call(reasonHint, nextStepReasonCode);
    const apiFallbackReason = apiNextStepWasUnknown
      ? ` [fallback: next_step "${apiNextStep}" was unknown and inferred from current flags]`
      : "";
    if (nextStepReasonCode && !reasonKnown) {
      recordWizardFallback({
        type: "next_step_reason_unknown",
        runningMode,
        nextStep: nextStepKey,
        nextStepReason: nextStepReasonCode,
        href,
      });
    }
    const guidance = reasonGuidance
      ? {
          ...baseGuidance,
          message: reasonGuidance.message || baseGuidance.message,
          reason: `${reasonGuidance.reason || baseGuidance.reason}${apiFallbackReason}`,
        }
      : {
          ...baseGuidance,
          reason: `${baseGuidance.reason || ""}${apiFallbackReason}`,
        };
    return {
      message: guidance.message,
      reason: guidance.reason,
      href,
      linkLabel: guidance.linkLabel || (href === FALLBACK_WIZARD_HREF ? "謇矩・ｒ遒ｺ隱・ : ""),
    };
  }


  function inferAllowedModes(data) {
    const apiModes = Array.isArray(data?.allowed_run_modes) ? data.allowed_run_modes : [];
    if (apiModes.length > 0) {
      const normalized = [];
      const seen = new Set();
      for (const mode of apiModes) {
        const normalizedMode = String(mode || "").trim();
        if (!normalizedMode || seen.has(normalizedMode)) continue;
        seen.add(normalizedMode);
        normalized.push(normalizedMode);
      }
      return normalized;
    }
    const allowed = ["preflight", "preflight_mf"];
    if (!data.preflight?.done) return allowed;
    allowed.push("amazon_download");
    allowed.push("rakuten_download");
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const amazonPending = Boolean(data.amazon?.downloaded && !amazonDone);
    const rakutenPending = Boolean(data.rakuten?.downloaded && !rakutenDone);
    if (data.amazon?.downloaded) {
      allowed.push("amazon_print");
    }
    if (data.rakuten?.downloaded) {
      allowed.push("rakuten_print");
    }
    const canReconcile =
      "can_reconcile" in data ? Boolean(data.can_reconcile) : Boolean(data.amazon?.downloaded || data.rakuten?.downloaded) && !(amazonPending || rakutenPending);
    if (canReconcile) {
      allowed.push("mf_reconcile");
    }
    return allowed;
  }

  function applyActionAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const allowedModes = inferAllowedModes(data);
    document.querySelectorAll("[data-step-action]").forEach((button) => {
      const mode = String(button.dataset.stepAction || "");
      const allowed = allowedModes.includes(mode);
      const blockedByRunning = Boolean(runningMode);
      const blockedByOrder = !allowed;
      button.disabled = blockedByRunning || blockedByOrder;
      if (blockedByRunning) {
        button.title = "莉悶・謇矩・ｒ螳溯｡御ｸｭ縺ｮ縺溘ａ髢句ｧ九〒縺阪∪縺帙ｓ縲・;
      } else if (blockedByOrder) {
        button.title = "縺ｾ縺縺薙・謇矩・・螳溯｡後〒縺阪∪縺帙ｓ縲・;
      } else {
        button.title = "";
      }
    });
  }

  function applyArchiveAvailability(data) {
    document.querySelectorAll("[data-archive-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const runningMode = String(data.running_mode || "");
      const amazonDownloaded = Boolean(data.amazon?.downloaded);
      const rakutenDownloaded = Boolean(data.rakuten?.downloaded);
      const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
      const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
      const amazonPending = Boolean(amazonDownloaded && !amazonDone);
      const rakutenPending = Boolean(rakutenDownloaded && !rakutenDone);
      const hasDownloadedSource = amazonDownloaded || rakutenDownloaded;
      const canArchive =
        "archive" in data && data.archive && typeof data.archive === "object"
          ? Boolean(data.archive.can_archive)
          : (hasDownloadedSource && !(amazonPending || rakutenPending));
      const allowed = canArchive;
      const blockedByRunning = Boolean(runningMode);
      const action = button.dataset.archiveAction;

      // For month_close button, also check checklist state
      if (action === "month_close") {
        const checklistComplete = isChecklistComplete();
        button.disabled = blockedByRunning || !allowed || !checklistComplete;
        if (blockedByRunning) {
          button.title = "莉悶・謇矩・ｒ螳溯｡御ｸｭ縺ｮ縺溘ａ繧｢繝ｼ繧ｫ繧､繝悶〒縺阪∪縺帙ｓ縲・;
        } else if (!allowed && !checklistComplete) {
          button.title = "Amazon縺ｾ縺溘・讌ｽ螟ｩ縺ｧ縲碁勁螟悶・蜊ｰ蛻ｷ・亥ｮ御ｺ・ｨ倬鹸縺ｾ縺ｧ・峨榊ｮ御ｺ・ｾ後↓螳溯｡後〒縺阪∪縺吶ゅ∪縺溘∵怦谺｡繧ｯ繝ｭ繝ｼ繧ｺ蜑阪・遒ｺ隱埼・岼繧偵☆縺ｹ縺ｦ繝√ぉ繝・け縺吶ｋ蠢・ｦ√′縺ゅｊ縺ｾ縺吶・;
        } else if (!allowed) {
          button.title = "Amazon縺ｾ縺溘・讌ｽ螟ｩ縺ｧ縲碁勁螟悶・蜊ｰ蛻ｷ・亥ｮ御ｺ・ｨ倬鹸縺ｾ縺ｧ・峨榊ｮ御ｺ・ｾ後↓螳溯｡後〒縺阪∪縺吶・;
        } else if (!checklistComplete) {
          button.title = "譛域ｬ｡繧ｯ繝ｭ繝ｼ繧ｺ蜑阪・遒ｺ隱埼・岼繧偵☆縺ｹ縺ｦ繝√ぉ繝・け縺励※縺上□縺輔＞縲・;
        } else {
          button.title = "";
        }
      } else {
        // For archive_outputs button, keep original logic
        button.disabled = blockedByRunning || !allowed;
        if (blockedByRunning) {
          button.title = "莉悶・謇矩・ｒ螳溯｡御ｸｭ縺ｮ縺溘ａ繧｢繝ｼ繧ｫ繧､繝悶〒縺阪∪縺帙ｓ縲・;
        } else if (!allowed) {
          button.title = "Amazon縺ｾ縺溘・讌ｽ螟ｩ縺ｧ縲碁勁螟悶・蜊ｰ蛻ｷ・亥ｮ御ｺ・ｨ倬鹸縺ｾ縺ｧ・峨榊ｮ御ｺ・ｾ後↓螳溯｡後〒縺阪∪縺吶・;
        } else {
          button.title = "";
        }
      }
    });
  }

  function applyManualAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const preflightDone = Boolean(data.preflight?.done);
    document.querySelectorAll("[data-manual-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const blockedByRunning = Boolean(runningMode);
      const action = String(button.dataset.manualAction || "");
      const needsPreflight = action === "run_mf_bulk_upload" || action === "run_mf_csv_import";
      const blockedByPreflight = needsPreflight && !preflightDone;
      button.disabled = blockedByRunning || blockedByPreflight;
      if (blockedByRunning) {
        button.title = "莉悶・謇矩・ｒ螳溯｡御ｸｭ縺ｮ縺溘ａ髢句ｧ九〒縺阪∪縺帙ｓ縲・;
      } else if (blockedByPreflight) {
        button.title = "蜈医↓謇矩・縲梧ｺ門ｙ縲阪ｒ螳溯｡後＠縺ｦ縺上□縺輔＞縲・;
      } else {
        button.title = "";
      }
    });
  }

  function applyProviderAvailability(data) {
    const runningMode = String(data.running_mode || "");
    document.querySelectorAll("[data-provider-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const blockedByRunning = Boolean(runningMode);
      button.disabled = blockedByRunning;
      if (blockedByRunning) {
        button.title = "莉悶・謇矩・ｒ螳溯｡御ｸｭ縺ｮ縺溘ａ髢句ｧ九〒縺阪∪縺帙ｓ縲・;
      } else {
        button.title = "";
      }
    });
  }

  function toCount(value) {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 0) return 0;
    return parsed;
  }

  function buildMfSummaryText(data) {
    const runningMode = String(data?.running_mode || "");
    if (runningMode === "mf_reconcile") {
      return "繧ｵ繝槭Μ繝ｼ: 謇矩・繧貞ｮ溯｡御ｸｭ...";
    }
    const mf = data && typeof data === "object" ? data.mf : null;
    const summary = mf && typeof mf === "object" ? mf.summary : null;
    const missingCandidates = toCount(summary?.missing_candidates);
    const targetsTotal = toCount(summary?.targets_total);
    const created = toCount(summary?.created);
    const failed = toCount(summary?.failed);
    const status = String(summary?.status || "").trim().toLowerCase();
    const hasDraftResult = targetsTotal > 0 || created > 0 || failed > 0 || Boolean(status);
    const reconciled = Boolean(mf?.reconciled);

    if (!reconciled && !hasDraftResult && missingCandidates === 0) {
      return "繧ｵ繝槭Μ繝ｼ: 譛ｪ螳溯｡・;
    }
    if (!hasDraftResult) {
      return `繧ｵ繝槭Μ繝ｼ: 譛ｪ豺ｻ莉伜呵｣・${missingCandidates}莉ｶ / 荳区嶌縺堺ｽ懈・縺ｯ譛ｪ螳溯｡形;
    }
    return `繧ｵ繝槭Μ繝ｼ: 譛ｪ豺ｻ莉伜呵｣・${missingCandidates}莉ｶ / 荳区嶌縺堺ｽ懈・ ${created}/${targetsTotal}莉ｶ・亥､ｱ謨・${failed}莉ｶ・荏;
  }

  function renderMfSummary(data, fallbackMessage = "") {
    const summaryEl = document.querySelector("[data-mf-summary]");
    if (!summaryEl) return;
    if (fallbackMessage) {
      summaryEl.textContent = fallbackMessage;
      return;
    }
    summaryEl.textContent = buildMfSummaryText(data);
  }

  function setStepLinkState(link, enabled, href) {
    if (!link) return;
    if (enabled) {
      link.href = href;
      link.classList.remove("disabled");
      link.removeAttribute("aria-disabled");
      link.removeAttribute("tabindex");
      return;
    }
    link.href = "#";
    link.classList.add("disabled");
    link.setAttribute("aria-disabled", "true");
    link.setAttribute("tabindex", "-1");
  }

  function applyLinkAvailability(data, ym) {
    const amazonExcludeReady = Boolean(data.preflight?.done && data.amazon?.downloaded);
    const rakutenExcludeReady = Boolean(data.preflight?.done && data.rakuten?.downloaded);
    document.querySelectorAll("[data-step-link]").forEach((link) => {
      const key = String(link.dataset.stepLink || "");
      if (key === "amazon_exclude") {
        setStepLinkState(link, amazonExcludeReady, `/runs/${ym}#exclude-section`);
      } else if (key === "rakuten_exclude") {
        setStepLinkState(link, rakutenExcludeReady, `/runs/${ym}#exclude-section`);
      } else {
        setStepLinkState(link, false, "#");
      }
    });
  }

  function buildStepStates(data, runningMode) {
    const amazonRunning = runningMode === "amazon_download" || runningMode === "amazon_print";
    const rakutenRunning = runningMode === "rakuten_download" || runningMode === "rakuten_print";
    const providerRunning = runningMode === "import_provider_receipts";
    const mfBulkUploadRunning = runningMode === "mf_bulk_upload" || runningMode === "mf_csv_import";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const providerDone = Boolean(data.providers?.step_done);
    const mfBulkUploadDone = Boolean(data.mf_bulk_upload?.done || data.mf_csv_import?.done);
    return {
      preflight: data.preflight?.done ? "done" : runningMode === "preflight" ? "running" : "pending",
      amazon_download: amazonRunning ? "running" : data.amazon?.downloaded ? "done" : "pending",
      amazon_decide_print: runningMode === "amazon_print" ? "running" : amazonDone ? "done" : "pending",
      rakuten_download: rakutenRunning ? "running" : data.rakuten?.downloaded ? "done" : "pending",
      rakuten_decide_print: runningMode === "rakuten_print" ? "running" : rakutenDone ? "done" : "pending",
      provider_ingest: providerRunning ? "running" : providerDone ? "done" : "pending",
      mf_bulk_upload_task: mfBulkUploadRunning ? "running" : mfBulkUploadDone ? "done" : "pending",
      mf_reconcile:
        runningMode === "mf_reconcile"
          ? "running"
          : Boolean(data.mf?.step_done ?? data.mf?.reconciled)
            ? "done"
            : "pending",
    };
  }

  function buildTaskStates(stepStates) {
    const amazonRunning = stepStates.amazon_download === "running" || stepStates.amazon_decide_print === "running";
    const rakutenRunning = stepStates.rakuten_download === "running" || stepStates.rakuten_decide_print === "running";
    return {
      amazon: amazonRunning ? "running" : stepStates.amazon_decide_print === "done" ? "done" : "pending",
      rakuten: rakutenRunning ? "running" : stepStates.rakuten_decide_print === "done" ? "done" : "pending",
    };
  }

  async function refreshSteps(options = {}) {
    const force = Boolean(options && options.force);
    if (stepRefreshInFlight) {
      if (!force) return null;
      if (Date.now() - stepRefreshStartedAt < STEP_REFRESH_STALE_MS) return null;
    }
    stepRefreshInFlight = true;
    stepRefreshStartedAt = Date.now();
    const wizard = document.getElementById("wizard");
    if (!wizard) {
      stepRefreshInFlight = false;
      stepRefreshStartedAt = 0;
      return null;
    }

    const ym = getYmFromForm();
    if (!ym) {
      stepRefreshInFlight = false;
      stepRefreshStartedAt = 0;
      return null;
    }
    wizard.dataset.ym = ym;
    applyArchivePageLink(ym);

    try {
      const raw = await apiGetJson(`/api/steps/${ym}`);
      if (!raw) {
        renderNextStep("繧ｹ繝・ャ繝礼憾諷九・蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆縲ょ・隱ｭ縺ｿ霎ｼ縺ｿ縺励※縺上□縺輔＞縲・, null);
        document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
        applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
        applyManualAvailability({ running_mode: "" });
        renderMfSummary(null, "繧ｵ繝槭Μ繝ｼ: 繧ｹ繝・ャ繝礼憾諷九・蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆縲・);
        if (!stepRetryTimer) {
          stepRetryTimer = setTimeout(() => {
            stepRetryTimer = null;
            refreshSteps();
          }, 1500);
        }
        return null;
      }

      const data = {
        preflight: raw.preflight || {},
        amazon: raw.amazon || {},
        rakuten: raw.rakuten || {},
        providers: raw.providers || {},
        mf_bulk_upload: raw.mf_bulk_upload || {},
        mf_csv_import: raw.mf_csv_import || {},
        archive: raw.archive || {},
        mf: raw.mf || {},
        running_mode: raw.running_mode || "",
        next_step: raw.next_step || "",
        allowed_run_modes: Array.isArray(raw.allowed_run_modes) ? raw.allowed_run_modes : [],
      };
      const archiveOverride = archiveStateOverrides[ym];
      if (archiveOverride && !(data.archive && data.archive.created)) {
        data.archive = { ...(data.archive || {}), ...archiveOverride, created: true };
      }

      const runningMode = String(data.running_mode || "");

      applyActionAvailability(data);
      await loadMonthCloseChecklist(ym);
      applyArchiveAvailability(data);
      applyManualAvailability(data);
      applyProviderAvailability(data);
      applyLinkAvailability(data, ym);
      renderMfSummary(data);

      const stepStates = buildStepStates(data, runningMode);
      setStepStatus("preflight", stepStates.preflight);
      setStepStatus("amazon_download", stepStates.amazon_download);
      setStepStatus("amazon_decide_print", stepStates.amazon_decide_print);
      setStepStatus("rakuten_download", stepStates.rakuten_download);
      setStepStatus("rakuten_decide_print", stepStates.rakuten_decide_print);
      setStepStatus("provider_ingest", stepStates.provider_ingest);
      setStepStatus("mf_bulk_upload_task", stepStates.mf_bulk_upload_task);
      setStepStatus("mf_reconcile", stepStates.mf_reconcile);
      const taskStates = buildTaskStates(stepStates);
      setTaskStatus("amazon", taskStates.amazon);
      setTaskStatus("rakuten", taskStates.rakuten);

      const labels = {
        preflight: "謇矩・ 貅門ｙ",
        amazon_download: "謇矩・ Amazon 蜿門ｾ・,
        amazon_decide_print: "謇矩・ Amazon 髯､螟悶・蜊ｰ蛻ｷ・亥ｮ御ｺ・ｨ倬鹸縺ｾ縺ｧ・・,
        rakuten_download: "謇矩・ 讌ｽ螟ｩ 蜿門ｾ・,
        rakuten_decide_print: "謇矩・ 讌ｽ螟ｩ 髯､螟悶・蜊ｰ蛻ｷ・亥ｮ御ｺ・ｨ倬鹸縺ｾ縺ｧ・・,
        provider_ingest: "謇矩・ 蜈ｱ騾壹ヵ繧ｩ繝ｫ繝蜿悶ｊ霎ｼ縺ｿ",
        mf_bulk_upload_task: "謇矩・ MF荳諡ｬ繧｢繝・・繝ｭ繝ｼ繝・,
        mf_reconcile: "謇矩・ MF遯∝粋繝ｻ荳区嶌縺堺ｽ懈・",
      };
      if (!window.__stepState) {
        window.__stepState = stepStates;
      } else {
        Object.keys(stepStates).forEach((key) => {
          if (key === "mf_reconcile") return;
          if (window.__stepState[key] && window.__stepState[key] !== "done" && stepStates[key] === "done") {
            showToast(`${labels[key]}縺悟ｮ御ｺ・＠縺ｾ縺励◆縲Ａ, "success");
          }
        });
      }
      window.__stepState = stepStates;
      const next = computeNextStep(data, ym);
      renderNextStep(next.message, next.href, next.reason, next.linkLabel);
      if (stepRetryTimer) {
        clearTimeout(stepRetryTimer);
        stepRetryTimer = null;
      }
      return data;


    } catch {
      renderNextStep("繧ｹ繝・ャ繝礼憾諷九・蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆縲ょ・隱ｭ縺ｿ霎ｼ縺ｿ縺励※縺上□縺輔＞縲・, null);
      document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
      applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
      applyManualAvailability({ running_mode: "" });
      applyProviderAvailability({ running_mode: "", preflight: {} });
      renderMfSummary(null, "繧ｵ繝槭Μ繝ｼ: 繧ｹ繝・ャ繝礼憾諷九・蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆縲・);
      if (!stepRetryTimer) {
        stepRetryTimer = setTimeout(() => {
          stepRetryTimer = null;
          refreshSteps();
        }, 1500);
      }
      return null;
    } finally {
      stepRefreshInFlight = false;
      stepRefreshStartedAt = 0;
    }
  }

  if (logEl && logEl.dataset.runId) {
    clearError();
    startLogPolling(logEl.dataset.runId);
    refreshLog(logEl.dataset.runId);
  }

  if (form) {
    document.querySelectorAll("[data-step-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (button.dataset.stepAction) startRun(button.dataset.stepAction);
      });
    });

    document.querySelectorAll("[data-archive-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (button.dataset.archiveAction === "archive_outputs") {
          archiveOutputs(button);
          return;
        }
        if (button.dataset.archiveAction === "month_close") {
          monthClose(button);
        }
      });
    });

    document.querySelectorAll("[data-manual-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        runManualAction(String(button.dataset.manualAction || ""), button);
      });
    });

    document.querySelectorAll("[data-provider-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        runProviderAction(String(button.dataset.providerAction || ""), String(button.dataset.provider || ""), button);
      });
    });

    document.querySelectorAll("[data-step-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        if (link.getAttribute("aria-disabled") === "true") {
          event.preventDefault();
          showToast("縺薙・謇矩・・縺ｾ縺螳溯｡後〒縺阪∪縺帙ｓ縲よｬ｡縺ｮ謇矩・｡亥・繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・, "error");
        }
      });
    });

    document.querySelectorAll("[data-step-reset]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const stepId = String(button.dataset.stepReset || "");
        if (!stepId) return;
        resetStep(stepId, button);
      });
    });

    const handleYmChanged = () => {
      const ym = getYmFromForm();
      persistYmSelection(ym);
      applyArchivePageLink(ym);
      refreshSteps();
    };
    form.querySelector("[name=year]")?.addEventListener("change", handleYmChanged);
    form.querySelector("[name=month]")?.addEventListener("change", handleYmChanged);

    restoreYmSelection();
    const initialYm = getYmFromForm();
    applyArchivePageLink(initialYm);
    refreshSteps();
    if (!window.__stepTimer) {
      window.__stepTimer = setInterval(refreshSteps, 3000);
    }
  }

  if (stopButton) {
    stopButton.addEventListener("click", async () => {
      const runId = stopButton.dataset.runId;
      if (!runId) return;
      const res = await fetch(`/api/runs/${runId}/stop`, { method: "POST" });
      if (!res.ok) {
        const message = "螳溯｡後・蛛懈ｭ｢縺ｫ螟ｱ謨励＠縺ｾ縺励◆縲・;
        showError(message);
        showToast(message, "error");
        return;
      }
      const message = "蛛懈ｭ｢繝ｪ繧ｯ繧ｨ繧ｹ繝医ｒ騾∽ｿ｡縺励∪縺励◆縲ゅΟ繧ｰ譖ｴ譁ｰ繧偵♀蠕・■縺上□縺輔＞縲・;
      showError(message);
      showToast(message, "success");
    });
  }

  bindCopyButtons();

  // ========== Month Close Checklist ==========
  async function loadMonthCloseChecklist(ym) {
    if (!ym) return;
    try {
      const data = await apiGetJson(`/api/month-close-checklist/${ym}`);
      if (data && data.checklist) {
        checklistState = normalizeChecklistState(data.checklist);
        updateCheckboxes();
      }
    } catch (err) {
      console.warn("Failed to load checklist:", err);
    }
  }

  async function saveMonthCloseChecklist(ym) {
    if (!ym) return;
    try {
      const res = await fetch(`/api/month-close-checklist/${ym}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checklist: normalizeChecklistState(checklistState) }),
      });
      if (!res.ok) {
        console.warn("Failed to save checklist:", res.statusText);
      }
    } catch (err) {
      console.warn("Failed to save checklist:", err);
    }
  }

  function updateCheckboxes() {
    document.querySelectorAll("[data-checklist-item]").forEach((checkbox) => {
      const key = checkbox.dataset.checklistItem;
      if (key in checklistState) {
        checkbox.checked = checklistState[key];
      }
    });
  }

  // Bind checkbox change events
  document.querySelectorAll("[data-checklist-item]").forEach((checkbox) => {
    checkbox.addEventListener("change", async (e) => {
      const key = e.target.dataset.checklistItem;
      if (key in checklistState) {
        checklistState[key] = e.target.checked;
        const ym = getYmFromForm();
        await saveMonthCloseChecklist(ym);
        // Refresh steps to update button state
        refreshSteps({ force: true });
      }
    });
  });
})();
