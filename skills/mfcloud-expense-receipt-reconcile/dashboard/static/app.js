const form = document.getElementById("run-form");
const logEl = document.getElementById("run-log");
const errorBox = document.getElementById("error-box");
const stopButton = document.getElementById("stop-run");
const wizardNext = document.getElementById("wizard-next");
const toastEl = document.getElementById("toast");

function showError(message) {
  if (!errorBox) return;
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
}

function showToast(message, type = "info") {
  if (!toastEl || !message) return;
  toastEl.textContent = message;
  toastEl.classList.remove("success", "error", "show");
  if (type === "success") toastEl.classList.add("success");
  if (type === "error") toastEl.classList.add("error");
  requestAnimationFrame(() => {
    toastEl.classList.add("show");
  });
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => {
    toastEl.classList.remove("show");
  }, 2400);
}

function clearError() {
  if (!errorBox) return;
  errorBox.textContent = "";
  errorBox.classList.add("hidden");
}

function toFriendlyMessage(detail) {
  const text = String(detail || "");
  if (text.includes("Another run is already in progress")) {
    return "すでに実行中の処理があります。完了してから再度お試しください。";
  }
  if (text.includes("MF Cloud expense list URL is required")) {
    return "MFクラウド経費一覧URLを入力してください。";
  }
  if (text.includes("Invalid year/month") || text.includes("Month must be")) {
    return "年月の形式が不正です。YYYY-MMで指定してください。";
  }
  if (text.includes("Missing amazon/orders.jsonl")) {
    return "Amazonの注文データがありません。先にAmazonの領収書取得を実行してください。";
  }
  if (text.includes("Missing mfcloud/expenses.jsonl")) {
    return "MFクラウドの抽出データがありません。先にMF抽出を実行してください。";
  }
  if (text.includes("Invalid mode")) {
    return "実行モードが不正です。";
  }
  return text || "実行に失敗しました。ログを確認してください。";
}

async function fetchStatus(runId) {
  const res = await fetch(`/api/runs/${runId}`);
  if (!res.ok) {
    return null;
  }
  return res.json();
}

async function refreshLog(runId) {
  const data = await fetchStatus(runId);
  if (!data) return;
  if (logEl) {
    logEl.textContent = data.log_tail || "";
  }
  if (data.run && data.run.status === "failed") {
    showError("実行に失敗しました。ログを確認してください。");
  }
  if (data.run && data.run.status !== "running") {
    clearInterval(window.__logTimer);
  }
}

if (logEl && logEl.dataset.runId) {
  clearError();
  refreshLog(logEl.dataset.runId);
  window.__logTimer = setInterval(() => refreshLog(logEl.dataset.runId), 2000);
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
    clearError();
    refreshLog(data.run_id);
    window.__logTimer = setInterval(() => refreshLog(data.run_id), 2000);
    refreshSteps();
  } catch (err) {
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
  } else if (state === "running") {
    el.textContent = "実行中";
    el.classList.add("running");
  } else {
    el.textContent = "未実行";
  }
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
  if (href) {
    const link = document.createElement("a");
    link.href = href;
    link.className = "secondary";
    link.textContent = "開く";
    wizardNext.appendChild(link);
  }
}

function computeNextStep(data, ym) {
  if (!data) return null;
  if (!data.preflight?.done) {
    return { message: "次は準備（ログイン + MF連携再取得）を実行してください。", href: null };
  }
  if (!data.amazon?.downloaded) {
    return { message: "次はAmazonの領収書取得を実行してください。", href: null };
  }
  if (!data.amazon?.confirmed || !data.amazon?.printed) {
    return { message: "次はAmazonの除外判断と印刷を実行してください。", href: `/runs/${ym}#exclude-section` };
  }
  if (!data.rakuten?.downloaded) {
    return { message: "次は楽天の領収書取得を実行してください。", href: null };
  }
  if (!data.rakuten?.confirmed || !data.rakuten?.printed) {
    return { message: "次は楽天の除外判断と印刷を実行してください。", href: `/runs/${ym}#exclude-section` };
  }
  if (!data.mf?.reconciled) {
    return { message: "次はMF抽出 + 突合を実行してください。", href: null };
  }
  return { message: "すべて完了しました。お疲れさまでした。", href: null };
}

function buildStepStates(data, runningMode) {
  const preflightRunning = runningMode === "preflight";
  const amazonRunning = runningMode === "amazon_download" || runningMode === "amazon_print";
  const rakutenRunning = runningMode === "rakuten_download" || runningMode === "rakuten_print";
  const mfRunning = runningMode === "mf_reconcile";
  const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
  const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
  return {
    preflight: data.preflight?.done ? "done" : preflightRunning ? "running" : "pending",
    amazon_download: amazonRunning ? "running" : data.amazon.downloaded ? "done" : "pending",
    amazon_decide_print: runningMode === "amazon_print" ? "running" : amazonDone ? "done" : "pending",
    rakuten_download: rakutenRunning ? "running" : data.rakuten.downloaded ? "done" : "pending",
    rakuten_decide_print: runningMode === "rakuten_print" ? "running" : rakutenDone ? "done" : "pending",
    mf_reconcile: mfRunning ? "running" : data.mf.reconciled ? "done" : "pending",
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
      const prev = window.__stepState[key];
      const next = stepStates[key];
      if (prev && prev !== "done" && next === "done") {
        showToast(`${labels[key]}が完了しました。`, "success");
      }
    });
    window.__stepState = stepStates;
  }

  const next = computeNextStep(data, ym);
  if (next) renderNextStep(next.message, next.href);

  if (runningMode) {
    clearInterval(window.__stepTimer);
    window.__stepTimer = setInterval(refreshSteps, 4000);
  } else if (window.__stepTimer) {
    clearInterval(window.__stepTimer);
  }
}

