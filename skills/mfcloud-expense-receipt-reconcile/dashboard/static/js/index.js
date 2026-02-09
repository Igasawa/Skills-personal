(function () {
  // UI文言方針: 利用者向け文言は原則日本語で統一する。
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
    if (normalizedMode === "amazon_download") return Boolean(data.amazon?.downloaded);
    if (normalizedMode === "rakuten_download") return Boolean(data.rakuten?.downloaded);
    if (normalizedMode === "amazon_print") return Boolean(data.amazon?.confirmed && data.amazon?.printed);
    if (normalizedMode === "rakuten_print") return Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
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

  async function archiveOutputs(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("年月が未設定です。", "error");
      return;
    }

    clearError();
    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    showToast("アーカイブを作成しています...", "success");

    try {
      const res = await fetch(`/api/archive/${ym}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "アーカイブ作成に失敗しました。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const archivedTo = String(data.archived_to || "").trim();
      const message = archivedTo ? `アーカイブ作成完了: ${archivedTo}` : "アーカイブ作成完了";
      showToast(message, "success");
    } catch {
      const message = "アーカイブ作成に失敗しました。";
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) {
        delete buttonEl.dataset.busy;
      }
      refreshSteps({ force: true });
    }
  }

  async function openManualInbox(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("年月が未設定です。", "error");
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
        const message = toFriendlyMessage(data.detail || "手動領収書フォルダを開けませんでした。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath ? `手動領収書フォルダを開きました: ${openedPath}` : "手動領収書フォルダを開きました。";
      showToast(message, "success");
    } catch {
      const message = "手動領収書フォルダを開けませんでした。";
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
      showToast("年月が未設定です。", "error");
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
        const message = toFriendlyMessage(data.detail || "手動領収書の取り込みに失敗しました。");
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
      const message = "手動領収書の取り込みに失敗しました。";
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
      showToast("年月が未設定です。", "error");
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
      showToast("年月が未設定です。", "error");
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
      const message = `MF一括アップロード: 発見 ${found}件 / 読取 ${readCount}件 / キュー ${queued}件 / 送信 ${submitted}件${details}`;
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

  async function resetStep(stepId, buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("年月が未設定です。", "error");
      return;
    }
    const labelByStep = {
      amazon_download: "1 Amazon領収書取得",
      amazon_decide_print: "2 Amazon除外判断・印刷",
      rakuten_download: "3 楽天領収書取得",
      rakuten_decide_print: "4 楽天除外判断・印刷",
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
        const message = toFriendlyMessage(data.detail || "リセットに失敗しました。");
        showError(message);
        showToast(message, "error");
        return;
      }
      const cancelledCount = Array.isArray(data.cancelled_runs) ? data.cancelled_runs.length : 0;
      showToast(cancelledCount > 0 ? `リセット完了（実行中 ${cancelledCount} 件を停止）` : "リセット完了", "success");
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
    el.classList.remove("done", "running");
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
    if (amazonPending) return "amazon_decide_print";
    if (rakutenPending) return "rakuten_decide_print";
    if (!data.amazon?.downloaded && !data.rakuten?.downloaded) return "amazon_or_rakuten_download";
    if (!data.amazon?.downloaded) return "amazon_download";
    if (!data.rakuten?.downloaded) return "rakuten_download";
    const mfDone = Boolean(data.mf?.step_done ?? data.mf?.reconciled);
    if (!mfDone && bothDownloaded && (amazonDone || rakutenDone)) return "mf_reconcile";
    if (!mfDone) return "mf_reconcile";
    return "done";
  }

  function resolveNextStep(data) {
    const inferred = inferNextStepFromFlags(data);
    // Keep UI guidance consistent with current flags even if API next_step lags.
    return inferred;
  }

  function computeNextStep(data, ym) {
    const nextStep = resolveNextStep(data);
    if (nextStep === "preflight") return { message: "次は準備（ログイン + MF連携再取得）を実行してください。", href: null };
    if (nextStep === "amazon_or_rakuten_download") {
      return { message: "次はAmazonまたは楽天の領収書取得を実行してください。", href: null };
    }
    if (nextStep === "amazon_download") return { message: "次はAmazonの領収書取得を実行してください。", href: null };
    if (nextStep === "amazon_decide_print") return { message: "次はAmazonの除外判断と印刷を実行してください。", href: `/runs/${ym}#exclude-section` };
    if (nextStep === "rakuten_download") return { message: "次は楽天の領収書取得を実行してください。", href: null };
    if (nextStep === "rakuten_decide_print") return { message: "次は楽天の除外判断と印刷を実行してください。", href: `/runs/${ym}#exclude-section` };
    if (nextStep === "mf_reconcile") return { message: "次はMF抽出 + 突合 + 下書き作成を実行してください。", href: null };
    if (nextStep === "done") return { message: "すべて完了しました。", href: null };
    return { message: "ステップ状態を判定できません。再読み込みしてください。", href: null };
  }

  function inferAllowedModes(data) {
    const allowed = ["preflight"];
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
        button.title = "他のステップが実行中のため開始できません。";
      } else if (blockedByOrder) {
        button.title = "現在のワークフロー順序では実行できません。";
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
        button.title = "他のステップ実行中はアーカイブできません。";
      } else if (!allowed) {
        button.title = "Amazonまたは楽天の確認+印刷完了後に実行できます。";
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
        button.title = "他のステップ実行中は開始できません。";
      } else if (blockedByPreflight) {
        button.title = "先に準備（Step0）を実行してください。";
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
      return "サマリー: Step5実行中...";
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
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    return {
      preflight: data.preflight?.done ? "done" : runningMode === "preflight" ? "running" : "pending",
      amazon_download: amazonRunning ? "running" : data.amazon?.downloaded ? "done" : "pending",
      amazon_decide_print: runningMode === "amazon_print" ? "running" : amazonDone ? "done" : "pending",
      rakuten_download: rakutenRunning ? "running" : data.rakuten?.downloaded ? "done" : "pending",
      rakuten_decide_print: runningMode === "rakuten_print" ? "running" : rakutenDone ? "done" : "pending",
      mf_reconcile:
        runningMode === "mf_reconcile"
          ? "running"
          : Boolean(data.mf?.step_done ?? data.mf?.reconciled)
            ? "done"
            : "pending",
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

    try {
      const raw = await apiGetJson(`/api/steps/${ym}`);
      if (!raw) {
        renderNextStep("ステップ状態の取得に失敗しました。再読み込みしてください。", null);
        document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
        applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
        applyManualAvailability({ running_mode: "" });
        renderMfSummary(null, "サマリー: 状態取得に失敗");
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
        mf: raw.mf || {},
        running_mode: raw.running_mode || "",
        next_step: raw.next_step || "",
        allowed_run_modes: Array.isArray(raw.allowed_run_modes) ? raw.allowed_run_modes : [],
      };

      const runningMode = String(data.running_mode || "");

      applyActionAvailability(data);
      applyArchiveAvailability(data);
      applyManualAvailability(data);
      applyLinkAvailability(data, ym);
      renderMfSummary(data);

      const stepStates = buildStepStates(data, runningMode);
      setStepStatus("preflight", stepStates.preflight);
      setStepStatus("amazon_download", stepStates.amazon_download);
      setStepStatus("amazon_decide_print", stepStates.amazon_decide_print);
      setStepStatus("rakuten_download", stepStates.rakuten_download);
      setStepStatus("rakuten_decide_print", stepStates.rakuten_decide_print);
      setStepStatus("mf_reconcile", stepStates.mf_reconcile);

      const labels = {
        preflight: "準備",
        amazon_download: "Amazon領収書の取得",
        amazon_decide_print: "Amazon除外・印刷",
        rakuten_download: "楽天領収書の取得",
        rakuten_decide_print: "楽天除外・印刷",
        mf_reconcile: "MF抽出 + 突合 + 下書き作成",
      };
      if (!window.__stepState) {
        window.__stepState = stepStates;
      } else {
        Object.keys(stepStates).forEach((key) => {
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
      renderMfSummary(null, "サマリー: 状態取得に失敗");
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
        }
      });
    });

    document.querySelectorAll("[data-manual-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        runManualAction(String(button.dataset.manualAction || ""), button);
      });
    });

    document.querySelectorAll("[data-step-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        if (link.getAttribute("aria-disabled") === "true") {
          event.preventDefault();
          showToast("まだこのステップには進めません。次ステップ案内に従ってください。", "error");
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
        const message = "停止できませんでした。";
        showError(message);
        showToast(message, "error");
        return;
      }
      const message = "停止を要求しました。ログ更新を待ってください。";
      showError(message);
      showToast(message, "success");
    });
  }

  bindCopyButtons();
})();

