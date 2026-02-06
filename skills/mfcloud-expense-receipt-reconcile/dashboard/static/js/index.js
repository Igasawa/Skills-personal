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

  const runStatusById = {};
  let awaitingRunFinalization = false;
  let stepRetryTimer = null;
  let activeLogRunId = "";
  let stepRefreshInFlight = false;

  async function apiGetJson(url) {
    const sep = url.includes("?") ? "&" : "?";
    const res = await fetch(`${url}${sep}_=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
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
    refreshSteps();
    [800, 2000, 4500].forEach((delayMs) => {
      setTimeout(() => {
        refreshSteps();
      }, delayMs);
    });
  }

  async function fetchStatus(runId) {
    return apiGetJson(`/api/runs/${runId}`);
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

  async function refreshLog(runId) {
    if (!runId) return;
    if (activeLogRunId && String(runId) !== activeLogRunId) return;
    const data = await fetchStatus(runId);
    if (!data) return;

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
      awaitingRunFinalization = false;
      stopLogPolling(runId);
      scheduleStepSync();
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
    if (!data.mf?.reconciled && (amazonDone || rakutenDone)) return "mf_reconcile";
    if (data.amazon?.downloaded && !amazonDone) return "amazon_decide_print";
    if (data.rakuten?.downloaded && !rakutenDone) return "rakuten_decide_print";
    if (!data.amazon?.downloaded && !data.rakuten?.downloaded) return "amazon_or_rakuten_download";
    if (!data.amazon?.downloaded) return "amazon_download";
    if (!data.rakuten?.downloaded) return "rakuten_download";
    if (!data.mf?.reconciled) return "mf_reconcile";
    return "done";
  }

  function resolveNextStep(data) {
    const hinted = String(data.next_step || "").trim();
    const inferred = inferNextStepFromFlags(data);
    if (!hinted) return inferred;
    if (hinted === "done" && inferred !== "done") return inferred;
    return hinted;
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
    if (nextStep === "mf_reconcile") return { message: "次はMF抽出 + 突合を実行してください。", href: null };
    if (nextStep === "done") return { message: "すべて完了しました。", href: null };
    return { message: "ステップ状態を判定できません。再読み込みしてください。", href: null };
  }

  function inferAllowedModes(data) {
    const allowed = ["preflight"];
    if (!data.preflight?.done) return allowed;
    allowed.push("amazon_download");
    allowed.push("rakuten_download");
    if (data.amazon?.downloaded) {
      allowed.push("amazon_print");
    }
    if (data.rakuten?.downloaded) {
      allowed.push("rakuten_print");
    }
    if ((data.amazon?.confirmed && data.amazon?.printed) || (data.rakuten?.confirmed && data.rakuten?.printed)) {
      allowed.push("mf_reconcile");
    }
    return allowed;
  }

  function applyActionAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const hintedAllowedModes = Array.isArray(data.allowed_run_modes) ? data.allowed_run_modes : [];
    const inferred = inferAllowedModes(data);
    const allowedModes = Array.from(new Set([...inferred, ...hintedAllowedModes]));
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
      mf_reconcile: runningMode === "mf_reconcile" ? "running" : data.mf?.reconciled ? "done" : "pending",
    };
  }

  async function refreshSteps() {
    if (stepRefreshInFlight) return;
    stepRefreshInFlight = true;
    const wizard = document.getElementById("wizard");
    if (!wizard) {
      stepRefreshInFlight = false;
      return;
    }

    const ym = getYmFromForm();
    if (!ym) {
      stepRefreshInFlight = false;
      return;
    }
    wizard.dataset.ym = ym;

    try {
      const raw = await apiGetJson(`/api/steps/${ym}`);
      if (!raw) {
        renderNextStep("ステップ状態の取得に失敗しました。再読み込みしてください。", null);
        document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
        if (!stepRetryTimer) {
          stepRetryTimer = setTimeout(() => {
            stepRetryTimer = null;
            refreshSteps();
          }, 1500);
        }
        return;
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
      applyLinkAvailability(data, ym);

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
      if (stepRetryTimer) {
        clearTimeout(stepRetryTimer);
        stepRetryTimer = null;
      }


    } catch {
      renderNextStep("ステップ状態の取得に失敗しました。再読み込みしてください。", null);
      document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
      if (!stepRetryTimer) {
        stepRetryTimer = setTimeout(() => {
          stepRetryTimer = null;
          refreshSteps();
        }, 1500);
      }
    } finally {
      stepRefreshInFlight = false;
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

    document.querySelectorAll("[data-step-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        if (link.getAttribute("aria-disabled") === "true") {
          event.preventDefault();
          showToast("まだこのステップには進めません。次ステップ案内に従ってください。", "error");
        }
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

