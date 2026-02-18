(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));

  const tabButtons = document.querySelectorAll("[data-errors-tab]");
  const tabPanels = document.querySelectorAll("[data-errors-tab-panel]");
  const statusBox = document.getElementById("errors-status");

  const refreshButton = document.getElementById("errors-refresh");
  const listEl = document.getElementById("error-incidents-list");
  const emptyEl = document.getElementById("error-incidents-empty");
  const statUnresolved = document.getElementById("errors-stat-unresolved");
  const statResolved = document.getElementById("errors-stat-resolved");
  const statEscalated = document.getElementById("errors-stat-escalated");

  const detailEmpty = document.getElementById("error-detail-empty");
  const detailRoot = document.getElementById("error-detail");
  const detailId = document.getElementById("error-detail-id");
  const detailStatus = document.getElementById("error-detail-status");
  const detailClass = document.getElementById("error-detail-class");
  const detailStep = document.getElementById("error-detail-step");
  const detailYm = document.getElementById("error-detail-ym");
  const detailUpdated = document.getElementById("error-detail-updated");
  const detailMessage = document.getElementById("error-detail-message");

  const planAllButton = document.getElementById("errors-plan-all");
  const planButton = document.getElementById("errors-plan");
  const goButton = document.getElementById("errors-go");
  const archiveResolvedButton = document.getElementById("errors-archive-resolved");
  const archiveEscalatedButton = document.getElementById("errors-archive-escalated");

  const maxLoopsInput = document.getElementById("errors-max-loops");
  const maxRuntimeInput = document.getElementById("errors-max-runtime");
  const sameErrorLimitInput = document.getElementById("errors-same-error-limit");
  const singleIterationInput = document.getElementById("errors-single-iteration");

  const planJsonEl = document.getElementById("errors-plan-json");
  const runResultJsonEl = document.getElementById("errors-run-result-json");

  const docRefreshButton = document.getElementById("errors-doc-refresh");
  const docRunButton = document.getElementById("errors-doc-run");
  const docSummaryEl = document.getElementById("errors-doc-summary");
  const docSourceUsedEl = document.getElementById("errors-doc-source-used");
  const docIndexCountEl = document.getElementById("errors-doc-index-count");
  const docMarkdownStateEl = document.getElementById("errors-doc-markdown-state");
  const docReviewStateEl = document.getElementById("errors-doc-review-state");
  const docIndexUpdatedAtEl = document.getElementById("errors-doc-index-updated-at");
  const docReviewUpdatedAtEl = document.getElementById("errors-doc-review-updated-at");
  const docFilesEl = document.getElementById("errors-doc-files");
  const docRunResultEl = document.getElementById("errors-doc-run-result");

  let incidents = [];
  let selectedIncidentId = "";
  let selectedDetail = null;
  let busy = false;
  let docStatusLoaded = false;

  function setText(el, value) {
    if (!el) return;
    const text = String(value == null ? "-" : value);
    el.textContent = text;
  }

  function setStatus(message, kind = "") {
    if (!statusBox) return;
    const text = String(message || "").trim();
    if (!text) {
      statusBox.textContent = "";
      statusBox.classList.add("hidden");
      return;
    }
    statusBox.textContent = text;
    statusBox.classList.remove("hidden");
    statusBox.classList.remove("success", "error");
    if (kind) statusBox.classList.add(kind);
  }

  function toInt(value, fallback) {
    const n = Number.parseInt(String(value ?? ""), 10);
    return Number.isFinite(n) ? n : fallback;
  }

  function pretty(value) {
    if (value == null) return "{}";
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }

  function setActiveTab(tabName) {
    if (!tabName) return;
    tabButtons.forEach((button) => {
      const isActive = button.dataset.errorsTab === tabName;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-selected", String(isActive));
    });
    tabPanels.forEach((panel) => {
      const isActive = panel.dataset.errorsTabPanel === tabName;
      panel.classList.toggle("hidden", !isActive);
      if (isActive) {
        panel.removeAttribute("hidden");
      } else {
        panel.setAttribute("hidden", "");
      }
    });
  }

  function setBusy(isBusy) {
    busy = Boolean(isBusy);
    if (refreshButton) refreshButton.disabled = busy;
    if (planAllButton) planAllButton.disabled = busy;
    if (docRefreshButton) docRefreshButton.disabled = busy;
    if (docRunButton) docRunButton.disabled = busy;

    document.querySelectorAll("[data-error-action]").forEach((button) => {
      button.disabled = busy || !selectedIncidentId;
    });
  }

  async function apiGetJson(url) {
    const res = await fetch(url, { cache: "no-store" }).catch(() => null);
    if (!res) throw new Error("network error");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  async function apiPostJson(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }).catch(() => null);
    if (!res) throw new Error("network error");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  function updateStats(payload) {
    if (statUnresolved) statUnresolved.textContent = String(toInt(payload?.inbox_count, 0));
    if (statResolved) statResolved.textContent = String(toInt(payload?.archive_resolved_count, 0));
    if (statEscalated) statEscalated.textContent = String(toInt(payload?.archive_escalated_count, 0));
  }

  function setDetailVisible(visible) {
    if (detailRoot) detailRoot.classList.toggle("hidden", !visible);
    if (detailEmpty) detailEmpty.classList.toggle("hidden", visible);
    if (!visible) {
      if (planJsonEl) planJsonEl.textContent = "{}";
      if (runResultJsonEl) runResultJsonEl.textContent = "{}";
    }
  }

  function renderList() {
    if (!listEl) return;
    listEl.innerHTML = "";
    if (!incidents.length) {
      if (emptyEl) emptyEl.classList.remove("hidden");
      setDetailVisible(false);
      return;
    }
    if (emptyEl) emptyEl.classList.add("hidden");

    incidents.forEach((item) => {
      const id = String(item.incident_id || "").trim();
      if (!id) return;

      const button = document.createElement("button");
      button.type = "button";
      button.className = "error-incident-item";
      if (id === selectedIncidentId) button.classList.add("selected");
      button.setAttribute("data-incident-id", id);
      button.innerHTML = [
        `<div class="error-incident-id">${id}</div>`,
        `<div class="error-incident-meta">`,
        `<span>${String(item.status || "-")}</span>`,
        `<span>${String(item.failure_class || "-")}</span>`,
        `<span>${String(item.step || "-")}</span>`,
        `<span>${String(item.ym || "-")}</span>`,
        `</div>`,
      ].join("");
      button.addEventListener("click", () => {
        if (busy) return;
        if (selectedIncidentId === id) return;
        selectedIncidentId = id;
        selectedDetail = null;
        renderList();
        loadIncidentDetail(id);
      });
      const li = document.createElement("li");
      li.appendChild(button);
      listEl.appendChild(li);
    });
  }

  function renderDetail() {
    if (!selectedIncidentId || !selectedDetail) {
      setDetailVisible(false);
      return;
    }
    setDetailVisible(true);

    const incident = selectedDetail.incident && typeof selectedDetail.incident === "object" ? selectedDetail.incident : {};
    const sourceRow = incidents.find((row) => String(row.incident_id || "") === selectedIncidentId) || {};

    if (detailId) detailId.textContent = selectedIncidentId;
    if (detailStatus) detailStatus.textContent = String(incident.status || sourceRow.status || "-");
    if (detailClass) detailClass.textContent = String(incident.failure_class || sourceRow.failure_class || "-");
    if (detailStep) detailStep.textContent = String(incident.step || sourceRow.step || "-");
    if (detailYm) detailYm.textContent = String(incident.ym || sourceRow.ym || "-");
    if (detailUpdated) detailUpdated.textContent = String(incident.updated_at || sourceRow.updated_at || "-");
    if (detailMessage) detailMessage.textContent = String(incident.message || sourceRow.message || "-");

    if (planJsonEl) planJsonEl.textContent = pretty(selectedDetail.plan || {});
    if (runResultJsonEl) runResultJsonEl.textContent = pretty(selectedDetail.run_result || {});
  }

  async function refreshIncidents(options = {}) {
    const keepSelection = Boolean(options.keepSelection);
    const previousSelection = selectedIncidentId;
    const payload = await apiGetJson("/api/errors/incidents");
    incidents = Array.isArray(payload.incidents) ? payload.incidents : [];
    updateStats(payload);

    if (keepSelection && previousSelection && incidents.some((row) => String(row.incident_id || "") === previousSelection)) {
      selectedIncidentId = previousSelection;
    } else if (!incidents.some((row) => String(row.incident_id || "") === selectedIncidentId)) {
      selectedIncidentId = incidents.length ? String(incidents[0].incident_id || "") : "";
      selectedDetail = null;
    }

    renderList();
    if (selectedIncidentId) {
      await loadIncidentDetail(selectedIncidentId);
    } else {
      setDetailVisible(false);
    }
  }

  async function loadIncidentDetail(incidentId) {
    const id = String(incidentId || "").trim();
    if (!id) {
      selectedDetail = null;
      renderDetail();
      return;
    }
    const payload = await apiGetJson(`/api/errors/incidents/${encodeURIComponent(id)}`);
    selectedDetail = payload;
    renderDetail();
  }

  function renderDocumentStatus(payload) {
    const dataFiles = payload?.data_files || {};
    const sourceUsed = payload?.source_used || payload?.requested_source || "-";
    const indexExists = Boolean(dataFiles.index_exists);
    const markdownExists = Boolean(dataFiles.markdown_exists);
    const reviewExists = Boolean(dataFiles.review_exists);
    const indexUpdatedAt = dataFiles.index_updated_at || "-";
    const reviewUpdatedAt = dataFiles.review_updated_at || "-";
    const indexCount = toInt(payload?.source_counts?.index, 0);

    setText(docSummaryEl, `情報源: ${sourceUsed} / 生成日時: ${payload?.generated_at || "不明"}`);
    setText(docSourceUsedEl, sourceUsed);
    setText(docIndexCountEl, indexCount);
    setText(docMarkdownStateEl, markdownExists ? "あり" : "なし");
    setText(docReviewStateEl, reviewExists ? "あり" : "なし");
    setText(docIndexUpdatedAtEl, indexUpdatedAt);
    setText(docReviewUpdatedAtEl, reviewUpdatedAt);

    if (docFilesEl) {
      const entries = [
        { label: "AGENT_BRAIN_INDEX.jsonl", path: dataFiles.index_path, state: indexExists ? "あり" : "なし" },
        { label: "AGENT_BRAIN.md", path: dataFiles.markdown_path, state: markdownExists ? "あり" : "なし" },
        { label: "AGENT_BRAIN_REVIEW.jsonl", path: dataFiles.review_path, state: reviewExists ? "あり" : "なし" },
      ];
      docFilesEl.innerHTML = "";
      entries.forEach((entry) => {
        const item = document.createElement("li");
        item.textContent = `${entry.label}: ${entry.state} (${entry.path || "-"})`;
        docFilesEl.appendChild(item);
      });
    }
  }

  async function refreshDocumentStatus() {
    const payload = await apiGetJson("/api/kil-review?source=all&limit=1");
    renderDocumentStatus(payload);
    docStatusLoaded = true;
    return payload;
  }

  async function runAction(fn) {
    if (!selectedIncidentId || busy) return;
    setBusy(true);
    try {
      await fn();
      setStatus("", "");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "action failed");
      setStatus(message, "error");
      showToast(message, "error");
    } finally {
      setBusy(false);
      renderDetail();
      renderList();
    }
  }

  async function runDocAction(fn) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      await refreshDocumentStatus();
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "action failed");
      setStatus(message, "error");
      showToast(message, "error");
      if (docRunResultEl) {
        docRunResultEl.textContent = pretty({ error: message });
      }
    } finally {
      setBusy(false);
    }
  }

  if (refreshButton) {
    refreshButton.addEventListener("click", () =>
      runAction(async () => {
        await refreshIncidents({ keepSelection: true });
        showToast("Incident list updated", "success");
      })
    );
  }

  if (planAllButton) {
    planAllButton.addEventListener("click", () =>
      runAction(async () => {
        const data = await apiPostJson("/api/errors/incidents/plan-all", {});
        await refreshIncidents({ keepSelection: true });
        const planned = Number.parseInt(String(data.planned_count ?? 0), 10) || 0;
        const failed = Number.parseInt(String(data.failed_count ?? 0), 10) || 0;
        const message = `Plan all finished: planned=${planned}, failed=${failed}`;
        setStatus(message, failed > 0 ? "error" : "success");
        showToast(message, failed > 0 ? "error" : "success");
      })
    );
  }

  if (planButton) {
    planButton.addEventListener("click", () =>
      runAction(async () => {
        const data = await apiPostJson(`/api/errors/incidents/${encodeURIComponent(selectedIncidentId)}/plan`, {});
        await refreshIncidents({ keepSelection: true });
        const message = `Plan generated: ${String(data.plan_json || selectedIncidentId)}`;
        setStatus(message, "success");
        showToast("Plan generated", "success");
      })
    );
  }

  if (goButton) {
    goButton.addEventListener("click", () =>
      runAction(async () => {
        const payload = {
          max_loops: toInt(maxLoopsInput?.value, 8),
          max_runtime_minutes: toInt(maxRuntimeInput?.value, 45),
          same_error_limit: toInt(sameErrorLimitInput?.value, 3),
          single_iteration: Boolean(singleIterationInput?.checked),
          archive_on_success: true,
          archive_on_escalate: true,
        };
        const data = await apiPostJson(`/api/errors/incidents/${encodeURIComponent(selectedIncidentId)}/go`, payload);
        await refreshIncidents({ keepSelection: true });
        const message = `GO finished: ${String(data.final_status || "unknown")}`;
        setStatus(message, "success");
        showToast(message, "success");
      })
    );
  }

  if (archiveResolvedButton) {
    archiveResolvedButton.addEventListener("click", () =>
      runAction(async () => {
        await apiPostJson(`/api/errors/incidents/${encodeURIComponent(selectedIncidentId)}/archive`, {
          result: "resolved",
          reason: "manual archive from errors page",
        });
        await refreshIncidents({ keepSelection: false });
        showToast("Archived to resolved", "success");
      })
    );
  }

  if (archiveEscalatedButton) {
    archiveEscalatedButton.addEventListener("click", () =>
      runAction(async () => {
        await apiPostJson(`/api/errors/incidents/${encodeURIComponent(selectedIncidentId)}/archive`, {
          result: "escalated",
          reason: "manual archive from errors page",
        });
        await refreshIncidents({ keepSelection: false });
        showToast("Archived to escalated", "success");
      })
    );
  }

  if (docRefreshButton) {
    docRefreshButton.addEventListener("click", () => {
      runDocAction(async () => {
        await refreshDocumentStatus();
        showToast("ドキュメント更新ステータスを更新しました", "success");
      });
    });
  }

  if (docRunButton) {
    docRunButton.addEventListener("click", () => {
      runDocAction(async () => {
        const data = await apiPostJson("/api/errors/doc-update/run", {});
        if (docRunResultEl) {
          docRunResultEl.textContent = pretty(data);
        }
        const duration = Number.isFinite(Number(data.duration_seconds)) ? Number(data.duration_seconds) : 0;
        const message = `ドキュメント更新を完了しました（${duration}秒）`;
        setStatus(message, "success");
        showToast("ドキュメント更新を完了しました", "success");
      });
    });
  }

  tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.errorsTab;
      if (!target) return;
      setActiveTab(target);
      if (target === "document-update" && !docStatusLoaded) {
        void refreshDocumentStatus();
      }
    });
  });

  setActiveTab("incidents");

  (async function init() {
    setBusy(true);
    try {
      await Promise.all([
        refreshIncidents({ keepSelection: false }),
        refreshDocumentStatus(),
      ]);
      if (!selectedIncidentId) {
        setStatus("", "");
      } else {
        showToast("Incident list updated", "success");
      }
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "failed to load");
      setStatus(message, "error");
      showToast(message, "error");
    } finally {
      setBusy(false);
    }
  })();
})();
