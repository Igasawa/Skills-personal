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

  const KIL_REVIEW_STATUS_LIMIT = 200;
  const DOCUMENT_TARGET_LIMIT = 500;
  const DOCUMENT_TARGET_FRESH_DAYS = 30;
  const DOCUMENT_TARGET_WARNING_DAYS = 60;

  const docRefreshButton = document.getElementById("errors-doc-refresh");
  const docRunButton = document.getElementById("errors-doc-run");
  const docTargetsRefreshButton = document.getElementById("errors-doc-targets-refresh");
  const docSummaryEl = document.getElementById("errors-doc-summary");
  const docSourceUsedEl = document.getElementById("errors-doc-source-used");
  const docIndexCountEl = document.getElementById("errors-doc-index-count");
  const docMarkdownStateEl = document.getElementById("errors-doc-markdown-state");
  const docReviewStateEl = document.getElementById("errors-doc-review-state");
  const docIndexUpdatedAtEl = document.getElementById("errors-doc-index-updated-at");
  const docReviewUpdatedAtEl = document.getElementById("errors-doc-review-updated-at");
  const docFilesEl = document.getElementById("errors-doc-files");
  const docRunResultEl = document.getElementById("errors-doc-run-result");
  const docTargetsSummaryEl = document.getElementById("errors-doc-targets-summary");
  const docTargetsStatsEl = document.getElementById("errors-doc-targets-stats");
  const docTargetsListEl = document.getElementById("errors-doc-targets-list");

  let incidents = [];
  let selectedIncidentId = "";
  let selectedDetail = null;
  let busy = false;
  let docStatusLoaded = false;
  let docTargetsLoaded = false;
  const tabNames = new Set(
    Array.from(tabButtons)
      .map((button) => String(button.dataset.errorsTab || "").trim())
      .filter((name) => name.length > 0),
  );

  function resolveInitialTab() {
    const page = document.querySelector(".page.errors-page");
    const fromData = String(page?.dataset?.errorsInitialTab || "").trim();
    const params = new URLSearchParams(window.location.search || "");
    const fromQuery = String(params.get("tab") || "").trim();
    const candidate = fromQuery || fromData;
    if (candidate && tabNames.has(candidate)) {
      return candidate;
    }
    return "incidents";
  }

  function syncTabToQuery(tabName) {
    if (!tabName || !tabNames.has(tabName) || !window.history?.replaceState) return;
    const url = new URL(window.location.href);
    if (tabName === "incidents") {
      url.searchParams.delete("tab");
    } else {
      url.searchParams.set("tab", tabName);
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

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

  function toText(value, fallback = "") {
    const text = String(value == null ? "" : value).trim();
    return text || String(fallback);
  }

  function formatDateTime(value) {
    const text = toText(value);
    if (!text) return "-";
    const normalized = text.replace("T", " ").replace("Z", "");
    if (normalized.length > 19) {
      return normalized.slice(0, 19);
    }
    return normalized;
  }

  function freshnessChipLabel(freshness) {
    const key = toText(freshness).toLowerCase();
    if (key === "stale") return "要更新";
    if (key === "warning") return "注意";
    if (key === "fresh") return "最新";
    return "不明";
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
    if (docTargetsRefreshButton) docTargetsRefreshButton.disabled = busy;

    document.querySelectorAll("[data-error-action]").forEach((button) => {
      button.disabled = busy || !selectedIncidentId;
    });
  }

  async function apiGetJson(url) {
    const res = await fetch(url, { cache: "no-store" }).catch(() => null);
    if (!res) throw new Error("ネットワークエラー");
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
    if (!res) throw new Error("ネットワークエラー");
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
    if (String(payload?.status || "").toLowerCase() === "degraded") {
      const message = toFriendlyMessage(payload?.detail || "インシデント一覧の読み込みに失敗しました");
      setStatus(message, "error");
    }

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

  function renderDocumentTargets(payload) {
    if (!docTargetsSummaryEl || !docTargetsListEl) return;

    const items = Array.isArray(payload?.items) ? payload.items : [];
    const safeItems = items.filter((item) => item && typeof item === "object");
    const summary = payload?.summary && typeof payload.summary === "object" ? payload.summary : {};
    const total = toInt(summary.total, safeItems.length);
    const staleCount = toInt(summary.stale, 0);
    const warningCount = toInt(summary.warning, 0);
    const freshCount = toInt(summary.fresh, 0);
    const unknownCount = toInt(summary.unknown, 0);
    const hiddenCount = toInt(summary.hidden, 0);

    docTargetsListEl.innerHTML = "";
    setText(
      docTargetsSummaryEl,
      `対象 ${total}件 / 要更新 ${staleCount}件 / 注意 ${warningCount}件 / 最新 ${freshCount}件`
    );

    if (docTargetsStatsEl) {
      docTargetsStatsEl.innerHTML = "";
      [
        { label: "要更新", value: staleCount, className: "is-stale" },
        { label: "注意", value: warningCount, className: "is-warning" },
        { label: "最新", value: freshCount, className: "is-fresh" },
        { label: "不明", value: unknownCount, className: "is-unknown" },
      ].forEach((item) => {
        const chip = document.createElement("span");
        chip.className = `errors-doc-targets-chip ${item.className}`;
        chip.textContent = `${item.label}: ${item.value}件`;
        docTargetsStatsEl.appendChild(chip);
      });
      if (hiddenCount > 0) {
        const note = document.createElement("span");
        note.className = "muted";
        note.textContent = `表示上限で ${hiddenCount}件は省略`;
        docTargetsStatsEl.appendChild(note);
      }
    }

    if (!safeItems.length) {
      const emptyRow = document.createElement("tr");
      const emptyCell = document.createElement("td");
      emptyCell.colSpan = 4;
      emptyCell.className = "muted";
      emptyCell.textContent = "対象のドキュメントはありません。";
      emptyRow.appendChild(emptyCell);
      docTargetsListEl.appendChild(emptyRow);
      return;
    }

    safeItems.forEach((item) => {
      const name = toText(item.name || item.document_name || item.path, "-");
      const path = toText(item.path, "-");
      const area = toText(item.area);
      const updatedAt = formatDateTime(item.updated_at);
      const daysValue = Number.isFinite(Number(item.days_since_update))
        ? Math.max(0, toInt(item.days_since_update, 0))
        : null;
      const freshness = toText(item.freshness, "unknown").toLowerCase();
      const freshnessLabel = toText(item.freshness_label, freshnessChipLabel(freshness));

      const row = document.createElement("tr");

      const statusCell = document.createElement("td");
      const statusChip = document.createElement("span");
      statusChip.className = `errors-doc-targets-chip is-${freshness}`;
      statusChip.textContent = freshnessLabel;
      statusCell.appendChild(statusChip);
      row.appendChild(statusCell);

      const docCell = document.createElement("td");
      const nameEl = document.createElement("div");
      nameEl.className = "errors-doc-targets-name";
      nameEl.textContent = name;
      docCell.appendChild(nameEl);
      const pathEl = document.createElement("div");
      pathEl.className = "muted errors-doc-targets-path";
      pathEl.textContent = area ? `${path} (${area})` : path;
      docCell.appendChild(pathEl);
      row.appendChild(docCell);

      const updatedCell = document.createElement("td");
      updatedCell.textContent = updatedAt;
      row.appendChild(updatedCell);

      const daysCell = document.createElement("td");
      daysCell.textContent = daysValue == null ? "-" : `${daysValue}日`;
      row.appendChild(daysCell);

      docTargetsListEl.appendChild(row);
    });
  }

  async function refreshDocumentStatus() {
    const payload = await apiGetJson(`/api/kil-review?source=all&limit=${KIL_REVIEW_STATUS_LIMIT}`);
    renderDocumentStatus(payload);
    docStatusLoaded = true;
    return payload;
  }

  async function refreshDocumentTargets() {
    const params = new URLSearchParams();
    params.set("limit", String(DOCUMENT_TARGET_LIMIT));
    params.set("fresh_days", String(DOCUMENT_TARGET_FRESH_DAYS));
    params.set("warning_days", String(DOCUMENT_TARGET_WARNING_DAYS));
    const payload = await apiGetJson(`/api/errors/document-freshness?${params.toString()}`);
    renderDocumentTargets(payload);
    docTargetsLoaded = true;
    return payload;
  }

  async function runAction(fn) {
    if (!selectedIncidentId || busy) return;
    setBusy(true);
    try {
      await fn();
      setStatus("", "");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "処理に失敗しました");
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
      const message = toFriendlyMessage(error?.message || "処理に失敗しました");
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
        showToast("インシデント一覧を更新しました", "success");
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
        const message = `一括計画完了: 計画=${planned}件、失敗=${failed}件`;
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
        const message = `計画を生成しました: ${String(data.plan_json || selectedIncidentId)}`;
        setStatus(message, "success");
        showToast("計画を生成しました", "success");
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
        const message = `実行完了: ${String(data.final_status || "不明")}`;
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
          reason: "エラー管理画面から手動で解決済みにアーカイブ",
        });
        await refreshIncidents({ keepSelection: false });
        showToast("解決済みに移動しました", "success");
      })
    );
  }

  if (archiveEscalatedButton) {
    archiveEscalatedButton.addEventListener("click", () =>
      runAction(async () => {
        await apiPostJson(`/api/errors/incidents/${encodeURIComponent(selectedIncidentId)}/archive`, {
          result: "escalated",
          reason: "エラー管理画面から手動でエスカレートにアーカイブ",
        });
        await refreshIncidents({ keepSelection: false });
        showToast("エスカレートへ移動しました", "success");
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

  if (docTargetsRefreshButton) {
    docTargetsRefreshButton.addEventListener("click", () => {
      if (busy) return;
      setBusy(true);
      refreshDocumentTargets()
        .then(() => {
          setStatus("", "");
          showToast("対象ドキュメント一覧を更新しました", "success");
        })
        .catch((error) => {
          const message = toFriendlyMessage(error?.message || "処理に失敗しました");
          setStatus(message, "error");
          showToast(message, "error");
        })
        .finally(() => {
          setBusy(false);
        });
    });
  }

  function lazyLoadTabData(tabName) {
    if (tabName === "document-update" && !docStatusLoaded) {
      void refreshDocumentStatus().catch((error) => {
        const message = toFriendlyMessage(error?.message || "読み込みに失敗しました");
        setStatus(message, "error");
      });
      return;
    }
    if (tabName === "document-targets" && !docTargetsLoaded) {
      void refreshDocumentTargets().catch((error) => {
        const message = toFriendlyMessage(error?.message || "読み込みに失敗しました");
        setStatus(message, "error");
      });
      return;
    }
  }

  tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.errorsTab;
      if (!target) return;
      setActiveTab(target);
      syncTabToQuery(target);
      lazyLoadTabData(target);
    });
  });

  const initialTab = resolveInitialTab();
  setActiveTab(initialTab);
  syncTabToQuery(initialTab);

  (async function init() {
    setBusy(true);
    try {
      const tasks = [{ name: "インシデント一覧", run: () => refreshIncidents({ keepSelection: false }) }];
      if (initialTab === "document-update") {
        tasks.push({ name: "ドキュメント更新", run: () => refreshDocumentStatus() });
      } else if (initialTab === "document-targets") {
        tasks.push({ name: "対象ドキュメント", run: () => refreshDocumentTargets() });
      }

      const settled = await Promise.allSettled(tasks.map((task) => Promise.resolve().then(() => task.run())));
      const failed = [];
      settled.forEach((result, index) => {
        if (result.status === "rejected") {
          failed.push({
            name: tasks[index]?.name || "読み込み",
            message: toFriendlyMessage(result.reason?.message || "読み込みに失敗しました"),
          });
        }
      });

      if (failed.length > 0) {
        const first = failed[0];
        const message =
          failed.length === 1
            ? `${first.name}の読み込みに失敗しました: ${first.message}`
            : `一部データの読み込みに失敗しました: ${first.message}`;
        setStatus(message, "error");
        showToast(message, "error");
      } else if (!selectedIncidentId) {
        setStatus("", "");
      } else {
        showToast("インシデント一覧を更新しました", "success");
      }
    } finally {
      setBusy(false);
    }
  })();
})();
