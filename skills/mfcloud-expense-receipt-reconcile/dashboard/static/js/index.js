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
  const PROVIDER_SOURCE_SETUP_GUIDE_URL =
    "https://github.com/Igasawa/Skills-personal/blob/main/skills/mfcloud-expense-receipt-reconcile/SKILL.md";

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

    // 郢ｧ・ｻ郢ｧ・ｯ郢ｧ・ｷ郢晢ｽｧ郢晢ｽｳ陷茨ｽｨ闖ｴ阮吶・郢ｧ・ｹ郢昴・繝ｻ郢ｧ・ｿ郢ｧ・ｹ郢ｧ・ｯ郢晢ｽｩ郢ｧ・ｹ郢ｧ蜻亥ｳｩ隴・ｽｰ
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
        showToast("陞ｳ貅ｯ・｡蠕娯・陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧・溽ｹｧ・ｰ郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
      } else if (status === "success") {
        showToast("陞ｳ貅ｯ・｡蠕娯ｲ陞ｳ蠕｡・ｺ繝ｻ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ, "success");
      }
    }
    if (status) {
      runStatusById[runId] = status;
    }

    if (status === "failed") {
      showError("陞ｳ貅ｯ・｡蠕娯・陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧・溽ｹｧ・ｰ郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ);
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
    showToast("陞ｳ貅ｯ・｡蠕鯉ｽ帝ｫ｢蜿･・ｧ荵晢ｼ邵ｺ・ｦ邵ｺ繝ｻ竏ｪ邵ｺ繝ｻ..", "success");

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
        logEl.textContent = "陞ｳ貅ｯ・｡蠕鯉ｽ帝ｫ｢蜿･・ｧ荵晢ｼ邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧・溽ｹｧ・ｰ郢ｧ蜻亥ｳｩ隴・ｽｰ闕ｳ・ｭ...";
      }

      awaitingRunFinalization = true;
      updateRunSummary({
        run_id: data.run_id,
        status: "running",
        started_at: new Date().toLocaleString("ja-JP", { hour12: false }),
        params: { year: payload.year, month: payload.month },
      });
      runStatusById[data.run_id] = "running";
      showToast("陞ｳ貅ｯ・｡蠕鯉ｽ帝ｫ｢蜿･・ｧ荵晢ｼ邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ, "success");

      startLogPolling(data.run_id);
      refreshLog(data.run_id);
      scheduleStepSync();
    } catch {
      awaitingRunFinalization = false;
      const message = "陞ｳ貅ｯ・｡遒∝ｹ戊沂荵昶・陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧・・髫ｧ・ｦ髯ｦ蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ;
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
    const actionLabel = String(entry.action_label || "").trim() || "郢ｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢昴・;
    const href = String(entry.archive_url || "").trim() || (ym ? `/runs/${ym}/archived-receipts` : "#");

    const item = document.createElement("li");
    item.className = "archive-history-item";
    const text = document.createElement("span");
    text.className = "muted";
    text.textContent = `${ts || "-"} / ${ym || "-"} / ${actionLabel}`;
    const link = document.createElement("a");
    link.className = "secondary";
    link.href = href;
    link.textContent = "郢ｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ・帝ｫ｢荵晢ｿ･";
    item.appendChild(text);
    item.appendChild(link);
    list.prepend(item);
  }

  async function runArchiveAction(action, buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
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
    showToast(isMonthClose ? "隴帛沺・ｬ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ郢ｧ雋橸ｽｮ貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ繝ｻ竏ｪ邵ｺ繝ｻ.." : "郢ｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ・定抄諛医・邵ｺ蜉ｱ窶ｻ邵ｺ繝ｻ竏ｪ邵ｺ繝ｻ..", "success");

    try {
      const endpoint = isMonthClose ? `/api/month-close/${ym}` : `/api/archive/${ym}`;
      const res = await fetch(endpoint, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || (isMonthClose ? "隴帛沺・ｬ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ : "郢ｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晉ｴ具ｽｽ諛医・邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ));
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
      const cleanupSuffix = Number.isFinite(cleanupRemoved) ? ` / 郢ｧ・ｯ郢晢ｽｪ郢晢ｽｼ郢晢ｽｳ郢ｧ・｢郢昴・繝ｻ ${cleanupRemoved}闔会ｽｶ` : "";
      const baseMessage = isMonthClose ? "隴帛沺・ｬ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ邵ｺ謔滂ｽｮ蠕｡・ｺ繝ｻ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ : "郢ｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ・定抄諛医・邵ｺ蜉ｱ竏ｪ邵ｺ蜉ｱ笳・;
      let message = archivedTo ? `${baseMessage}: ${archivedTo}${cleanupSuffix}` : `${baseMessage}邵ｲ繝ｻ{cleanupSuffix}`;
      if (isMonthClose) {
        const next = nextYm(ym);
        if (next) {
          setYmToForm(next);
          if (window.__stepState) window.__stepState = null;
          message += ` / 郢ｧ・ｦ郢ｧ・｣郢ｧ・ｶ郢晢ｽｼ郢晏ｳｨ・・${next} 邵ｺ・ｫ陋ｻ繝ｻ・願ｭ厄ｽｿ邵ｺ蛹ｻ竏ｪ邵ｺ蜉ｱ笳・ｸｲ・｡;
        }
      }
      prependArchiveHistoryRow(data.history_entry || null);
      showToast(message, "success");
    } catch {
      const message = normalizedAction === "month_close" ? "隴帛沺・ｬ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ : "郢ｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晉ｴ具ｽｽ諛医・邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
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
        const message = toFriendlyMessage(data.detail || "陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ莉｣竏ｪ邵ｺ蟶呻ｽ鍋ｸｺ・ｧ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath ? `陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・ ${openedPath}` : "陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
      showToast(message, "success");
    } catch {
      const message = "陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ莉｣竏ｪ邵ｺ蟶呻ｽ鍋ｸｺ・ｧ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("隰・唱陌夐ｬ・ｼ懷ｺｶ隴厄ｽｸ邵ｺ・ｮ陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ郢ｧ蟶晏ｹ戊沂荵晢ｼ邵ｺ・ｾ邵ｺ繝ｻ..", "success");
    try {
      const res = await fetch(`/api/manual/${ym}/import`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "鬯・ｼ懷ｺｶ隴厄ｽｸ陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.found_pdfs ?? 0), 10) || 0;
      const imported = Number.parseInt(String(data.imported ?? 0), 10) || 0;
      const skipped = Number.parseInt(String(data.skipped_duplicates ?? 0), 10) || 0;
      const failed = Number.parseInt(String(data.failed ?? 0), 10) || 0;
      const message = `隰・唱陌夐ｬ・ｼ懷ｺｶ隴厄ｽｸ陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ: 騾具ｽｺ髫輔・${found}闔会ｽｶ / 陷ｿ蜀ｶ・ｾ・ｼ ${imported}闔会ｽｶ / 鬩･蟠趣ｽ､繝ｻ${skipped}闔会ｽｶ / 陞滂ｽｱ隰ｨ繝ｻ${failed}闔会ｽｶ`;
      showToast(message, failed > 0 ? "error" : "success");
      if (failed > 0) {
        showError(message);
      }
    } catch {
      const message = "鬯・ｼ懷ｺｶ隴厄ｽｸ陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
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
        const message = toFriendlyMessage(data.detail || "MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晁・逡醍ｹ晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ莉｣竏ｪ邵ｺ蟶呻ｽ鍋ｸｺ・ｧ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath
        ? `MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晁・逡醍ｹ晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・ ${openedPath}`
        : "MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晁・逡醍ｹ晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
      showToast(message, "success");
    } catch {
      const message = "MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晁・逡醍ｹ晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ莉｣竏ｪ邵ｺ蟶呻ｽ鍋ｸｺ・ｧ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晏ｳｨ・帝ｫ｢蜿･・ｧ荵晢ｼ邵ｺ・ｾ邵ｺ繝ｻ..", "success");
    try {
      const res = await fetch(`/api/mf-bulk-upload/${ym}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晏ｳｨ竊楢棔・ｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.files_found ?? 0), 10) || 0;
      const submitted = Number.parseInt(String(data.submitted_count ?? 0), 10) || 0;
      const queued = Number.parseInt(String(data.queued_count ?? 0), 10) || 0;
      const readCount = Number.parseInt(String(data.read_count ?? 0), 10) || 0;
      const archivedDir = String(data.archived_dir || "").trim();
      const details = archivedDir ? ` / 闖ｫ譎会ｽｮ・｡: ${archivedDir}` : "";
      const message = `MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢昴・ 騾具ｽｺ髫輔・${found}闔会ｽｶ / 髫ｱ・ｭ髴趣ｽｼ ${readCount}闔会ｽｶ / 郢ｧ・ｭ郢晢ｽ･郢晢ｽｼ ${queued}闔会ｽｶ / 鬨ｾ竏ｽ・ｿ・｡ ${submitted}闔会ｽｶ${details}`;
      showToast(message, "success");
    } catch {
      const message = "MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晏ｳｨ竊楢棔・ｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
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
        const message = toFriendlyMessage(data.detail || "闔・､鬨ｾ螟奇ｽｲ・ｻCSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晁ご逡醍ｹ晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ莉｣竏ｪ邵ｺ蟶呻ｽ鍋ｸｺ・ｧ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath
        ? `闔・､鬨ｾ螟奇ｽｲ・ｻCSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晁ご逡醍ｹ晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・ ${openedPath}`
        : "闔・､鬨ｾ螟奇ｽｲ・ｻCSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晁ご逡醍ｹ晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
      showToast(message, "success");
    } catch {
      const message = "闔・､鬨ｾ螟奇ｽｲ・ｻCSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晁ご逡醍ｹ晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ莉｣竏ｪ邵ｺ蟶呻ｽ鍋ｸｺ・ｧ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("闔・､鬨ｾ螟奇ｽｲ・ｻCSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晏現・帝ｫ｢蜿･・ｧ荵晢ｼ邵ｺ・ｾ邵ｺ繝ｻ..", "success");
    try {
      const res = await fetch(`/api/mf-csv-import/${ym}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "闔・､鬨ｾ螟奇ｽｲ・ｻCSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晏現竊楢棔・ｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.files_found ?? 0), 10) || 0;
      const submitted = Number.parseInt(String(data.submitted_count ?? 0), 10) || 0;
      const queued = Number.parseInt(String(data.queued_count ?? 0), 10) || 0;
      const archivedDir = String(data.archived_dir || "").trim();
      const details = archivedDir ? ` / 闖ｫ譎会ｽｮ・｡: ${archivedDir}` : "";
      const message = `闔・､鬨ｾ螟奇ｽｲ・ｻCSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢昴・ 騾具ｽｺ髫輔・${found}闔会ｽｶ / 郢ｧ・ｭ郢晢ｽ･郢晢ｽｼ ${queued}闔会ｽｶ / 鬨ｾ竏ｽ・ｿ・｡ ${submitted}闔会ｽｶ${details}`;
      showToast(message, "success");
    } catch {
      const message = "闔・､鬨ｾ螟奇ｽｲ・ｻCSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晏現竊楢棔・ｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
      return;
    }
    if (!normalizedProvider) {
      showToast("陝・ｽｾ髮趣ｽ｡郢ｧ・ｵ郢晢ｽｼ郢晁侭縺帷ｸｺ譴ｧ谺陞ｳ螢ｹ・・ｹｧ蠕娯ｻ邵ｺ繝ｻ竏ｪ邵ｺ蟶呻ｽ鍋ｸｲ繝ｻ, "error");
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
        const message = toFriendlyMessage(data.detail || "郢ｧ・ｵ郢晢ｽｼ郢晁侭縺幄崕・･郢晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ莉｣竏ｪ邵ｺ蟶呻ｽ鍋ｸｺ・ｧ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const label = providerLabel(normalizedProvider);
      const message = openedPath ? `${label}郢晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・ ${openedPath}` : `${label}郢晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・ｸｲ・｡;
      showToast(message, "success");
    } catch {
      const message = "郢ｧ・ｵ郢晢ｽｼ郢晁侭縺幄崕・･郢晁ｼ斐°郢晢ｽｫ郢敖郢ｧ蟶晏ｹ慕ｸｺ莉｣竏ｪ邵ｺ蟶呻ｽ鍋ｸｺ・ｧ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function openProviderSource(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("蟷ｴ譛医ｒ驕ｸ謚槭＠縺ｦ縺上□縺輔＞縲・, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    try {
      const res = await fetch(`/api/folders/${ym}/provider-source`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "Provider source folder could not be opened.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      renderProviderSourceSummary(data.source_status || data.providers?.source);
      const message = openedPath ? `Provider source folder opened: ${openedPath}` : "Provider source folder opened.";
      showToast(message, "success");
    } catch {
      const message = "Provider source folder could not be opened.";
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖邵ｺ・ｮ鬯・ｼ懷ｺｶ隴厄ｽｸ郢ｧ雋槫徐郢ｧ鬘假ｽｾ・ｼ邵ｺ・ｿ闕ｳ・ｭ...", "success");
    try {
      const res = await fetch(`/api/providers/${ym}/import`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.found_files ?? 0), 10) || 0;
      const imported = Number.parseInt(String(data.imported ?? 0), 10) || 0;
      const skipped = Number.parseInt(String(data.skipped_duplicates ?? 0), 10) || 0;
      const failed = Number.parseInt(String(data.failed ?? 0), 10) || 0;
      const message = `陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ: 隶諛ｷ繝ｻ ${found}闔会ｽｶ / 陷ｿ蜀ｶ・ｾ・ｼ ${imported}闔会ｽｶ / 鬩･蟠趣ｽ､繝ｻ${skipped}闔会ｽｶ / 陞滂ｽｱ隰ｨ繝ｻ${failed}闔会ｽｶ`;
      const manualActionRequired = Boolean(data.manual_action_required) || skipped > 0 || failed > 0;
      if (!manualActionRequired) {
        showToast(message, "success");
        return;
      }

      const details = [message, "郢ｧ・ｹ郢ｧ・ｭ郢昴・繝ｻ/陞滂ｽｱ隰ｨ諤懊・邵ｺ・ｯMF邵ｺ・ｸ髢ｾ・ｪ陷榊｢難ｽｷ・ｻ闔牙･・・ｹｧ蠕娯ｻ邵ｺ繝ｻ竏ｪ邵ｺ蟶呻ｽ鍋ｸｲ繧育・陷榊｢難ｽｷ・ｻ闔牙･・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ];
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
        details.push(`隴幢ｽｪ雎ｺ・ｻ闔牙・ｽｸﾂ髫包ｽｧ郢晁ｼ斐°郢晢ｽｫ郢敖: ${skippedFolderPath}`);
      }
      const skippedFiles = Array.isArray(data.skipped_files)
        ? data.skipped_files.map((value) => String(value || "").trim()).filter((value) => value)
        : [];
      if (skippedFiles.length > 0) {
        const preview = skippedFiles.slice(0, 8);
        const suffix = skippedFiles.length > preview.length ? ` 邵ｺ・ｻ邵ｺ繝ｻ{skippedFiles.length - preview.length}闔会ｽｶ` : "";
        details.push(`隴幢ｽｪ雎ｺ・ｻ闔牙･繝ｵ郢ｧ・｡郢ｧ・､郢晢ｽｫ: ${preview.join(", ")}${suffix}`);
      }
      const errorMessage = details.join("\n");
      showError(errorMessage);
      showToast("陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ邵ｺ・ｧ郢ｧ・ｹ郢ｧ・ｭ郢昴・繝ｻ/陞滂ｽｱ隰ｨ蜉ｱ窶ｲ騾具ｽｺ騾墓ｺ假ｼ邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧育・陷榊｢難ｽｷ・ｻ闔牙･窶ｲ陟｢繝ｻ・ｦ竏壹堤ｸｺ蜷ｶﾂ繝ｻ, "error");
    } catch {
      const message = "陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖陷ｿ蜀ｶ・ｾ・ｼ雋ょ現竏ｩ邵ｺ・ｮPDF郢ｧ蝣､・ｵ莉咏ｲ狗ｸｺ蜉ｱ窶ｻ邵ｺ繝ｻ竏ｪ邵ｺ繝ｻ..", "success");
    try {
      const res = await fetch(`/api/providers/${ym}/print-run`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖闕ｳﾂ隲｡・ｬ陷奇ｽｰ陋ｻ・ｷ邵ｺ・ｮ鬮｢蜿･・ｧ荵昶・陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
        showError(message);
        showToast(message, "error");
        return;
      }
      const count = Number.parseInt(String(data.count ?? 0), 10) || 0;
      const message = `陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖陷ｿ蜀ｶ・ｾ・ｼ陋ｻ繝ｻ繝ｻ驍ｨ莉咏ｲ輝DF郢ｧ蟶晏ｹ慕ｸｺ髦ｪ竏ｪ邵ｺ蜉ｱ笳・・莠･・ｯ・ｾ髮趣ｽ｡ ${Math.max(0, count)} 闔会ｽｶ繝ｻ蟲ｨﾂ・｡;
      showToast(message, "success");
    } catch {
      const message = "陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖闕ｳﾂ隲｡・ｬ陷奇ｽｰ陋ｻ・ｷ邵ｺ・ｮ鬮｢蜿･・ｧ荵昶・陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  function runProviderAction(action, provider, buttonEl) {
    if (action === "open_provider_source") {
      openProviderSource(buttonEl);
      return;
    }
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
      showToast("陝ｷ・ｴ隴帛現・定怦・･陷牙ｸ呻ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
      return;
    }
    const labelByStep = {
      amazon_download: "Amazon郢ｧ・ｫ郢晢ｽｼ郢昴・/ 陷ｿ髢・ｾ繝ｻ,
      amazon_decide_print: "Amazon郢ｧ・ｫ郢晢ｽｼ郢昴・/ 鬮ｯ・､陞滄摩諢幄ｭ・ｽｭ郢晢ｽｻ陷奇ｽｰ陋ｻ・ｷ繝ｻ莠･・ｮ蠕｡・ｺ繝ｻ・ｨ蛟ｬ鮖ｸ邵ｺ・ｾ邵ｺ・ｧ繝ｻ繝ｻ,
      rakuten_download: "隶鯉ｽｽ陞滂ｽｩ郢ｧ・ｫ郢晢ｽｼ郢昴・/ 陷ｿ髢・ｾ繝ｻ,
      rakuten_decide_print: "隶鯉ｽｽ陞滂ｽｩ郢ｧ・ｫ郢晢ｽｼ郢昴・/ 鬮ｯ・､陞滄摩諢幄ｭ・ｽｭ郢晢ｽｻ陷奇ｽｰ陋ｻ・ｷ繝ｻ莠･・ｮ蠕｡・ｺ繝ｻ・ｨ蛟ｬ鮖ｸ邵ｺ・ｾ邵ｺ・ｧ繝ｻ繝ｻ,
    };
    const label = labelByStep[String(stepId || "")] || String(stepId || "");
    const confirmed = window.confirm(`邵ｲ繝ｻ{label}邵ｲ髦ｪ・堤ｹ晢ｽｪ郢ｧ・ｻ郢昴・繝ｨ邵ｺ蜉ｱ竏ｪ邵ｺ蜷ｶﾂ繧・ｽｿ繝ｻ・ｦ竏壺・郢ｧ迚呻ｽｮ貅ｯ・｡蠕｡・ｸ・ｭ郢ｧ・ｸ郢晢ｽｧ郢晄じ・定屁諛茨ｽｭ・｢邵ｺ蜉ｱ竏ｪ邵ｺ蜷ｶﾂ繧会ｽｶ螟奇ｽ｡蠕鯉ｼ邵ｺ・ｾ邵ｺ蜷ｶﾂｰ繝ｻ豁・;
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
      showToast(cancelledCount > 0 ? `郢晢ｽｪ郢ｧ・ｻ郢昴・繝ｨ陞ｳ蠕｡・ｺ繝ｻ 陞ｳ貅ｯ・｡蠕｡・ｸ・ｭ郢ｧ・ｸ郢晢ｽｧ郢昴・${cancelledCount} 闔会ｽｶ郢ｧ雋樞酪雎・ｽ｢邵ｺ蜉ｱ竏ｪ邵ｺ蜉ｱ笳・ｸｲ・｡ : "郢晢ｽｪ郢ｧ・ｻ郢昴・繝ｨ邵ｺ謔滂ｽｮ蠕｡・ｺ繝ｻ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ, "success");
      scheduleStepSync();
      if (activeLogRunId) {
        refreshLog(activeLogRunId);
      }
    } catch {
      const message = "郢晢ｽｪ郢ｧ・ｻ郢昴・繝ｨ邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
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
      el.textContent = "陞ｳ貅ｯ・｡謔溷ｺ・;
      el.classList.add("pending");
      return;
    }
    if (state === "done") {
      el.textContent = "陞ｳ蠕｡・ｺ繝ｻ;
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "陞ｳ貅ｯ・｡蠕｡・ｸ・ｭ";
      el.classList.add("running");
      return;
    }
    el.textContent = "隴幢ｽｪ陞ｳ貅ｯ・｡繝ｻ;
    el.classList.add("pending");
  }

  function setTaskStatus(id, state) {
    const el = document.querySelector(`[data-task-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (state === "done") {
      el.textContent = "陞ｳ蠕｡・ｺ繝ｻ;
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "陞ｳ貅ｯ・｡蠕｡・ｸ・ｭ";
      el.classList.add("running");
      return;
    }
    el.textContent = "隴幢ｽｪ陞ｳ貅ｯ・｡繝ｻ;
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
    link.textContent = String(linkLabel || "鬮｢荵晢ｿ･").trim() || "鬮｢荵晢ｿ･";
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
      showToast("陝・ｽｾ髮趣ｽ｡郢ｧ・ｻ郢ｧ・ｯ郢ｧ・ｷ郢晢ｽｧ郢晢ｽｳ邵ｺ迹夲ｽｦ荵昶命邵ｺ荵晢ｽ顔ｸｺ・ｾ邵ｺ蟶呻ｽ鍋ｸｲ繝ｻ, "warning");
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
        message: "邵ｺ・ｾ邵ｺ螢ｹ繝ｻ陷題ざ鄂ｲ隴夲ｽ｡闔会ｽｶ邵ｺ・ｮ驕抵ｽｺ髫ｱ髦ｪﾂｰ郢ｧ陋ｾﾂ・ｲ郢ｧ竏壺ｻ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "郢晢ｽｭ郢ｧ・ｰ郢ｧ・､郢晢ｽｳ霑･・ｶ隲ｷ荵昶・隴帛沺・ｬ・｡隲繝ｻ・ｰ・ｱ郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｲ竏晢ｽｮ貅ｯ・｡謔溷ｺ・妙・ｽ隴夲ｽ｡闔会ｽｶ郢ｧ蛛ｵ笳守ｹｧ髦ｪ竏ｴ邵ｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "雋・摩・呵淦・･驕樔ｹ昶・",
      },
      amazon_or_rakuten_download: {
        message: "邵ｺ・ｾ邵ｺ螢ｹ繝ｻ Amazon 邵ｺ蛹ｺ・･・ｽ陞滂ｽｩ邵ｺ・ｮ邵ｺ繝ｻ笘・ｹｧ蠕個ｰ邵ｺ・ｮ鬯・ｼ懷ｺｶ隴厄ｽｸ陷ｿ髢・ｾ蜉ｱ・定怦蛹ｻ竊楢楜貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "陝・ｻ｣竊醍ｸｺ荳岩・郢ｧ繝ｻ驕会ｽｾ陋ｻ繝ｻ繝ｻ鬯・ｼ懷ｺｶ隴厄ｽｸ陷ｿ髢・ｾ蜉ｱ窶ｲ陟｢繝ｻ・ｦ竏壹堤ｸｺ蜷ｶﾂ繧域ざ陷ｿ髢・ｾ蜉ｱ窶ｲ邵ｺ繧・ｽ狗ｸｺ・ｨ隹ｺ・｡邵ｺ・ｮ陷・ｽｦ騾・・竊馴ｨｾ・ｲ郢ｧ竏壺穐邵ｺ蟶呻ｽ鍋ｸｲ繝ｻ,
        linkLabel: "Amazon繝ｻ荵暦ｽ･・ｽ陞滂ｽｩ 陷ｿ髢・ｾ蜉ｱ竏・,
      },
      amazon_download: {
        message: "Amazon 邵ｺ・ｮ鬯・ｼ懷ｺｶ隴厄ｽｸ郢ｧ雋槫徐陟募干・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "Amazon 陋幢ｽｴ邵ｺ・ｮ陝・ｽｾ髮趣ｽ｡隴帛現繝ｧ郢晢ｽｼ郢ｧ・ｿ郢ｧ雋槫徐陟募干・邵ｺ・ｦ邵ｲ竏ｵ・ｬ・｡邵ｺ・ｮ鬮ｯ・､陞滄摩諢幄ｭ・ｽｭ郢晢ｽｻ陷奇ｽｰ陋ｻ・ｷ邵ｺ・ｸ鬨ｾ・ｲ邵ｺ・ｿ邵ｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "Amazon 陷ｿ髢・ｾ蜉ｱ竏・,
      },
      amazon_decide_print: {
        message: "Amazon 邵ｺ・ｮ鬮ｯ・､陞溷・・ｨ・ｭ陞ｳ螢ｹ繝ｻ陷奇ｽｰ陋ｻ・ｷ陝・ｽｾ髮趣ｽ｡郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "鬮ｯ・､陞滄摩・ｯ・ｾ髮趣ｽ｡郢ｧ蝣､・｢・ｺ陞ｳ螢ｹ・邵ｺ・ｦ陷奇ｽｰ陋ｻ・ｷ陞ｳ蠕｡・ｺ繝ｻ竏ｪ邵ｺ・ｧ鬨ｾ・ｲ郢ｧ竏夲ｽ狗ｸｺ・ｨ霑･・ｶ隲ｷ荵昶ｲ闖ｫ譎擾ｽｭ蛟･・・ｹｧ蠕娯穐邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "Amazon 鬮ｯ・､陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ邵ｺ・ｸ",
      },
      amazon_print: {
        message: "Amazon邵ｺ・ｮ陷奇ｽｰ陋ｻ・ｷ陞ｳ蠕｡・ｺ繝ｻ・ｾ繝ｻ笆郢ｧ・ｹ郢昴・繝ｻ郢ｧ・ｿ郢ｧ・ｹ郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "Amazon邵ｺ・ｮ陷奇ｽｰ陋ｻ・ｷ陷・ｽｦ騾・・窶ｲ陞ｳ蠕｡・ｺ繝ｻ・邵ｲ竏晢ｽｿ繝ｻ・ｦ竏壺・陟｢諛環ｧ邵ｺ・ｦ驕抵ｽｺ髫ｱ髦ｪ繝ｻ陷ｿ閧ｴ荳千ｹｧ螳夲ｽ｡蠕娯夢邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "Amazon邵ｺ・ｮ陷奇ｽｰ陋ｻ・ｷ郢ｧ・ｹ郢昴・繝ｻ郢ｧ・ｿ郢ｧ・ｹ邵ｺ・ｸ",
      },
      rakuten_download: {
        message: "隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｮ鬯・ｼ懷ｺｶ隴厄ｽｸ郢ｧ雋槫徐陟募干・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "隶鯉ｽｽ陞滂ｽｩ陋幢ｽｴ邵ｺ・ｮ陝・ｽｾ髮趣ｽ｡隴帛現繝ｧ郢晢ｽｼ郢ｧ・ｿ郢ｧ雋槫徐陟募干・邵ｺ・ｦ邵ｲ竏ｵ・ｬ・｡邵ｺ・ｮ鬮ｯ・､陞滄摩諢幄ｭ・ｽｭ郢晢ｽｻ陷奇ｽｰ陋ｻ・ｷ邵ｺ・ｸ鬨ｾ・ｲ邵ｺ・ｿ邵ｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "隶鯉ｽｽ陞滂ｽｩ 陷ｿ髢・ｾ蜉ｱ竏・,
      },
      rakuten_print: {
        message: "隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｮ陷奇ｽｰ陋ｻ・ｷ陞ｳ蠕｡・ｺ繝ｻ・ｾ繝ｻ笆郢ｧ・ｹ郢昴・繝ｻ郢ｧ・ｿ郢ｧ・ｹ郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｮ陷奇ｽｰ陋ｻ・ｷ陷・ｽｦ騾・・窶ｲ陞ｳ蠕｡・ｺ繝ｻ・邵ｲ竏晢ｽｿ繝ｻ・ｦ竏壺・陟｢諛環ｧ邵ｺ・ｦ驕抵ｽｺ髫ｱ髦ｪ繝ｻ陷ｿ閧ｴ荳千ｹｧ螳夲ｽ｡蠕娯夢邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｮ陷奇ｽｰ陋ｻ・ｷ郢ｧ・ｹ郢昴・繝ｻ郢ｧ・ｿ郢ｧ・ｹ邵ｺ・ｸ",
      },
      rakuten_decide_print: {
        message: "隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｮ鬮ｯ・､陞溷・・ｨ・ｭ陞ｳ螢ｹ繝ｻ陷奇ｽｰ陋ｻ・ｷ陝・ｽｾ髮趣ｽ｡郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "鬮ｯ・､陞滄摩・ｯ・ｾ髮趣ｽ｡郢ｧ蝣､・｢・ｺ陞ｳ螢ｹ・邵ｺ・ｦ陷奇ｽｰ陋ｻ・ｷ陞ｳ蠕｡・ｺ繝ｻ竏ｪ邵ｺ・ｧ鬨ｾ・ｲ郢ｧ竏夲ｽ狗ｸｺ・ｨ霑･・ｶ隲ｷ荵昶ｲ闖ｫ譎擾ｽｭ蛟･・・ｹｧ蠕娯穐邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "隶鯉ｽｽ陞滂ｽｩ 鬮ｯ・､陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ邵ｺ・ｸ",
      },
      mf_reconcile: {
        message: "MF鬨ｾ・｣隰ｳ・ｺ邵ｺ・ｮ驕ｯ竏晉ｲ狗ｸｺ蟶幢ｽｮ貅ｯ・｡蠕娯・鬨ｾ・ｲ郢ｧ竏壺ｻ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ雋ょ現竏ｩ郢昴・繝ｻ郢ｧ・ｿ郢ｧ讓ｽF邵ｺ・ｮ闕ｳ蛹ｺ蠍檎ｸｺ蝣ｺ・ｽ諛医・邵ｺ・ｸ陷ｿ閧ｴ荳千ｸｺ蜉ｱ竏ｪ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "MF 驕ｯ竏晉ｲ玖抄諛茨ｽ･・ｭ邵ｺ・ｸ",
      },
      preflight_mf: {
        message: "MF陷讎雁徐陟募干繝ｻ邵ｺ・ｿ邵ｺ・ｮ郢ｧ・ｹ郢昴・繝｣郢晏干・定楜蠕｡・ｺ繝ｻ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "MF陷讎雁徐陟墓懶ｽｾ蠕個竏壹Β郢昴・縺咏ｹ晢ｽ･郢晄㈱繝ｻ郢晏ｳｨ繝ｻ隴崢隴・ｽｰ霑･・ｶ隲ｷ荵晢ｽ帝￡・ｺ髫ｱ髦ｪ・邵ｺ・ｦ隹ｺ・｡邵ｺ・ｮ闖ｴ諛茨ｽ･・ｭ邵ｺ・ｫ鬨ｾ・ｲ郢ｧ阮吶堤ｸｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "MF陷讎雁徐陟募干・帝￡・ｺ髫ｱ繝ｻ,
      },
      mf_bulk_upload_task: {
        message: "Step 4: MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晉判辟秘ｬ・・窶ｲ邵ｺ繧・ｽ顔ｸｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "MF陷ｷ莉｣・邵ｺ・ｮ隰・唱繝ｻ陷牙ｸ吶Ψ郢ｧ・｡郢ｧ・､郢晢ｽｫ邵ｺ讙守舞隲｢荳翫堤ｸｺ髦ｪ窶ｻ邵ｺ繝ｻ・玖撻・ｴ陷ｷ蛹ｻﾂ竏晏徐郢ｧ鬘假ｽｾ・ｼ邵ｺ・ｿ郢ｧ雋橸ｽｮ貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晏ｳｨ・帝ｫ｢荵晢ｿ･",
      },
      import_provider_receipts: {
        message: "Provider陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ郢ｧ・ｹ郢昴・繝｣郢晏干・定楜貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "陞溷､慚夂ｹ晏生ﾎｦ郢敖郢晢ｽｼ邵ｺ・ｮ隴幢ｽｪ陷・ｽｦ騾・・SV郢ｧ讓ｽF驕ｯ竏晉ｲ玖恆髦ｪ竊楢愾謔ｶ・企恷・ｼ郢ｧ阮吶定愾閧ｴ荳千ｸｺ蜉ｱ窶ｻ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "Provider陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ邵ｺ・ｸ鬨ｾ・ｲ郢ｧﾂ",
      },
      mf_bulk_upload: {
        message: "MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晏ｳｨ・定楜貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "MF邵ｺ・ｮ郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晁ご蛻､鬮ｱ・｢郢ｧ蟶晏ｹ慕ｸｺ繝ｻ窶ｻ邵ｲ竏晢ｽｯ・ｾ髮趣ｽ｡隴帛現繝ｻ闕ｳ蛹ｺ蠍檎ｸｺ讎奇ｽｯ・ｾ髮趣ｽ｡郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢晏ｳｨ・帝ｫ｢荵晢ｿ･",
      },
      mf_csv_import: {
        message: "MF CSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晏現・定楜貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "CSV郢ｧ讓ｽF陟厄ｽ｢陟台ｸ岩・隰繝ｻ竏ｴ邵ｺ貅倪鴬邵ｺ蛹ｻ縲定愾謔ｶ・企恷・ｼ邵ｺ・ｿ郢ｧ雋橸ｽｮ貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "MF CSV郢ｧ・､郢晢ｽｳ郢晄亢繝ｻ郢晏現・帝ｫ｢荵晢ｿ･",
      },
      done: {
        message: "邵ｺ蜷ｶ竏狗ｸｺ・ｦ陞ｳ蠕｡・ｺ繝ｻ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧域ｦ隹ｺ・｡郢ｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ・定楜貅ｯ・｡蠕後堤ｸｺ髦ｪ竏ｪ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "隴崢陟募ｾ娯・隴帛沺・ｬ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ郢ｧ繝ｻ縺・ｹ晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ・定楜貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｲ竏ｵ・ｬ・｡隴帷｣ｯﾂｰ騾包ｽｨ邵ｺ・ｫ陋ｯ蜷ｶ竏ｴ邵ｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "隴帛沺・ｬ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ邵ｺ・ｸ",
      },
      fallback: {
        message: "陷・ｽｦ騾・・繝ｻ陷ｿ髢・ｾ蜉ｱ竊楢ｭ弱ｋ菫｣邵ｺ蠕個ｰ邵ｺ荵昶夢邵ｺ・ｦ邵ｺ繝ｻ竏ｪ邵ｺ蜷ｶﾂ繧亥ｳｩ隴・ｽｰ郢ｧ雋橸ｽｾ繝ｻ笆ｲ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "郢晁・繝｣郢ｧ・ｯ郢ｧ・ｨ郢晢ｽｳ郢晏ｳｨﾂｰ郢ｧ逕ｻ諤呵ｭ・ｽｰ霑･・ｶ隲ｷ荵晢ｽ定愾閧ｴ荳千ｸｺ蜷ｶ・狗ｸｺ・ｾ邵ｺ・ｧ隰ｨ・ｰ驕倩ｲ橸ｽｾ繝ｻ笆ｲ邵ｺ・ｦ陷讎雁徐陟募干・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
      },
    };

    const runningModeGuidance = {
      preflight: {
        message: "雋・摩・呵怎・ｦ騾・・・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "陷・ｽｦ騾・・窶ｲ陞ｳ蠕｡・ｺ繝ｻ笘・ｹｧ荵昶穐邵ｺ・ｧ陟輔・・ｩ貅假ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繧・ｽｮ蠕｡・ｺ繝ｻ・ｾ蠕娯・隹ｺ・｡邵ｺ・ｮ隰ｫ蝣ｺ・ｽ諛岩ｲ髢ｾ・ｪ陷崎ｼ斐定ｭ厄ｽｴ隴・ｽｰ邵ｺ霈費ｽ檎ｸｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "雋・摩・呵淦・･驕樔ｹ昶・",
      },
      preflight_mf: {
        message: "MF陷讎雁徐陟募干・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "MF陷讎雁徐陟墓懊・騾・・・定楜蠕｡・ｺ繝ｻ笘・ｹｧ荵昶穐邵ｺ・ｧ邵ｲ繝ｻﾂ・ｲ髯ｦ謔滂ｽｮ蠕｡・ｺ繝ｻ・ｾ蠕後・霑･・ｶ隲ｷ蛹ｺ蟲ｩ隴・ｽｰ郢ｧ雋橸ｽｾ繝ｻ笆ｲ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "雋・摩・呵淦・･驕樔ｹ昶・",
      },
      amazon_download: {
        message: "Amazon 鬯・ｼ懷ｺｶ隴厄ｽｸ陷ｿ髢・ｾ蜉ｱ・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "陷ｿ髢・ｾ蜉ｱ窶ｲ陞ｳ蠕｡・ｺ繝ｻ笘・ｹｧ荵昶・隹ｺ・｡邵ｺ・ｮ陝ｾ・･驕樔ｹ昶・鬨ｾ・ｲ郢ｧ竏夲ｽ玖ｿ･・ｶ隲ｷ荵昶・邵ｺ・ｪ郢ｧ鄙ｫ竏ｪ邵ｺ蜷ｶﾂ繧・ｽｮ蠕｡・ｺ繝ｻ竏ｪ邵ｺ・ｧ邵ｺ髮・ｽｾ繝ｻ笆邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "Amazon 陷ｿ髢・ｾ驤ｴﾂ・ｲ髯ｦ讙取・雎補・竏・,
      },
      amazon_print: {
        message: "Amazon 陷奇ｽｰ陋ｻ・ｷ陷・ｽｦ騾・・・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "鬮ｯ・､陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ邵ｺ・ｮ鬨ｾ・ｲ髯ｦ蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繧・ｽｮ蠕｡・ｺ繝ｻ・ｾ蠕娯・霑･・ｶ隲ｷ荵昶ｲ陷ｿ閧ｴ荳千ｸｺ霈費ｽ檎ｸｲ竏ｵ・ｬ・｡邵ｺ・ｮ隴ｯ莠･繝ｻ邵ｺ・ｸ鬨ｾ・ｲ邵ｺ・ｿ邵ｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "Amazon 陷奇ｽｰ陋ｻ・ｷ霑･・ｶ雎補・竏・,
      },
      rakuten_download: {
        message: "隶鯉ｽｽ陞滂ｽｩ鬯・ｼ懷ｺｶ隴厄ｽｸ陷ｿ髢・ｾ蜉ｱ・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "陷ｿ髢・ｾ蜉ｱ窶ｲ陞ｳ蠕｡・ｺ繝ｻ笘・ｹｧ荵昶・隹ｺ・｡邵ｺ・ｮ陝ｾ・･驕樔ｹ昶・鬨ｾ・ｲ郢ｧ竏夲ｽ玖ｿ･・ｶ隲ｷ荵昶・邵ｺ・ｪ郢ｧ鄙ｫ竏ｪ邵ｺ蜷ｶﾂ繧・ｽｮ蠕｡・ｺ繝ｻ竏ｪ邵ｺ・ｧ邵ｺ髮・ｽｾ繝ｻ笆邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        linkLabel: "隶鯉ｽｽ陞滂ｽｩ 陷ｿ髢・ｾ驤ｴﾂ・ｲ髯ｦ讙取・雎補・竏・,
      },
      rakuten_print: {
        message: "隶鯉ｽｽ陞滂ｽｩ 陷奇ｽｰ陋ｻ・ｷ陷・ｽｦ騾・・・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "鬮ｯ・､陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ邵ｺ・ｮ鬨ｾ・ｲ髯ｦ蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繧・ｽｮ蠕｡・ｺ繝ｻ・ｾ蠕娯・霑･・ｶ隲ｷ荵昶ｲ陷ｿ閧ｴ荳千ｸｺ霈費ｽ檎ｸｲ竏ｵ・ｬ・｡邵ｺ・ｮ隴ｯ莠･繝ｻ邵ｺ・ｸ鬨ｾ・ｲ邵ｺ・ｿ邵ｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "隶鯉ｽｽ陞滂ｽｩ 陷奇ｽｰ陋ｻ・ｷ霑･・ｶ雎補・竏・,
      },
      mf_reconcile: {
        message: "MF驕ｯ竏晉ｲ狗ｸｺ蟶呻ｽ定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "驕ｯ竏晉ｲ狗ｸｺ蟶幢ｽｮ蠕｡・ｺ繝ｻ竏ｪ邵ｺ・ｧ隴会ｽｫ邵ｺ荳岩凰陟輔・笆邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繧・ｽｮ蠕｡・ｺ繝ｻ・ｾ蠕娯・闕ｳ蛹ｺ蠍檎ｸｺ髦ｪ繝ｻ闖ｴ諛医・霑･・ｶ雎補・窶ｲ隴厄ｽｴ隴・ｽｰ邵ｺ霈費ｽ檎ｸｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
        linkLabel: "MF驕ｯ竏晉ｲ玖ｿ･・ｶ雎補・竏・,
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
        message: runningGuidance?.message || `${runningMode} 郢ｧ雋橸ｽｮ貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ・｡,
        reason:
          runningGuidance?.reason ||
          "陋ｻ・･邵ｺ・ｮ陷・ｽｦ騾・・窶ｲ鬨ｾ・ｲ髯ｦ蠕｡・ｸ・ｭ邵ｺ・ｧ邵ｺ蜷ｶﾂ繧・ｽｮ蠕｡・ｺ繝ｻ笘・ｹｧ荵昶穐邵ｺ・ｧ陟輔・・ｩ貅假ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        href: runningTargetHref,
        linkLabel: runningGuidance?.linkLabel || (runningTargetHref === FALLBACK_WIZARD_HREF ? "隰・洸・ｰ繝ｻ・帝￡・ｺ髫ｱ繝ｻ : "鬨ｾ・ｲ隰仙干・帝￡・ｺ髫ｱ繝ｻ),
      };
    }

    const reasonHint = {
      preflight_required: {
        reason: "雋・摩・咏ｹ晁ｼ釆溽ｹ晢ｽｼ邵ｺ譴ｧ謔ｴ陞ｳ蠕｡・ｺ繝ｻ縲堤ｸｺ蜷ｶﾂ繧・穐邵ｺ螢ｼ辯戊ｬ蜊・ｨ・ｭ陞ｳ螢ｹ繝ｻ陞ｳ蠕｡・ｺ繝ｻ窶ｲ陟｢繝ｻ・ｦ竏壹堤ｸｺ蜷ｶﾂ繝ｻ,
      },
      source_download_required: {
        message: "Amazon 邵ｺ蛹ｺ・･・ｽ陞滂ｽｩ邵ｺ・ｮ邵ｺ・ｩ邵ｺ・｡郢ｧ蟲ｨﾂｰ邵ｺ・ｮ鬯・ｼ懷ｺｶ隴厄ｽｸ陷ｿ髢・ｾ蜉ｱ・定怦蛹ｻ竊楢楜貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "陝・ｻ｣竊醍ｸｺ荳岩・郢ｧ繝ｻ驕会ｽｾ陋ｻ繝ｻ繝ｻ陝・ｽｾ髮趣ｽ｡隴帛現繝ｧ郢晢ｽｼ郢ｧ・ｿ郢ｧ雋槫徐陟募干・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
      },
      amazon_download_required: {
        message: "Amazon 邵ｺ・ｮ鬯・ｼ懷ｺｶ隴厄ｽｸ郢ｧ雋槫徐陟募干・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "陝・ｽｾ髮趣ｽ｡隴帑ｺ･繝ｻ郢ｧ雋槫徐陟募干笘・ｹｧ荵昶・隹ｺ・｡邵ｺ・ｮ鬮ｯ・､陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ陝ｾ・･驕樔ｹ昶・鬨ｾ・ｲ郢ｧ竏壺穐邵ｺ蜷ｶﾂ繝ｻ,
      },
      rakuten_download_required: {
        message: "隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｮ鬯・ｼ懷ｺｶ隴厄ｽｸ郢ｧ雋槫徐陟募干・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "陝・ｽｾ髮趣ｽ｡隴帑ｺ･繝ｻ郢ｧ雋槫徐陟募干笘・ｹｧ荵昶・隹ｺ・｡邵ｺ・ｮ鬮ｯ・､陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ陝ｾ・･驕樔ｹ昶・鬨ｾ・ｲ郢ｧ竏壺穐邵ｺ蜷ｶﾂ繝ｻ,
      },
      amazon_print_pending: {
        message: "Amazon 邵ｺ・ｮ鬮ｯ・､陞溷・・ｨ・ｭ陞ｳ螢ｹ繝ｻ陷奇ｽｰ陋ｻ・ｷ陝・ｽｾ髮趣ｽ｡郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "鬮ｯ・､陞滄摩・ｯ・ｾ髮趣ｽ｡邵ｺ・ｮ驕抵ｽｺ陞ｳ螢ｹ竊定怺・ｰ陋ｻ・ｷ陞ｳ蠕｡・ｺ繝ｻ・帝勗蠕娯鴬邵ｺ・ｨ隹ｺ・｡陝ｾ・･驕樔ｹ昶・鬨ｾ・ｲ邵ｺ・ｿ邵ｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
      },
      rakuten_print_pending: {
        message: "隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｮ鬮ｯ・､陞溷・・ｨ・ｭ陞ｳ螢ｹ繝ｻ陷奇ｽｰ陋ｻ・ｷ陝・ｽｾ髮趣ｽ｡郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "鬮ｯ・､陞滄摩・ｯ・ｾ髮趣ｽ｡邵ｺ・ｮ驕抵ｽｺ陞ｳ螢ｹ竊定怺・ｰ陋ｻ・ｷ陞ｳ蠕｡・ｺ繝ｻ・帝勗蠕娯鴬邵ｺ・ｨ隹ｺ・｡陝ｾ・･驕樔ｹ昶・鬨ｾ・ｲ邵ｺ・ｿ邵ｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ,
      },
      provider_ingest_pending: {
        message: "陞溷､慚咾SV邵ｺ・ｮ陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ郢ｧ雋橸ｽｮ貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "Amazon/隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｧ陷ｿ髢・ｾ蜉ｱ・邵ｺ髦ｪ・檎ｸｺ・ｪ邵ｺ繝ｻ繝ｻ郢ｧ雋槭・鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖邵ｺ荵晢ｽ芽愾謔ｶ・企恷・ｼ郢ｧ阮吶堤ｸｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
      },
      mf_reconcile_ready: {
        message: "MF鬨ｾ・｣隰ｳ・ｺ邵ｺ・ｮ驕ｯ竏晉ｲ狗ｸｺ蟶幢ｽｮ貅ｯ・｡蠕娯・鬨ｾ・ｲ郢ｧ竏壺ｻ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
        reason: "陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ雋ょ現竏ｩ郢昴・繝ｻ郢ｧ・ｿ郢ｧ讓ｽF邵ｺ・ｮ闕ｳ蛹ｺ蠍檎ｸｺ蝣ｺ・ｽ諛医・邵ｺ・ｸ陷ｿ閧ｴ荳千ｸｺ蜷ｶ・玖ｲ・摩・咏ｸｺ譴ｧ邏帷ｸｺ繝ｻ竏ｪ邵ｺ蜉ｱ笳・ｸｲ繝ｻ,
      },
      workflow_complete: {
        message: "邵ｺ蜷ｶ竏狗ｸｺ・ｦ陞ｳ蠕｡・ｺ繝ｻ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧域ｦ隹ｺ・｡郢ｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ・定楜貅ｯ・｡蠕後堤ｸｺ髦ｪ竏ｪ邵ｺ蜷ｶﾂ繝ｻ,
        reason: "隴崢驍ｨ繧会ｽ｢・ｺ髫ｱ髦ｪ竊堤ｸｺ蜉ｱ窶ｻ隴帛沺・ｬ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ郢ｧ繝ｻ縺・ｹ晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ縲定ｰｺ・｡隴帛沺・ｺ髢・咏ｸｺ・ｫ鬨ｾ・ｲ郢ｧ阮吶堤ｸｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ,
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
      linkLabel: guidance.linkLabel || (href === FALLBACK_WIZARD_HREF ? "隰・洸・ｰ繝ｻ・帝￡・ｺ髫ｱ繝ｻ : ""),
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
        button.title = "闔画じ繝ｻ隰・洸・ｰ繝ｻ・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｮ邵ｺ貅假ｽ・ｫ｢蜿･・ｧ荵昴堤ｸｺ髦ｪ竏ｪ邵ｺ蟶呻ｽ鍋ｸｲ繝ｻ;
      } else if (blockedByOrder) {
        button.title = "邵ｺ・ｾ邵ｺ・ｰ邵ｺ阮吶・隰・洸・ｰ繝ｻ繝ｻ陞ｳ貅ｯ・｡蠕後堤ｸｺ髦ｪ竏ｪ邵ｺ蟶呻ｽ鍋ｸｲ繝ｻ;
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
          button.title = "闔画じ繝ｻ隰・洸・ｰ繝ｻ・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｮ邵ｺ貅假ｽ∫ｹｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ縲堤ｸｺ髦ｪ竏ｪ邵ｺ蟶呻ｽ鍋ｸｲ繝ｻ;
        } else if (!allowed && !checklistComplete) {
          button.title = "Amazon邵ｺ・ｾ邵ｺ貅倥・隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｧ邵ｲ遒∝求陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ繝ｻ莠･・ｮ蠕｡・ｺ繝ｻ・ｨ蛟ｬ鮖ｸ邵ｺ・ｾ邵ｺ・ｧ繝ｻ蟲ｨﾂ讎奇ｽｮ蠕｡・ｺ繝ｻ・ｾ蠕娯・陞ｳ貅ｯ・｡蠕後堤ｸｺ髦ｪ竏ｪ邵ｺ蜷ｶﾂ繧・穐邵ｺ貅伉竏ｵ諤ｦ隹ｺ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ陷鷹亂繝ｻ驕抵ｽｺ髫ｱ蝓ｼ・ｰ繝ｻ蟯ｼ郢ｧ蛛ｵ笘・ｸｺ・ｹ邵ｺ・ｦ郢昶・縺臥ｹ昴・縺醍ｸｺ蜷ｶ・玖｢繝ｻ・ｦ竏壺ｲ邵ｺ繧・ｽ顔ｸｺ・ｾ邵ｺ蜷ｶﾂ繝ｻ;
        } else if (!allowed) {
          button.title = "Amazon邵ｺ・ｾ邵ｺ貅倥・隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｧ邵ｲ遒∝求陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ繝ｻ莠･・ｮ蠕｡・ｺ繝ｻ・ｨ蛟ｬ鮖ｸ邵ｺ・ｾ邵ｺ・ｧ繝ｻ蟲ｨﾂ讎奇ｽｮ蠕｡・ｺ繝ｻ・ｾ蠕娯・陞ｳ貅ｯ・｡蠕後堤ｸｺ髦ｪ竏ｪ邵ｺ蜷ｶﾂ繝ｻ;
        } else if (!checklistComplete) {
          button.title = "隴帛沺・ｬ・｡郢ｧ・ｯ郢晢ｽｭ郢晢ｽｼ郢ｧ・ｺ陷鷹亂繝ｻ驕抵ｽｺ髫ｱ蝓ｼ・ｰ繝ｻ蟯ｼ郢ｧ蛛ｵ笘・ｸｺ・ｹ邵ｺ・ｦ郢昶・縺臥ｹ昴・縺醍ｸｺ蜉ｱ窶ｻ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ;
        } else {
          button.title = "";
        }
      } else {
        // For archive_outputs button, keep original logic
        button.disabled = blockedByRunning || !allowed;
        if (blockedByRunning) {
          button.title = "闔画じ繝ｻ隰・洸・ｰ繝ｻ・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｮ邵ｺ貅假ｽ∫ｹｧ・｢郢晢ｽｼ郢ｧ・ｫ郢ｧ・､郢晄じ縲堤ｸｺ髦ｪ竏ｪ邵ｺ蟶呻ｽ鍋ｸｲ繝ｻ;
        } else if (!allowed) {
          button.title = "Amazon邵ｺ・ｾ邵ｺ貅倥・隶鯉ｽｽ陞滂ｽｩ邵ｺ・ｧ邵ｲ遒∝求陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ繝ｻ莠･・ｮ蠕｡・ｺ繝ｻ・ｨ蛟ｬ鮖ｸ邵ｺ・ｾ邵ｺ・ｧ繝ｻ蟲ｨﾂ讎奇ｽｮ蠕｡・ｺ繝ｻ・ｾ蠕娯・陞ｳ貅ｯ・｡蠕後堤ｸｺ髦ｪ竏ｪ邵ｺ蜷ｶﾂ繝ｻ;
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
        button.title = "闔画じ繝ｻ隰・洸・ｰ繝ｻ・定楜貅ｯ・｡蠕｡・ｸ・ｭ邵ｺ・ｮ邵ｺ貅假ｽ・ｫ｢蜿･・ｧ荵昴堤ｸｺ髦ｪ竏ｪ邵ｺ蟶呻ｽ鍋ｸｲ繝ｻ;
      } else if (blockedByPreflight) {
        button.title = "陷亥現竊楢ｬ・洸・ｰ繝ｻ邵ｲ譴ｧ・ｺ髢・咏ｸｲ髦ｪ・定楜貅ｯ・｡蠕鯉ｼ邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ;
      } else {
        button.title = "";
      }
    });
  }

  function applyProviderAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const providers = data && typeof data === "object" ? data.providers : null;
    const sourceStatus = providers && typeof providers === "object" ? providers.source : null;
    const sourceConfigured = Boolean(sourceStatus && sourceStatus.configured);
    const sourceExists = Boolean(sourceStatus && sourceStatus.exists);
    document.querySelectorAll("[data-provider-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const blockedByRunning = Boolean(runningMode);
      const action = String(button.dataset.providerAction || "");
      if (action === "open_provider_source") {
        const blockedBySource = !sourceConfigured || !sourceExists;
        button.disabled = blockedByRunning || blockedBySource;
        if (blockedByRunning) {
          button.title = "別の処理が実行中です。";
        } else if (!sourceConfigured) {
          button.title = "Provider source folder is not configured.";
        } else if (!sourceExists) {
          button.title = "Provider source folder not found.";
        } else {
          button.title = "";
        }
      } else {
        button.disabled = blockedByRunning;
        button.title = blockedByRunning ? "別の処理が実行中です。" : "";
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
      return "郢ｧ・ｵ郢晄ｧｭﾎ懃ｹ晢ｽｼ: 隰・洸・ｰ繝ｻ郢ｧ雋橸ｽｮ貅ｯ・｡蠕｡・ｸ・ｭ...";
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
      return "郢ｧ・ｵ郢晄ｧｭﾎ懃ｹ晢ｽｼ: 隴幢ｽｪ陞ｳ貅ｯ・｡繝ｻ;
    }
    if (!hasDraftResult) {
      return `郢ｧ・ｵ郢晄ｧｭﾎ懃ｹ晢ｽｼ: 隴幢ｽｪ雎ｺ・ｻ闔我ｼ慊蜻ｵ・｣繝ｻ${missingCandidates}闔会ｽｶ / 闕ｳ蛹ｺ蠍檎ｸｺ蝣ｺ・ｽ諛医・邵ｺ・ｯ隴幢ｽｪ陞ｳ貅ｯ・｡蠖｢;
    }
    return `郢ｧ・ｵ郢晄ｧｭﾎ懃ｹ晢ｽｼ: 隴幢ｽｪ雎ｺ・ｻ闔我ｼ慊蜻ｵ・｣繝ｻ${missingCandidates}闔会ｽｶ / 闕ｳ蛹ｺ蠍檎ｸｺ蝣ｺ・ｽ諛医・ ${created}/${targetsTotal}闔会ｽｶ繝ｻ莠･・､・ｱ隰ｨ繝ｻ${failed}闔会ｽｶ繝ｻ闕・
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

  function fileNameFromPath(rawPath) {
    const path = String(rawPath || "").trim();
    if (!path) return "";
    const normalized = path.replace(/\\/g, "/");
    const parts = normalized.split("/");
    return parts.length > 0 ? parts[parts.length - 1] : normalized;
  }

  function buildProviderSourceSummarySuffix(scanSummary, pendingFiles) {
    const summary = scanSummary && typeof scanSummary === "object" ? scanSummary : {};
    const matched = toCount(summary.matched);
    const checked = toCount(summary.checked);
    const pdfFiles = toCount(summary.pdf_files);
    const ignoredOutOfMonth = toCount(summary.ignored_out_of_month);
    const ignoredUnmatchedName = toCount(summary.ignored_unmatched_name);
    const ignoredNonPdf = toCount(summary.ignored_non_pdf);
    const ignoredHidden = toCount(summary.ignored_hidden);
    const parts = [];
    const effectivePending = Math.max(0, pendingFiles);
    if (checked > 0) {
      parts.push(`確認済み: ${checked}件`);
    }
    if (pdfFiles > 0) {
      parts.push(`PDF: ${pdfFiles}件`);
    }
    if (effectivePending > 0) {
      parts.push(`対象月一致: ${effectivePending}件`);
    }
    if (matched > 0 && pendingFiles === 0) {
      parts.push(`一致候補: ${matched}件`);
    }
    if (ignoredOutOfMonth > 0) {
      parts.push(`年月非一致: ${ignoredOutOfMonth}件`);
    }
    if (ignoredNonPdf > 0) {
      parts.push(`PDF以外: ${ignoredNonPdf}件`);
    }
    if (ignoredHidden > 0) {
      parts.push(`隠しファイル: ${ignoredHidden}件`);
    }
    const scanError = String(summary.scan_error || "").trim();
    if (scanError) {
      const friendlyScanError = scanError
        .replace("failed_to_scan_metadata", "メタ情報の走査に失敗")
        .replace("scan_metadata_skipped_for_missing_ym", "年月指定がありません")
        .replace("source_is_not_a_directory", "ディレクトリではありません");
      parts.push(`状態: ${friendlyScanError}`);
    }
    return parts.length > 0 ? ` (${parts.join(", ")})` : "";
  }

  function buildProviderSourceSummaryText(rawSource) {
    const source = rawSource && typeof rawSource === "object" ? rawSource : {};
    const configured = Boolean(source.configured);
    const exists = Boolean(source.exists);
    const pending = toCount(source.pending_files);
    const path = String(source.path || "").trim();
    const scanSummary = source.scan_summary && typeof source.scan_summary === "object" ? source.scan_summary : {};
    const sampleMatched = Array.isArray(scanSummary.sample_matched)
      ? scanSummary.sample_matched.map(fileNameFromPath).filter(Boolean).slice(0, 3)
      : [];
    const detailsSuffix = buildProviderSourceSummarySuffix(scanSummary, pending);
    const sampleText = sampleMatched.length > 0 ? ` e.g. ${sampleMatched.join(", ")}` : "";

    if (!configured) {
      return "受信元フォルダが未設定です。";
    }
    if (!exists) {
      return `受信元フォルダが見つかりません: ${path || "(未設定)"}`;
    }
    const checked = toCount(scanSummary.checked);
    if (pending === 0 && checked > 0) {
      const scanHint = String(scanSummary.scan_error || "").trim();
      const status = scanHint ? `（${scanHint}）` : "";
      return `${path}: 選択月に一致するファイルは見つかりませんでした${status}。確認済み: ${checked}件。${sampleText ? `例: ${sampleText}` : ""}${detailsSuffix}`;
    }
    if (!path) {
      return `受信元フォルダ準備完了${detailsSuffix}`;
    }
    if (sampleText) {
      return `${path}: 例: ${sampleText}${detailsSuffix}`;
    }
    return `${path}${detailsSuffix}`;
  }

  function renderProviderSourceSummary(rawSource, fallbackMessage = "") {
    const source = rawSource && typeof rawSource === "object" ? rawSource : {};
    const summaryEl = document.querySelector("[data-provider-source-summary]");
    if (!summaryEl) return;
    const text = fallbackMessage || buildProviderSourceSummaryText(rawSource);
    summaryEl.textContent = text;
    const guideEl = document.querySelector("[data-provider-source-setup-guide]");
    if (guideEl) {
      const needsGuide =
        Boolean(fallbackMessage) ||
        !Boolean(source.configured) ||
        !Boolean(source.exists) ||
        text.toLowerCase().includes("not configured") ||
        text.toLowerCase().includes("not found");
      guideEl.hidden = !needsGuide;
      const guideLinkEl = guideEl.querySelector("a");
      if (guideLinkEl) {
        guideLinkEl.href = PROVIDER_SOURCE_SETUP_GUIDE_URL;
      }
    }
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
        renderNextStep("郢ｧ・ｹ郢昴・繝｣郢晉､ｼ諞ｾ隲ｷ荵昴・陷ｿ髢・ｾ蜉ｱ竊楢棔・ｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧・・髫ｱ・ｭ邵ｺ・ｿ髴趣ｽｼ邵ｺ・ｿ邵ｺ蜉ｱ窶ｻ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, null);
        document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
        applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
        applyManualAvailability({ running_mode: "" });
        renderProviderSourceSummary(null, "Provider source folder status is unavailable.");
        renderMfSummary(null, "郢ｧ・ｵ郢晄ｧｭﾎ懃ｹ晢ｽｼ: 郢ｧ・ｹ郢昴・繝｣郢晉､ｼ諞ｾ隲ｷ荵昴・陷ｿ髢・ｾ蜉ｱ竊楢棔・ｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
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
      renderProviderSourceSummary(data.providers?.source);
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
        preflight: "隰・洸・ｰ繝ｻ 雋・摩・・,
        amazon_download: "隰・洸・ｰ繝ｻ Amazon 陷ｿ髢・ｾ繝ｻ,
        amazon_decide_print: "隰・洸・ｰ繝ｻ Amazon 鬮ｯ・､陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ繝ｻ莠･・ｮ蠕｡・ｺ繝ｻ・ｨ蛟ｬ鮖ｸ邵ｺ・ｾ邵ｺ・ｧ繝ｻ繝ｻ,
        rakuten_download: "隰・洸・ｰ繝ｻ 隶鯉ｽｽ陞滂ｽｩ 陷ｿ髢・ｾ繝ｻ,
        rakuten_decide_print: "隰・洸・ｰ繝ｻ 隶鯉ｽｽ陞滂ｽｩ 鬮ｯ・､陞滓じ繝ｻ陷奇ｽｰ陋ｻ・ｷ繝ｻ莠･・ｮ蠕｡・ｺ繝ｻ・ｨ蛟ｬ鮖ｸ邵ｺ・ｾ邵ｺ・ｧ繝ｻ繝ｻ,
        provider_ingest: "隰・洸・ｰ繝ｻ 陷茨ｽｱ鬨ｾ螢ｹ繝ｵ郢ｧ・ｩ郢晢ｽｫ郢敖陷ｿ謔ｶ・企恷・ｼ邵ｺ・ｿ",
        mf_bulk_upload_task: "隰・洸・ｰ繝ｻ MF闕ｳﾂ隲｡・ｬ郢ｧ・｢郢昴・繝ｻ郢晢ｽｭ郢晢ｽｼ郢昴・,
        mf_reconcile: "隰・洸・ｰ繝ｻ MF驕ｯ竏晉ｲ狗ｹ晢ｽｻ闕ｳ蛹ｺ蠍檎ｸｺ蝣ｺ・ｽ諛医・",
      };
      if (!window.__stepState) {
        window.__stepState = stepStates;
      } else {
        Object.keys(stepStates).forEach((key) => {
          if (key === "mf_reconcile") return;
          if (window.__stepState[key] && window.__stepState[key] !== "done" && stepStates[key] === "done") {
            showToast(`${labels[key]}邵ｺ謔滂ｽｮ蠕｡・ｺ繝ｻ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ・｡, "success");
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
      renderNextStep("郢ｧ・ｹ郢昴・繝｣郢晉､ｼ諞ｾ隲ｷ荵昴・陷ｿ髢・ｾ蜉ｱ竊楢棔・ｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繧・・髫ｱ・ｭ邵ｺ・ｿ髴趣ｽｼ邵ｺ・ｿ邵ｺ蜉ｱ窶ｻ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, null);
      document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
      applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
      applyManualAvailability({ running_mode: "" });
      applyProviderAvailability({ running_mode: "", preflight: {} });
      renderProviderSourceSummary(null, "Failed to refresh provider status.");
      renderMfSummary(null, "郢ｧ・ｵ郢晄ｧｭﾎ懃ｹ晢ｽｼ: 郢ｧ・ｹ郢昴・繝｣郢晉､ｼ諞ｾ隲ｷ荵昴・陷ｿ髢・ｾ蜉ｱ竊楢棔・ｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ);
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
          showToast("邵ｺ阮吶・隰・洸・ｰ繝ｻ繝ｻ邵ｺ・ｾ邵ｺ・ｰ陞ｳ貅ｯ・｡蠕後堤ｸｺ髦ｪ竏ｪ邵ｺ蟶呻ｽ鍋ｸｲ繧茨ｽｬ・｡邵ｺ・ｮ隰・洸・ｰ繝ｻ・｡莠･繝ｻ郢ｧ蝣､・｢・ｺ髫ｱ髦ｪ・邵ｺ・ｦ邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ, "error");
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
        const message = "陞ｳ貅ｯ・｡蠕後・陋帶㊧・ｭ・｢邵ｺ・ｫ陞滂ｽｱ隰ｨ蜉ｱ・邵ｺ・ｾ邵ｺ蜉ｱ笳・ｸｲ繝ｻ;
        showError(message);
        showToast(message, "error");
        return;
      }
      const message = "陋帶㊧・ｭ・｢郢晢ｽｪ郢ｧ・ｯ郢ｧ・ｨ郢ｧ・ｹ郢晏現・帝ｨｾ竏ｽ・ｿ・｡邵ｺ蜉ｱ竏ｪ邵ｺ蜉ｱ笳・ｸｲ繧・溽ｹｧ・ｰ隴厄ｽｴ隴・ｽｰ郢ｧ蛛ｵ笙陟輔・笆邵ｺ荳岩味邵ｺ霈費ｼ樒ｸｲ繝ｻ;
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
