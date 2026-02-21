(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const form = document.getElementById("pptx-polish-form");
  const fileInput = document.getElementById("pptx-file");
  const submitButton = document.getElementById("pptx-polish-submit");
  const resetButton = document.getElementById("pptx-polish-reset");
  const messageEl = document.getElementById("pptx-polish-message");
  const currentPanel = document.getElementById("pptx-polish-current");
  const currentMetaEl = document.getElementById("pptx-polish-job-meta");
  const progressFill = document.getElementById("pptx-polish-progress-fill");
  const summaryEl = document.getElementById("pptx-polish-job-summary");
  const currentActionsEl = document.getElementById("pptx-polish-job-actions");
  const refreshJobsButton = document.getElementById("pptx-polish-refresh-jobs");
  const jobListEl = document.getElementById("pptx-polish-job-list");
  const emptyEl = document.getElementById("pptx-polish-empty");

  const POLL_MS = 1200;
  const API_PREFIX = "/api/pptx/polish";
  const allowedStates = new Set(["uploaded", "running", "done", "failed", "unknown"]);
  let pollTimer = null;
  let currentPollJobId = null;

  function formatBytes(bytes) {
    const n = Number.parseInt(String(bytes || "0"), 10);
    if (!Number.isFinite(n) || n <= 0) return "0 B";
    if (n < 1024) return `${n} B`;
    const kb = n / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    return `${mb.toFixed(2)} MB`;
  }

  function setMessage(message, kind) {
    if (!messageEl) return;
    messageEl.textContent = String(message || "");
    messageEl.classList.remove("success", "error");
    if (kind) messageEl.classList.add(kind);
  }

  function setBusy(isBusy) {
    if (submitButton) submitButton.disabled = Boolean(isBusy);
    if (fileInput) fileInput.disabled = Boolean(isBusy);
    if (resetButton) resetButton.disabled = Boolean(isBusy);
  }

  function clearJobActions() {
    if (!currentActionsEl) return;
    currentActionsEl.innerHTML = "";
  }

  function statusLabel(status) {
    if (status === "running") return "実行中";
    if (status === "done") return "完了";
    if (status === "failed") return "失敗";
    if (status === "uploaded") return "アップロード済み";
    return "不明";
  }

  function setProgress(progress) {
    if (!progressFill) return;
    const safeProgress = Math.max(0, Math.min(100, Number.parseInt(String(progress || ""), 10) || 0));
    progressFill.style.width = `${safeProgress}%`;
    progressFill.textContent = `${safeProgress}%`;
  }

  function createField(label, value) {
    const wrapper = document.createElement("div");
    const labelEl = document.createElement("div");
    const valueEl = document.createElement("div");
    labelEl.className = "label";
    labelEl.textContent = String(label || "");
    valueEl.className = "value";
    valueEl.textContent = String(value || "-");
    wrapper.appendChild(labelEl);
    wrapper.appendChild(valueEl);
    return wrapper;
  }

  function renderMeta(job) {
    if (!currentMetaEl) return;
    const input = job.input && typeof job.input === "object" ? job.input : {};
    const output = job.output && typeof job.output === "object" ? job.output : {};
    const summary = job.summary && typeof job.summary === "object" ? job.summary : {};
    const diff = job.diff && typeof job.diff === "object" ? job.diff : {};
    const inputName = String(input.filename || "").trim() || "upload.pptx";
    const status = String(job.status || "unknown");
    const message = toFriendlyMessage(String(job.message || ""));
    const createdAt = String(job.created_at || "");
    const updatedAt = String(job.updated_at || "");
    const progress = job.progress && typeof job.progress === "object" ? Number.parseInt(String(job.progress.value || 0), 10) : 0;
    const attempt = Number.parseInt(String(job.attempt || "0"), 10);
    const beforeSlides = Number.parseInt(String(summary?.before?.slides || ""), 10);
    const slideHashChanges = Number.parseInt(String(diff?.slide_hash_changes || "0"), 10);

    const metaRows = [
      { label: "ジョブID", value: String(job.job_id || currentPollJobId || "-") },
      { label: "ステータス", value: `${statusLabel(status)}${message ? `（${message}）` : ""}` },
      { label: "入力ファイル", value: inputName },
      { label: "入力サイズ", value: formatBytes(input.size || 0) },
      { label: "出力サイズ", value: formatBytes(output.size || 0) },
      {
        label: "試行回数",
        value: Number.isFinite(attempt) ? attempt : 0,
      },
      { label: "作成日時", value: createdAt || "-" },
      { label: "更新日時", value: updatedAt || "-" },
      {
        label: "スライド数",
        value: Number.isFinite(beforeSlides) ? beforeSlides : 0,
      },
      {
        label: "変更スライド数",
        value: Number.isFinite(slideHashChanges) ? slideHashChanges : 0,
      },
    ];

    setProgress(progress || 0);
    currentMetaEl.innerHTML = "";
    metaRows.forEach((row) => {
      currentMetaEl.appendChild(createField(row.label, row.value));
    });
  }

  async function apiGetJson(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload?.detail === "string" ? payload.detail : "リクエストに失敗しました。";
      throw new Error(detail);
    }
    return payload;
  }

  async function pollJobStatus(jobId) {
    if (!jobId) return null;
    try {
      const payload = await apiGetJson(`${API_PREFIX}/${encodeURIComponent(jobId)}`, {
        method: "GET",
        headers: { "Cache-Control": "no-store" },
      });
      const job = payload?.job;
      if (!job || typeof job !== "object") {
        throw new Error("ステータス応答が不正です。");
      }
      if (!allowedStates.has(String(job.status || "").toLowerCase())) {
        job.status = "unknown";
      }
      renderCurrentJob(job);
      return job;
    } catch (error) {
      showToast(toFriendlyMessage(error.message), "error");
      clearPolling();
      setMessage("ジョブ状態を確認できませんでした。", "error");
      return null;
    }
  }

  function buildActionButton(label, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = label;
    button.addEventListener("click", handler);
    return button;
  }

  function renderCurrentActions(job) {
    if (!currentActionsEl) return;
    clearJobActions();
    const status = String(job.status || "").toLowerCase();
    const jobId = String(job.job_id || currentPollJobId || "").trim();
    if (!jobId) return;

    if ((status === "uploaded" || status === "failed") && !isCurrentPolling()) {
      currentActionsEl.appendChild(
        buildActionButton(status === "uploaded" ? "▶ 整形を開始" : "🔁 再実行", async () => {
          try {
            setBusy(true);
            clearJobActions();
            setMessage("整形開始をリクエストしています...");
            await runPolishJob(jobId);
            setMessage("整形を開始しました。");
            await pollJobStatus(jobId);
            setBusy(false);
          } catch (error) {
            setBusy(false);
            setMessage(toFriendlyMessage(error.message) || "整形の開始に失敗しました。", "error");
          }
        }),
      );
    }

    if (status === "done" && job.download_url) {
      const anchor = document.createElement("a");
      anchor.href = job.download_url;
      anchor.rel = "noopener noreferrer";
      anchor.className = "secondary";
      anchor.textContent = "整形済みファイルをダウンロード";
      anchor.setAttribute("download", "");
      currentActionsEl.appendChild(anchor);
      currentActionsEl.appendChild(
        buildActionButton("再実行", async () => {
          try {
            setBusy(true);
            clearJobActions();
            await runPolishJob(jobId);
            setMessage("整形を開始しました。");
            await pollJobStatus(jobId);
            setBusy(false);
          } catch (error) {
            setBusy(false);
            setMessage(toFriendlyMessage(error.message) || "整形の開始に失敗しました。", "error");
          }
        }),
      );
    }

    if (status === "running") {
      const runningBadge = document.createElement("span");
      runningBadge.className = "muted";
      runningBadge.textContent = "実行中... 数秒かかる場合があります。";
      currentActionsEl.appendChild(runningBadge);
    }
  }

  function isCurrentPolling() {
    if (!pollTimer) return false;
    return true;
  }

  function renderCurrentJob(job) {
    if (!currentPanel || !currentMetaEl || !summaryEl) return;
    const status = String(job.status || "").toLowerCase();
    currentPollJobId = String(job.job_id || currentPollJobId || "");
    currentPanel.classList.remove("hidden");
    job.job_id = currentPollJobId;
    renderMeta(job);
    const jobMessage = toFriendlyMessage(String(job.message || ""));
    summaryEl.textContent = `ステータス: ${statusLabel(status)}${jobMessage ? ` - ${jobMessage}` : ""}`;
    renderCurrentActions(job);

    if (status === "done" || status === "failed") {
      clearPolling();
    }
  }

  function clearPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling(jobId) {
    clearPolling();
    if (!jobId) return;
    currentPollJobId = String(jobId);
    pollTimer = window.setInterval(() => {
      pollJobStatus(currentPollJobId);
    }, POLL_MS);
  }

  async function runPolishJob(jobId) {
    if (!jobId) return;
    const data = await apiGetJson(`${API_PREFIX}/${encodeURIComponent(jobId)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const job = data?.job || data;
    if (!job || typeof job !== "object") {
      const detail = String(data?.message || "開始に失敗しました。");
      throw new Error(detail);
    }
    job.job_id = String(jobId);
    renderCurrentJob(job);
    startPolling(jobId);
  }

  function createJobCard(job) {
    const status = String(job.status || "unknown").toLowerCase();
    const item = document.createElement("article");
    item.className = "pptx-job-item";
    const jobId = String(job.job_id || "").trim();
    const createdAt = String(job.created_at || "-");
    const updatedAt = String(job.updated_at || "-");
    const progress = Number.parseInt(String(job.progress?.value || 0), 10) || 0;
    const input = job.input && typeof job.input === "object" ? job.input : {};
    const output = job.output && typeof job.output === "object" ? job.output : {};
    const inputName = String(input.filename || "upload.pptx");
    const summary = toFriendlyMessage(String(job.message || ""));

    const actions = document.createElement("div");
    actions.className = "step-actions";
    actions.setAttribute("data-job-actions", jobId || "new");

    if (status === "done" && job.download_url) {
      const anchor = document.createElement("a");
      anchor.className = "secondary";
      anchor.href = job.download_url;
      anchor.rel = "noopener noreferrer";
      anchor.textContent = "ダウンロード";
      anchor.setAttribute("download", "");
      actions.appendChild(anchor);
    }
    if (status === "uploaded" || status === "failed") {
      actions.appendChild(
        buildActionButton(status === "uploaded" ? "実行" : "再実行", async () => {
          try {
            setBusy(true);
            setMessage("実行を開始しています。");
            await runPolishJob(jobId);
            await refreshJobs();
            setBusy(false);
          } catch (error) {
            setBusy(false);
            setMessage(toFriendlyMessage(error.message) || "実行に失敗しました。", "error");
          }
        }),
      );
    }

    const head = document.createElement("div");
    const left = document.createElement("div");
    const title = document.createElement("div");
    const subtitle = document.createElement("div");
    const statusBadge = document.createElement("span");
    const meta = document.createElement("div");

    head.className = "pptx-job-item-head";
    left.className = "pptx-job-item-left";
    title.className = "pptx-job-item-id";
    subtitle.className = "muted";
    statusBadge.className = `pptx-job-status status-${status}`;

    title.textContent = `ジョブ: ${jobId || "(不明)"}`;
    subtitle.textContent = inputName;
    statusBadge.textContent = statusLabel(status);
    left.appendChild(title);
    left.appendChild(subtitle);
    head.appendChild(left);
    head.appendChild(statusBadge);

    meta.className = "pptx-job-item-meta";
    const created = document.createElement("span");
    const updated = document.createElement("span");
    const inBytes = document.createElement("span");
    const outBytes = document.createElement("span");
    const progressText = document.createElement("span");
    created.textContent = `作成: ${createdAt}`;
    updated.textContent = `更新: ${updatedAt}`;
    inBytes.textContent = `入力: ${formatBytes(input.size || 0)}`;
    outBytes.textContent = `出力: ${formatBytes(output.size || 0)}`;
    progressText.textContent = `進捗: ${Number.isFinite(progress) ? progress : 0}%`;
    meta.appendChild(created);
    meta.appendChild(updated);
    meta.appendChild(inBytes);
    meta.appendChild(outBytes);
    meta.appendChild(progressText);

    item.appendChild(head);
    item.appendChild(meta);
    if (summary) {
      const summaryText = document.createElement("p");
      summaryText.className = "muted";
      summaryText.textContent = summary;
      item.appendChild(summaryText);
    }
    item.appendChild(actions);
    return item;
  }

  function renderJobs(jobs) {
    if (!jobListEl || !emptyEl) return;
    jobListEl.innerHTML = "";
    if (!Array.isArray(jobs) || jobs.length === 0) {
      emptyEl.classList.remove("hidden");
      return;
    }
    emptyEl.classList.add("hidden");
    jobs.forEach((job) => {
      if (!job || typeof job !== "object") return;
      jobListEl.appendChild(createJobCard(job));
    });
  }

  async function refreshJobs() {
    if (!jobListEl || !emptyEl) return;
    try {
      const data = await apiGetJson(`${API_PREFIX}/jobs?limit=25`, {
        method: "GET",
        headers: { "Cache-Control": "no-store" },
      });
      const jobs = Array.isArray(data?.jobs) ? data.jobs : [];
      renderJobs(jobs);

      if (!currentPollJobId) return;
      const currentJob = jobs.find((row) => String(row?.job_id || "") === currentPollJobId);
      if (currentJob && typeof currentJob === "object" && !allowedStates.has(String(currentJob.status || "").toLowerCase())) {
        currentJob.status = "unknown";
      }
      if (currentJob && typeof currentJob === "object") {
        renderCurrentJob(currentJob);
      }
    } catch {
      showToast("履歴を読み込めませんでした。");
    }
  }

  async function uploadAndRun() {
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      setMessage(".pptx ファイルを選択してください。", "error");
      return;
    }
    const file = fileInput.files[0];
    if (!file || !String(file.name || "").toLowerCase().endsWith(".pptx")) {
      setMessage(".pptx ファイルのみ受け付けています。", "error");
      return;
    }

    const payload = new FormData();
    payload.append("file", file);
    const uploadResponse = await apiGetJson(`${API_PREFIX}`, {
      method: "POST",
      body: payload,
    });
    const jobId = String(uploadResponse.job_id || "").trim();
    if (!jobId) {
      throw new Error("アップロード結果にジョブIDが含まれていません。");
    }

    if (currentPollJobId && pollTimer) clearPolling();
    setMessage("アップロードが完了しました。整形ジョブを開始します...");
    await runPolishJob(jobId);
    await refreshJobs();
    if (submitButton) submitButton.textContent = "▶ 実行";
  }

  function bindEvents() {
    if (form) {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setBusy(true);
        setMessage("アップロード中...");
        try {
          await uploadAndRun();
          setMessage("整形を開始しました。");
          if (fileInput) fileInput.value = "";
          showToast("整形処理を開始しました。", "success");
        } catch (error) {
          setMessage(toFriendlyMessage(error.message) || "整形の開始に失敗しました。", "error");
          showToast(toFriendlyMessage(error.message) || "整形の開始に失敗しました。", "error");
        } finally {
          setBusy(false);
        }
      });
    }

    if (resetButton) {
      resetButton.addEventListener("click", () => {
        if (fileInput) fileInput.value = "";
        setMessage("");
        currentPanel.classList.add("hidden");
        if (currentMetaEl) currentMetaEl.innerHTML = "";
        if (summaryEl) summaryEl.textContent = "";
        clearJobActions();
        setProgress(0);
        if (currentPollJobId) {
          clearPolling();
          currentPollJobId = null;
        }
      });
    }

    if (refreshJobsButton) {
      refreshJobsButton.addEventListener("click", async () => {
        refreshJobsButton.disabled = true;
        try {
          await refreshJobs();
          setMessage("履歴を更新しました。", "success");
        } catch {
          setMessage("履歴の更新に失敗しました。", "error");
        } finally {
          refreshJobsButton.disabled = false;
        }
      });
    }

    window.addEventListener("beforeunload", () => {
      clearPolling();
    });
  }

  bindEvents();
  refreshJobs();
})();
