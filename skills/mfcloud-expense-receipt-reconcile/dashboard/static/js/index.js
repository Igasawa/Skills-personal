(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const form = document.getElementById("run-form");
  const logEl = document.getElementById("run-log");
  const errorBox = document.getElementById("error-box");
  const stopButton = document.getElementById("stop-run");
  const wizardNext = document.getElementById("wizard-next");

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

  async function fetchStatus(runId) {
    const res = await fetch(`/api/runs/${runId}`);
    if (!res.ok) return null;
    return res.json();
  }

  async function refreshLog(runId) {
    const data = await fetchStatus(runId);
    if (!data) return;
    if (logEl) logEl.textContent = data.log_tail || "";
    if (data.run && data.run.status === "failed") showError("実行に失敗しました。ログを確認してください。");
    if (data.run && data.run.status !== "running") clearInterval(window.__logTimer);
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
    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        showError(toFriendlyMessage(data.detail));
        return;
      }
      const data = await res.json();
      if (logEl) {
        logEl.dataset.runId = data.run_id;
        logEl.textContent = "実行を開始しました。ログを更新中...";
      }
      refreshLog(data.run_id);
      window.__logTimer = setInterval(() => refreshLog(data.run_id), 2000);
      refreshSteps();
    } catch {
      showError("実行開始に失敗しました。しばらく待ってから再度お試しください。");
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

  function computeNextStep(data, ym) {
    const nextStep = String(data.next_step || "");
    if (nextStep === "preflight") return { message: "次は準備（ログイン + MF連携再取得）を実行してください。", href: null };
    if (nextStep === "amazon_download") return { message: "次はAmazonの領収書取得を実行してください。", href: null };
    if (nextStep === "amazon_decide_print") return { message: "次はAmazonの除外判断と印刷を実行してください。", href: `/runs/${ym}#exclude-section` };
    if (nextStep === "rakuten_download") return { message: "次は楽天の領収書取得を実行してください。", href: null };
    if (nextStep === "rakuten_decide_print") return { message: "次は楽天の除外判断と印刷を実行してください。", href: `/runs/${ym}#exclude-section` };
    if (nextStep === "mf_reconcile") return { message: "次はMF抽出 + 突合を実行してください。", href: null };
    return { message: "すべて完了しました。", href: null };
  }

  function applyActionAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const allowedModes = Array.isArray(data.allowed_run_modes) ? data.allowed_run_modes : [];
    document.querySelectorAll("[data-step-action]").forEach((button) => {
      const mode = String(button.dataset.stepAction || "");
      const allowed = allowedModes.includes(mode);
      button.disabled = Boolean(runningMode) || !allowed;
      button.title = button.disabled ? "現在のワークフロー順序では実行できません。" : "";
    });
  }

  function buildStepStates(data, runningMode) {
    const amazonRunning = runningMode === "amazon_download" || runningMode === "amazon_print";
    const rakutenRunning = runningMode === "rakuten_download" || runningMode === "rakuten_print";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    return {
      preflight: data.preflight?.done ? "done" : runningMode === "preflight" ? "running" : "pending",
      amazon_download: amazonRunning ? "running" : data.amazon.downloaded ? "done" : "pending",
      amazon_decide_print: runningMode === "amazon_print" ? "running" : amazonDone ? "done" : "pending",
      rakuten_download: rakutenRunning ? "running" : data.rakuten.downloaded ? "done" : "pending",
      rakuten_decide_print: runningMode === "rakuten_print" ? "running" : rakutenDone ? "done" : "pending",
      mf_reconcile: runningMode === "mf_reconcile" ? "running" : data.mf.reconciled ? "done" : "pending",
    };
  }

  async function refreshSteps() {
    const wizard = document.getElementById("wizard");
    if (!wizard) return;
    const ym = getYmFromForm();
    if (!ym) return;
    wizard.dataset.ym = ym;
    document.querySelectorAll("[data-step-link]").forEach((link) => {
      link.href = `/runs/${ym}#exclude-section`;
    });
    const res = await fetch(`/api/steps/${ym}`);
    if (!res.ok) return;
    const data = await res.json();
    const runningMode = data.running_mode || "";
    applyActionAvailability(data);
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
      mf_reconcile: "MF抽出 + 突合",
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
    if (runningMode) {
      clearInterval(window.__stepTimer);
      window.__stepTimer = setInterval(refreshSteps, 4000);
    } else if (window.__stepTimer) {
      clearInterval(window.__stepTimer);
    }
  }

  if (logEl && logEl.dataset.runId) {
    clearError();
    refreshLog(logEl.dataset.runId);
    window.__logTimer = setInterval(() => refreshLog(logEl.dataset.runId), 2000);
  }

  if (form) {
    document.querySelectorAll("[data-step-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (button.dataset.stepAction) startRun(button.dataset.stepAction);
      });
    });
    form.querySelector("[name=year]")?.addEventListener("change", refreshSteps);
    form.querySelector("[name=month]")?.addEventListener("change", refreshSteps);
    refreshSteps();
  }

  if (stopButton) {
    stopButton.addEventListener("click", async () => {
      const runId = stopButton.dataset.runId;
      if (!runId) return;
      const res = await fetch(`/api/runs/${runId}/stop`, { method: "POST" });
      if (!res.ok) {
        showError("停止できませんでした。");
        return;
      }
      showError("停止を要求しました。ログの更新をお待ちください。");
    });
  }

  bindCopyButtons();
})();