if (form) {
  document.querySelectorAll("[data-step-action]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const mode = button.dataset.stepAction;
      if (mode) startRun(mode);
    });
  });

  const yearEl = form.querySelector("[name=year]");
  const monthEl = form.querySelector("[name=month]");
  yearEl?.addEventListener("change", refreshSteps);
  monthEl?.addEventListener("change", refreshSteps);
  refreshSteps();
}

document.querySelectorAll(".copy-button").forEach((button) => {
  button.addEventListener("click", async () => {
    const targetId = button.dataset.copyTarget;
    const target = targetId ? document.getElementById(targetId) : null;
    const text = target ? target.textContent : "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "コピーしました";
      setTimeout(() => {
        button.textContent = "コピー";
      }, 1200);
    } catch {
      alert("クリップボードにコピーできませんでした。");
    }
  });
});

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

const excludeSection = document.getElementById("exclude-section");
const excludeButtons = document.querySelectorAll(".exclude-save");
const excludeStatus = document.getElementById("exclude-status");

function setExcludeStatus(message, kind) {
  if (!excludeStatus) return;
  excludeStatus.textContent = message || "";
  excludeStatus.classList.remove("success", "error");
  if (kind) excludeStatus.classList.add(kind);
}

async function saveExclusions(ym, source) {
  const items = [];
  document.querySelectorAll(".exclude-toggle").forEach((el) => {
    const orderSource = el.dataset.source;
    const orderId = el.dataset.orderId;
    if (el.checked && orderSource && orderId) {
      items.push({ source: orderSource, order_id: orderId });
    }
  });

  const res = await fetch(`/api/exclusions/${ym}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ exclude: items, source }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "save failed");
  }
}

async function runPrint(ym, source) {
  const res = await fetch(`/api/print/${ym}/${source}`, { method: "POST" });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "print failed");
  }
}

if (excludeSection && excludeButtons.length) {
  excludeButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      const ym = excludeSection.dataset.ym;
      const source = button.dataset.source;
      if (!ym || !source) return;

      excludeButtons.forEach((btn) => (btn.disabled = true));
      try {
        await saveExclusions(ym, source);
        await runPrint(ym, source);
        setExcludeStatus(excludeStatus?.dataset.success || "除外設定を保存しました。", "success");
      } catch (err) {
        setExcludeStatus(excludeStatus?.dataset.error || "保存または印刷に失敗しました。", "error");
      } finally {
        excludeButtons.forEach((btn) => (btn.disabled = false));
      }
    });
  });
}

const printButtons = document.querySelectorAll(".print-single");
const printStatus = document.getElementById("print-status");

function setPrintStatus(message, kind) {
  if (!printStatus) return;
  printStatus.textContent = message || "";
  printStatus.classList.remove("success", "error");
  if (kind) printStatus.classList.add(kind);
}

if (printButtons.length) {
  printButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      const ym = button.dataset.ym;
      const source = button.dataset.source;
      const filename = button.dataset.filename;
      if (!ym || !source || !filename) return;

      printButtons.forEach((btn) => (btn.disabled = true));
      setPrintStatus("印刷を開始しています...", "success");
      try {
        const res = await fetch(`/api/print-pdf/${ym}/${source}/${filename}`, { method: "POST" });
        if (!res.ok) throw new Error("print failed");
        setPrintStatus("印刷を開始しました。", "success");
        showToast("印刷を開始しました。", "success");
      } catch {
        setPrintStatus("印刷に失敗しました。", "error");
        showToast("印刷に失敗しました。", "error");
      } finally {
        printButtons.forEach((btn) => (btn.disabled = false));
      }
    });
  });
}

const excludedSearch = document.getElementById("excluded-search");
const excludedRows = document.querySelectorAll(".excluded-row");
const excludedCount = document.getElementById("excluded-count");
const filterAmazon = document.getElementById("filter-amazon");
const filterRakuten = document.getElementById("filter-rakuten");
const filterPdf = document.getElementById("filter-pdf");

function updateExcludedCount() {
  if (!excludedCount) return;
  let visible = 0;
  excludedRows.forEach((row) => {
    if (row.classList.contains("hidden")) return;
    visible += 1;
  });
  excludedCount.textContent = String(visible);
}

function applyExcludedFilters() {
  if (!excludedRows.length) return;
  const normalize = (text) => String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
  const query = normalize(excludedSearch?.value || "");
  const tokens = query ? query.split(" ") : [];
  const amazonOn = filterAmazon ? filterAmazon.checked : true;
  const rakutenOn = filterRakuten ? filterRakuten.checked : true;
  const pdfMode = filterPdf ? filterPdf.value : "all";
  excludedRows.forEach((row) => {
    const source = row.dataset.source || "";
    const hasPdf = row.dataset.hasPdf || "yes";
    const sourceMatch = (source === "amazon" && amazonOn) || (source === "rakuten" && rakutenOn);
    const pdfMatch = pdfMode === "all" || (pdfMode === "yes" && hasPdf === "yes") || (pdfMode === "no" && hasPdf === "no");
    const hay = normalize(row.dataset.search);
    const textMatch = tokens.every((t) => hay.includes(t));
    row.classList.toggle("hidden", !(sourceMatch && pdfMatch && textMatch));
  });
  updateExcludedCount();
}

if (excludedRows.length) {
  const normalize = (text) => String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
  excludedSearch?.addEventListener("input", applyExcludedFilters);
  filterAmazon?.addEventListener("change", applyExcludedFilters);
  filterRakuten?.addEventListener("change", applyExcludedFilters);
  filterPdf?.addEventListener("change", applyExcludedFilters);
  applyExcludedFilters();
}
