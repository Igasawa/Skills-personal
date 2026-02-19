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
    if (status === "running") return "Running";
    if (status === "done") return "Completed";
    if (status === "failed") return "Failed";
    if (status === "uploaded") return "Uploaded";
    return "Unknown";
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
    const message = String(job.message || "");
    const createdAt = String(job.created_at || "");
    const updatedAt = String(job.updated_at || "");
    const progress = job.progress && typeof job.progress === "object" ? Number.parseInt(String(job.progress.value || 0), 10) : 0;
    const attempt = Number.parseInt(String(job.attempt || "0"), 10);
    const beforeSlides = Number.parseInt(String(summary?.before?.slides || ""), 10);
    const slideHashChanges = Number.parseInt(String(diff?.slide_hash_changes || "0"), 10);

    const metaRows = [
      { label: "Job ID", value: String(job.job_id || currentPollJobId || "-") },
      { label: "Status", value: `${statusLabel(status)}${message ? ` (${message})` : ""}` },
      { label: "Input", value: inputName },
      { label: "Input size", value: formatBytes(input.size || 0) },
      { label: "Output size", value: formatBytes(output.size || 0) },
      {
        label: "Attempt",
        value: Number.isFinite(attempt) ? attempt : 0,
      },
      { label: "Created at", value: createdAt || "-" },
      { label: "Updated at", value: updatedAt || "-" },
      {
        label: "Slides",
        value: Number.isFinite(beforeSlides) ? beforeSlides : 0,
      },
      {
        label: "Slides changed",
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
      const detail = typeof payload?.detail === "string" ? payload.detail : "Request failed";
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
        throw new Error("Invalid status response.");
      }
      if (!allowedStates.has(String(job.status || "").toLowerCase())) {
        job.status = "unknown";
      }
      renderCurrentJob(job);
      return job;
    } catch (error) {
      showToast(toFriendlyMessage(error.message), "error");
      clearPolling();
      setMessage("Unable to check job status.", "error");
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
        buildActionButton(status === "uploaded" ? "Run polish" : "Retry polish", async () => {
          try {
            setBusy(true);
            clearJobActions();
            setMessage("Polish start requested...");
            await runPolishJob(jobId);
            setMessage("Polish started.");
            await pollJobStatus(jobId);
            setBusy(false);
          } catch (error) {
            setBusy(false);
            setMessage(toFriendlyMessage(error.message) || "Failed to start polish.", "error");
          }
        }),
      );
    }

    if (status === "done" && job.download_url) {
      const anchor = document.createElement("a");
      anchor.href = job.download_url;
      anchor.rel = "noopener noreferrer";
      anchor.className = "secondary";
      anchor.textContent = "Download polished file";
      anchor.setAttribute("download", "");
      currentActionsEl.appendChild(anchor);
      currentActionsEl.appendChild(
        buildActionButton("Run again", async () => {
          try {
            setBusy(true);
            clearJobActions();
            await runPolishJob(jobId);
            setMessage("Polish started.");
            await pollJobStatus(jobId);
            setBusy(false);
          } catch (error) {
            setBusy(false);
            setMessage(toFriendlyMessage(error.message) || "Failed to start polish.", "error");
          }
        }),
      );
    }

    if (status === "running") {
      const runningBadge = document.createElement("span");
      runningBadge.className = "muted";
      runningBadge.textContent = "Running... this may take a few seconds.";
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
    summaryEl.textContent = `Status: ${statusLabel(status)}${job.message ? ` - ${job.message}` : ""}`;
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
      const detail = String(data?.message || "Start failed");
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
    const summary = String(job.message || "");

    const actions = document.createElement("div");
    actions.className = "step-actions";
    actions.setAttribute("data-job-actions", jobId || "new");

    if (status === "done" && job.download_url) {
      const anchor = document.createElement("a");
      anchor.className = "secondary";
      anchor.href = job.download_url;
      anchor.rel = "noopener noreferrer";
      anchor.textContent = "Download";
      anchor.setAttribute("download", "");
      actions.appendChild(anchor);
    }
    if (status === "uploaded" || status === "failed") {
      actions.appendChild(
        buildActionButton(status === "uploaded" ? "Run" : "Retry", async () => {
          try {
            setBusy(true);
            setMessage("Run requested.");
            await runPolishJob(jobId);
            await refreshJobs();
            setBusy(false);
          } catch (error) {
            setBusy(false);
            setMessage(toFriendlyMessage(error.message) || "Failed to run.", "error");
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

    title.textContent = `Job: ${jobId || "(unknown)"}`;
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
    created.textContent = `Created: ${createdAt}`;
    updated.textContent = `Updated: ${updatedAt}`;
    inBytes.textContent = `Input: ${formatBytes(input.size || 0)}`;
    outBytes.textContent = `Output: ${formatBytes(output.size || 0)}`;
    progressText.textContent = `Progress: ${Number.isFinite(progress) ? progress : 0}%`;
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
      showToast("Unable to load job history.");
    }
  }

  async function uploadAndRun() {
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      setMessage("Please select a .pptx file.", "error");
      return;
    }
    const file = fileInput.files[0];
    if (!file || !String(file.name || "").toLowerCase().endsWith(".pptx")) {
      setMessage("Only .pptx files are accepted.", "error");
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
      throw new Error("Upload response is missing job ID.");
    }

    if (currentPollJobId && pollTimer) clearPolling();
    setMessage("Upload complete. Starting polish job...");
    await runPolishJob(jobId);
    await refreshJobs();
    if (submitButton) submitButton.textContent = "Execute";
  }

  function bindEvents() {
    if (form) {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setBusy(true);
        setMessage("Uploading...");
        try {
          await uploadAndRun();
          setMessage("Polish started.");
          if (fileInput) fileInput.value = "";
          showToast("Polish process started.", "success");
        } catch (error) {
          setMessage(toFriendlyMessage(error.message) || "Failed to start polish.", "error");
          showToast(toFriendlyMessage(error.message) || "Failed to start polish.", "error");
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
          setMessage("History refreshed.", "success");
        } catch {
          setMessage("Failed to refresh history.", "error");
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
