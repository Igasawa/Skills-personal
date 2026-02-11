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
  let autoReloadScheduled = false;
  const REQUEST_TIMEOUT_MS = 12000;
  const STEP_REFRESH_STALE_MS = 15000;
  const archiveStateOverrides = Object.create(null);

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

    // セクション全体のステータスクラスを更新
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
        showToast("実行に失敗しました。ログを確認してください。", "error");
      } else if (status === "success") {
        showToast("実行が完了しました。", "success");
      }
    }
    if (status) {
      runStatusById[runId] = status;
    }

    if (status === "failed") {
      showError("実行に失敗しました。ログを確認してください。");
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
    showToast("実行を開始しています...", "success");

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
        logEl.textContent = "実行を開始しました。ログを更新中...";
      }

      awaitingRunFinalization = true;
      updateRunSummary({
        run_id: data.run_id,
        status: "running",
        started_at: new Date().toLocaleString("ja-JP", { hour12: false }),
        params: { year: payload.year, month: payload.month },
      });
      runStatusById[data.run_id] = "running";
      showToast("実行を開始しました。", "success");

      startLogPolling(data.run_id);
      refreshLog(data.run_id);
      scheduleStepSync();
    } catch {
      awaitingRunFinalization = false;
      const message = "実行開始に失敗しました。再試行してください。";
      showError(message);
      showToast(message, "error");
    }
  }

  function nextYm(ym) {
    const text = String(ym || "").trim();
    const match = text.match(/^(\d{4})-(\d{2})$/);
    if (!match) return "";
    const year = Number.parseInt(match[1], 10);
    const month = Number.parseInt(match[2], 10);
    if (!Number.isInteger(year) || !Number.isInteger(month)) return "";
    if (month >= 12) return `${year + 1}-01`;
    return `${year}-${String(month + 1).padStart(2, "0")}`;
  }

  function setYmToForm(ym) {
    const text = String(ym || "").trim();
    const match = text.match(/^(\d{4})-(\d{2})$/);
    if (!match || !form) return;
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    if (yearEl) yearEl.value = String(Number.parseInt(match[1], 10));
    if (monthEl) monthEl.value = String(Number.parseInt(match[2], 10));
  }

  function prependArchiveHistoryRow(entry) {
    if (!entry || typeof entry !== "object") return;
    const list = document.querySelector("[data-archive-history-list]");
    if (!(list instanceof HTMLElement)) return;
    const empty = list.querySelector("[data-archive-history-empty]");
    if (empty) empty.remove();

    const ym = String(entry.ym || "").trim();
    const ts = String(entry.ts || "").trim();
    const actionLabel = String(entry.action_label || "").trim() || "アーカイブ";
    const href = String(entry.archive_url || "").trim() || (ym ? `/runs/${ym}/archived-receipts` : "#");

    const item = document.createElement("li");
    item.className = "archive-history-item";
    const text = document.createElement("span");
    text.className = "muted";
    text.textContent = `${ts || "-"} / ${ym || "-"} / ${actionLabel}`;
    const link = document.createElement("a");
    link.className = "secondary";
    link.href = href;
    link.textContent = "アーカイブを開く";
    item.appendChild(text);
    item.appendChild(link);
    list.prepend(item);
  }

  async function runArchiveAction(action, buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("年月を入力してください。", "error");
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
    showToast(isMonthClose ? "月次クローズを実行しています..." : "アーカイブを作成しています...", "success");

    try {
      const endpoint = isMonthClose ? `/api/month-close/${ym}` : `/api/archive/${ym}`;
      const res = await fetch(endpoint, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || (isMonthClose ? "月次クローズに失敗しました。" : "アーカイブ作成に失敗しました。"));
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
      const cleanupSuffix = Number.isFinite(cleanupRemoved) ? ` / クリーンアップ ${cleanupRemoved}件` : "";
      const baseMessage = isMonthClose ? "月次クローズが完了しました" : "アーカイブを作成しました";
      let message = archivedTo ? `${baseMessage}: ${archivedTo}${cleanupSuffix}` : `${baseMessage}。${cleanupSuffix}`;
      if (isMonthClose) {
        const next = nextYm(ym);
        if (next) {
          setYmToForm(next);
          if (window.__stepState) window.__stepState = null;
          message += ` / ウィザードを ${next} に切り替えました。`;
        }
      }
      prependArchiveHistoryRow(data.history_entry || null);
      showToast(message, "success");
    } catch {
      const message = normalizedAction === "month_close" ? "月次クローズに失敗しました。" : "アーカイブ作成に失敗しました。";
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
      showToast("年月を入力してください。", "error");
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
        const message = toFriendlyMessage(data.detail || "共通フォルダを開けませんでした。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath ? `共通フォルダを開きました: ${openedPath}` : "共通フォルダを開きました。";
      showToast(message, "success");
    } catch {
      const message = "共通フォルダを開けませんでした。";
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
      showToast("年月を入力してください。", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("手動領収書の取り込みを開始します...", "success");
    try {
      const res = await fetch(`/api/manual/${ym}/import`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "領収書取り込みに失敗しました。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.found_pdfs ?? 0), 10) || 0;
      const imported = Number.parseInt(String(data.imported ?? 0), 10) || 0;
      const skipped = Number.parseInt(String(data.skipped_duplicates ?? 0), 10) || 0;
      const failed = Number.parseInt(String(data.failed ?? 0), 10) || 0;
      const message = `手動領収書取り込み: 発見 ${found}件 / 取込 ${imported}件 / 重複 ${skipped}件 / 失敗 ${failed}件`;
      showToast(message, failed > 0 ? "error" : "success");
      if (failed > 0) {
        showError(message);
      }
    } catch {
      const message = "領収書取り込みに失敗しました。";
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
      showToast("年月を入力してください。", "error");
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
        const message = toFriendlyMessage(data.detail || "MF一括アップロード用フォルダを開けませんでした。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath
        ? `MF一括アップロード用フォルダを開きました: ${openedPath}`
        : "MF一括アップロード用フォルダを開きました。";
      showToast(message, "success");
    } catch {
      const message = "MF一括アップロード用フォルダを開けませんでした。";
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
      showToast("年月を入力してください。", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("MF一括アップロードを開始します...", "success");
    try {
      const res = await fetch(`/api/mf-bulk-upload/${ym}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "MF一括アップロードに失敗しました。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.files_found ?? 0), 10) || 0;
      const submitted = Number.parseInt(String(data.submitted_count ?? 0), 10) || 0;
      const queued = Number.parseInt(String(data.queued_count ?? 0), 10) || 0;
      const readCount = Number.parseInt(String(data.read_count ?? 0), 10) || 0;
      const archivedDir = String(data.archived_dir || "").trim();
      const details = archivedDir ? ` / 保管: ${archivedDir}` : "";
      const message = `MF一括アップロード: 発見 ${found}件 / 読込 ${readCount}件 / キュー ${queued}件 / 送信 ${submitted}件${details}`;
      showToast(message, "success");
    } catch {
      const message = "MF一括アップロードに失敗しました。";
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
      showToast("年月を入力してください。", "error");
      return;
    }
    if (!normalizedProvider) {
      showToast("対象サービスが指定されていません。", "error");
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
        const message = toFriendlyMessage(data.detail || "サービス別フォルダを開けませんでした。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const label = providerLabel(normalizedProvider);
      const message = openedPath ? `${label}フォルダを開きました: ${openedPath}` : `${label}フォルダを開きました。`;
      showToast(message, "success");
    } catch {
      const message = "サービス別フォルダを開けませんでした。";
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
      showToast("年月を入力してください。", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
      showToast("共通フォルダの領収書を取り込み中...", "success");
    try {
      const res = await fetch(`/api/providers/${ym}/import`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "共通フォルダ取り込みに失敗しました。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.found_files ?? 0), 10) || 0;
      const imported = Number.parseInt(String(data.imported ?? 0), 10) || 0;
      const skipped = Number.parseInt(String(data.skipped_duplicates ?? 0), 10) || 0;
      const failed = Number.parseInt(String(data.failed ?? 0), 10) || 0;
      const message = `共通フォルダ取り込み: 検出 ${found}件 / 取込 ${imported}件 / 重複 ${skipped}件 / 失敗 ${failed}件`;
      showToast(message, failed > 0 ? "error" : "success");
      if (failed > 0) showError(message);
    } catch {
      const message = "共通フォルダ取り込みに失敗しました。";
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
      showToast("年月を入力してください。", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("共通フォルダ取込済みのPDFを結合しています...", "success");
    try {
      const res = await fetch(`/api/providers/${ym}/print-run`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "共通フォルダ一括印刷の開始に失敗しました。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const count = Number.parseInt(String(data.count ?? 0), 10) || 0;
      const message = `共通フォルダ取込分の結合PDFを開きました（対象 ${Math.max(0, count)} 件）。`;
      showToast(message, "success");
    } catch {
      const message = "共通フォルダ一括印刷の開始に失敗しました。";
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
      showToast("年月を入力してください。", "error");
      return;
    }
    const labelByStep = {
      amazon_download: "Amazonカード / 取得",
      amazon_decide_print: "Amazonカード / 除外判断・印刷（完了記録まで）",
      rakuten_download: "楽天カード / 取得",
      rakuten_decide_print: "楽天カード / 除外判断・印刷（完了記録まで）",
    };
    const label = labelByStep[String(stepId || "")] || String(stepId || "");
    const confirmed = window.confirm(`「${label}」をリセットします。必要なら実行中ジョブを停止します。続行しますか？`);
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
      showToast(cancelledCount > 0 ? `リセット完了: 実行中ジョブ ${cancelledCount} 件を停止しました。` : "リセットが完了しました。", "success");
      scheduleStepSync();
      if (activeLogRunId) {
        refreshLog(activeLogRunId);
      }
    } catch {
      const message = "リセットに失敗しました。";
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
    const year = String(yearEl?.value || "").padStart(4, "0");
    const month = String(monthEl?.value || "").padStart(2, "0");
    if (!year || !month || year === "0000") return "";
    return `${year}-${month}`;
  }

  function setStepStatus(id, state) {
    const el = document.querySelector(`[data-step-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (id === "mf_reconcile" && state !== "running") {
      el.textContent = "実行可";
      el.classList.add("pending");
      return;
    }
    if (state === "done") {
      el.textContent = "完了";
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "実行中";
      el.classList.add("running");
      return;
    }
    el.textContent = "未実行";
    el.classList.add("pending");
  }

  function setTaskStatus(id, state) {
    const el = document.querySelector(`[data-task-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (state === "done") {
      el.textContent = "完了";
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "実行中";
      el.classList.add("running");
      return;
    }
    el.textContent = "未実行";
    el.classList.add("pending");
  }

  function renderNextStep(message, href) {
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
    if (!href) return;
    const link = document.createElement("a");
    link.href = href;
    link.className = "secondary";
    link.textContent = "開く";
    wizardNext.appendChild(link);
  }

  function inferNextStepFromFlags(data) {
    if (!data.preflight?.done) return "preflight";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const amazonPending = Boolean(data.amazon?.downloaded && !amazonDone);
    const rakutenPending = Boolean(data.rakuten?.downloaded && !rakutenDone);
    const bothDownloaded = Boolean(data.amazon?.downloaded && data.rakuten?.downloaded);
    const providerPending = (Number.parseInt(String(data.providers?.pending_total ?? 0), 10) || 0) > 0;
    if (amazonPending) return "amazon_decide_print";
    if (rakutenPending) return "rakuten_decide_print";
    if (!data.amazon?.downloaded && !data.rakuten?.downloaded) return "amazon_or_rakuten_download";
    if (!data.amazon?.downloaded) return "amazon_download";
    if (!data.rakuten?.downloaded) return "rakuten_download";
    const mfDone = Boolean(data.mf?.step_done ?? data.mf?.reconciled);
    if (!mfDone && providerPending) return "provider_ingest";
    if (!mfDone && bothDownloaded && (amazonDone || rakutenDone)) return "mf_reconcile";
    if (!mfDone) return "mf_reconcile";
    return "done";
  }

  function resolveNextStep(data) {
    const inferred = inferNextStepFromFlags(data);
    // Keep UI guidance consistent with current flags even if API next_step lags.
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
    if (nextStep === "preflight") return { message: "次の手順: 手順0「準備」を実行してください。", href: null };
    if (nextStep === "amazon_or_rakuten_download") {
      return { message: "次の手順: 手順1または手順2で「取得」を実行してください。", href: null };
    }
    if (nextStep === "amazon_download") return { message: "次の手順: 手順1 Amazonで「取得」を実行してください。", href: null };
    if (nextStep === "amazon_decide_print") return { message: "次の手順: 手順1 Amazonで「除外・印刷（完了記録まで）」を実行してください。", href: `/runs/${ym}#exclude-section` };
    if (nextStep === "rakuten_download") return { message: "次の手順: 手順2 楽天で「取得」を実行してください。", href: null };
    if (nextStep === "rakuten_decide_print") return { message: "次の手順: 手順2 楽天で「除外・印刷（完了記録まで）」を実行してください。", href: `/runs/${ym}#exclude-section` };
    if (nextStep === "provider_ingest") return { message: "次の手順: 手順3 共通フォルダ取り込みを実行してください。", href: null };
    if (nextStep === "mf_reconcile") return { message: "次の手順: 手順5 MF突合・下書き作成を実行してください。", href: null };
    if (nextStep === "done") {
      return { message: "必要に応じて手順5を再実行してください。月次完了時は「月次クローズ」を実行します。", href: null };
    }
    return { message: "ステップ状態を判定できませんでした。再読み込みしてください。", href: null };
  }

  function inferAllowedModes(data) {
    const allowed = ["preflight", "preflight_mf"];
    if (!data.preflight?.done) return allowed;
    allowed.push("amazon_download");
    allowed.push("rakuten_download");
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const amazonPending = Boolean(data.amazon?.downloaded && !amazonDone);
    const rakutenPending = Boolean(data.rakuten?.downloaded && !rakutenDone);
    const bothDownloaded = Boolean(data.amazon?.downloaded && data.rakuten?.downloaded);
    if (data.amazon?.downloaded) {
      allowed.push("amazon_print");
    }
    if (data.rakuten?.downloaded) {
      allowed.push("rakuten_print");
    }
    if ((amazonDone || rakutenDone) && bothDownloaded && !(amazonPending || rakutenPending)) {
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
        button.title = "他の手順を実行中のため開始できません。";
      } else if (blockedByOrder) {
        button.title = "まだこの手順は実行できません。";
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
      const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
      const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
      const allowed = amazonDone || rakutenDone;
      const blockedByRunning = Boolean(runningMode);
      button.disabled = blockedByRunning || !allowed;
      if (blockedByRunning) {
        button.title = "他の手順を実行中のためアーカイブできません。";
      } else if (!allowed) {
        button.title = "Amazonまたは楽天で「除外・印刷（完了記録まで）」完了後に実行できます。";
      } else {
        button.title = "";
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
      const needsPreflight = action === "run_mf_bulk_upload";
      const blockedByPreflight = needsPreflight && !preflightDone;
      button.disabled = blockedByRunning || blockedByPreflight;
      if (blockedByRunning) {
        button.title = "他の手順を実行中のため開始できません。";
      } else if (blockedByPreflight) {
        button.title = "先に手順0「準備」を実行してください。";
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
        button.title = "他の手順を実行中のため開始できません。";
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
      return "サマリー: 手順5を実行中...";
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
      return "サマリー: 未実行";
    }
    if (!hasDraftResult) {
      return `サマリー: 未添付候補 ${missingCandidates}件 / 下書き作成は未実行`;
    }
    return `サマリー: 未添付候補 ${missingCandidates}件 / 下書き作成 ${created}/${targetsTotal}件（失敗 ${failed}件）`;
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
    const mfBulkUploadRunning = runningMode === "mf_bulk_upload";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const providerDone = Boolean(data.providers?.step_done);
    const mfBulkUploadDone = Boolean(data.mf_bulk_upload?.done);
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
        renderNextStep("ステップ状態の取得に失敗しました。再読み込みしてください。", null);
        document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
        applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
        applyManualAvailability({ running_mode: "" });
        renderMfSummary(null, "サマリー: ステップ状態の取得に失敗しました。");
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
        preflight: "手順0 準備",
        amazon_download: "手順1 Amazon 取得",
        amazon_decide_print: "手順1 Amazon 除外・印刷（完了記録まで）",
        rakuten_download: "手順2 楽天 取得",
        rakuten_decide_print: "手順2 楽天 除外・印刷（完了記録まで）",
        provider_ingest: "手順3 共通フォルダ取り込み",
        mf_bulk_upload_task: "手順4 MF一括アップロード",
        mf_reconcile: "手順5 MF突合・下書き作成",
      };
      if (!window.__stepState) {
        window.__stepState = stepStates;
      } else {
        Object.keys(stepStates).forEach((key) => {
          if (key === "mf_reconcile") return;
          if (window.__stepState[key] && window.__stepState[key] !== "done" && stepStates[key] === "done") {
            showToast(`${labels[key]}が完了しました。`, "success");
          }
        });
        window.__stepState = stepStates;
      }

      const next = computeNextStep(data, ym);
      renderNextStep(next.message, next.href);
      if (stepRetryTimer) {
        clearTimeout(stepRetryTimer);
        stepRetryTimer = null;
      }
      return data;


    } catch {
      renderNextStep("ステップ状態の取得に失敗しました。再読み込みしてください。", null);
      document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
      applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
      applyManualAvailability({ running_mode: "" });
      applyProviderAvailability({ running_mode: "", preflight: {} });
      renderMfSummary(null, "サマリー: ステップ状態の取得に失敗しました。");
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
          showToast("この手順はまだ実行できません。次の手順案内を確認してください。", "error");
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

    form.querySelector("[name=year]")?.addEventListener("change", refreshSteps);
    form.querySelector("[name=month]")?.addEventListener("change", refreshSteps);
    form.querySelector("[name=year]")?.addEventListener("change", () => applyArchivePageLink(getYmFromForm()));
    form.querySelector("[name=month]")?.addEventListener("change", () => applyArchivePageLink(getYmFromForm()));
    applyArchivePageLink(getYmFromForm());
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
        const message = "実行の停止に失敗しました。";
        showError(message);
        showToast(message, "error");
        return;
      }
      const message = "停止リクエストを送信しました。ログ更新をお待ちください。";
      showError(message);
      showToast(message, "success");
    });
  }

  bindCopyButtons();
})();


