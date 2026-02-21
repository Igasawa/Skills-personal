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
  const aiSkillsRefreshButton = document.getElementById("errors-ai-skills-refresh");
  const aiSkillsSummaryEl = document.getElementById("errors-ai-skills-summary");
  const aiSkillsEnvPolicyEl = document.getElementById("errors-ai-skills-env-policy");
  const aiSkillsListEl = document.getElementById("errors-ai-skills-list");
  const notificationSettingsRefreshButton = document.getElementById("errors-notification-settings-refresh");
  const notificationConfiguredEl = document.getElementById("errors-notification-configured");
  const notificationSourceEl = document.getElementById("errors-notification-source");
  const notificationMaskedEl = document.getElementById("errors-notification-masked");
  const notificationUpdatedAtEl = document.getElementById("errors-notification-updated-at");
  const notificationWebhookInput = document.getElementById("errors-notification-webhook-url");
  const notificationSaveButton = document.getElementById("errors-notification-save");
  const notificationClearButton = document.getElementById("errors-notification-clear");
  const notificationTestButton = document.getElementById("errors-notification-test");
  const notificationLastResultEl = document.getElementById("errors-notification-last-result");
  const schedulerRefreshButton = document.getElementById("errors-scheduler-refresh");
  const schedulerRestartButton = document.getElementById("errors-scheduler-restart");
  const schedulerSummaryEl = document.getElementById("errors-scheduler-summary");
  const schedulerWorkerRunningEl = document.getElementById("errors-scheduler-worker-running");
  const schedulerWorkerPollEl = document.getElementById("errors-scheduler-worker-poll");
  const schedulerWorkerStartedEl = document.getElementById("errors-scheduler-worker-started");
  const schedulerTotalEl = document.getElementById("errors-scheduler-total");
  const schedulerEnabledEl = document.getElementById("errors-scheduler-enabled");
  const schedulerDueEl = document.getElementById("errors-scheduler-due");
  const schedulerLockActiveEl = document.getElementById("errors-scheduler-lock-active");
  const schedulerLockStaleEl = document.getElementById("errors-scheduler-lock-stale");
  const schedulerTimersEl = document.getElementById("errors-scheduler-timers");
  const schedulerEmptyEl = document.getElementById("errors-scheduler-empty");
  const schedulerLastResultEl = document.getElementById("errors-scheduler-last-result");

  let incidents = [];
  let selectedIncidentId = "";
  let selectedDetail = null;
  let busy = false;
  let docStatusLoaded = false;
  let docTargetsLoaded = false;
  let aiSkillsLoaded = false;
  let notificationSettingsLoaded = false;
  let schedulerLoaded = false;
  const aiSkillPending = new Set();
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
    if (notificationSettingsRefreshButton) notificationSettingsRefreshButton.disabled = busy;
    if (notificationSaveButton) notificationSaveButton.disabled = busy;
    if (notificationClearButton) notificationClearButton.disabled = busy;
    if (notificationTestButton) notificationTestButton.disabled = busy;
    if (notificationWebhookInput) notificationWebhookInput.disabled = busy;
    if (schedulerRefreshButton) schedulerRefreshButton.disabled = busy;
    if (schedulerRestartButton) schedulerRestartButton.disabled = busy;

    document.querySelectorAll("[data-error-action]").forEach((button) => {
      button.disabled = busy || !selectedIncidentId;
    });
    updateAiSkillControlsDisabled();
  }

  function updateAiSkillControlsDisabled() {
    if (aiSkillsRefreshButton) {
      aiSkillsRefreshButton.disabled = busy || aiSkillPending.size > 0;
    }
    if (!aiSkillsListEl) return;
    aiSkillsListEl.querySelectorAll("[data-ai-skill-toggle]").forEach((input) => {
      const skillId = String(input?.dataset?.aiSkillToggle || "").trim();
      input.disabled = busy || !skillId || aiSkillPending.has(skillId);
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
    if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
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

  function buildAiSkillEffectiveState(row) {
    if (!row || typeof row !== "object") return "不明";
    const hasRunner = Boolean(row.has_runner);
    const envAllowed = Boolean(row.env_allowed);
    const adminEnabled = Boolean(row.admin_enabled);
    const allowed = Boolean(row.allowed);
    if (!hasRunner) return "API: 実行不可（runnerなし） / Agent: 実行可（SKILL.md）";
    if (!envAllowed) return "API: 環境ポリシーで制限中 / Agent: 実行可（SKILL.md）";
    if (!adminEnabled) return "API: ダッシュボード設定で禁止 / Agent: 実行可（SKILL.md）";
    return allowed ? "API: 実行可 / Agent: 実行可（SKILL.md）" : "API: 実行不可 / Agent: 実行可（SKILL.md）";
  }

  function renderAiSkills(payload) {
    if (!aiSkillsListEl || !aiSkillsSummaryEl) return;
    const skills = Array.isArray(payload?.skills) ? payload.skills.filter((row) => row && typeof row === "object") : [];
    const runnableCount = skills.filter((row) => Boolean(row.has_runner)).length;
    const allowedCount = skills.filter((row) => Boolean(row.allowed)).length;
    const blockedCount = Math.max(0, runnableCount - allowedCount);
    setText(aiSkillsSummaryEl, `実行可能 ${runnableCount}件 / 許可 ${allowedCount}件 / 制限中 ${blockedCount}件`);

    const permissions = payload?.permissions && typeof payload.permissions === "object" ? payload.permissions : {};
    const envAllowlistEnabled = Boolean(permissions.env_allowlist_enabled);
    const envAllowlist = Array.isArray(permissions.env_allowlist) ? permissions.env_allowlist : [];
    if (aiSkillsEnvPolicyEl) {
      if (envAllowlistEnabled) {
        setText(
          aiSkillsEnvPolicyEl,
          `環境変数 AX_AI_CHAT_SKILL_ALLOWLIST により ${envAllowlist.length}件へ制限中`,
        );
      } else {
        setText(aiSkillsEnvPolicyEl, "環境変数による追加制限はありません");
      }
    }

    aiSkillsListEl.innerHTML = "";
    if (!skills.length) {
      const emptyRow = document.createElement("tr");
      const emptyCell = document.createElement("td");
      emptyCell.colSpan = 4;
      emptyCell.className = "muted";
      emptyCell.textContent = "利用可能なスキルが見つかりません。";
      emptyRow.appendChild(emptyCell);
      aiSkillsListEl.appendChild(emptyRow);
      updateAiSkillControlsDisabled();
      return;
    }

    skills.forEach((row) => {
      const skillId = toText(row.id, "-");
      const skillName = toText(row.name, skillId);
      const description = toText(row.description, "-");
      const hasRunner = Boolean(row.has_runner);
      const envAllowed = Boolean(row.env_allowed);
      const adminEnabled = hasRunner ? Boolean(row.admin_enabled) : false;

      const tr = document.createElement("tr");

      const skillCell = document.createElement("td");
      const skillTitle = document.createElement("div");
      skillTitle.className = "errors-ai-skills-name";
      skillTitle.textContent = `${skillName} (${skillId})`;
      skillCell.appendChild(skillTitle);
      tr.appendChild(skillCell);

      const descCell = document.createElement("td");
      descCell.className = "errors-ai-skills-desc";
      descCell.textContent = description;
      tr.appendChild(descCell);

      const stateCell = document.createElement("td");
      stateCell.textContent = buildAiSkillEffectiveState(row);
      tr.appendChild(stateCell);

      const toggleCell = document.createElement("td");
      const label = document.createElement("label");
      label.className = "errors-ai-skills-toggle";

      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = adminEnabled;
      input.dataset.aiSkillToggle = skillId;
      input.disabled = !hasRunner;
      if (!hasRunner) {
        input.title =
          "このスキルは runner がないため API 実行できません（scripts/run.py|run.ps1|run.mjs|run.js）。SKILL.md ベースの Agent 実行は可能です。";
      } else if (!envAllowed) {
        input.title =
          "環境許可リストにより API 実行が制限されています。このトグルはダッシュボード側の許可設定のみ変更します。";
      } else {
        input.title = "ダッシュボードの API 実行許可を切り替えます。";
      }
      label.title = input.title;
      input.addEventListener("change", () => {
        const enabled = Boolean(input.checked);
        void updateAiSkillPermission(skillId, enabled);
      });
      label.appendChild(input);

      const caption = document.createElement("span");
      caption.textContent = adminEnabled ? "許可" : "禁止";
      label.appendChild(caption);
      toggleCell.appendChild(label);
      tr.appendChild(toggleCell);

      aiSkillsListEl.appendChild(tr);
    });
    updateAiSkillControlsDisabled();
  }

  async function refreshAiSkills() {
    const payload = await apiGetJson("/api/ai/skills");
    renderAiSkills(payload);
    aiSkillsLoaded = true;
    return payload;
  }

  function renderNotificationSettings(payload) {
    const configured = Boolean(payload?.configured);
    const sourceRaw = toText(payload?.source, "none").toLowerCase();
    let sourceLabel = "none";
    if (sourceRaw === "file") sourceLabel = "file (UI設定)";
    else if (sourceRaw === "env") sourceLabel = "env (AX_GOOGLE_CHAT_WEBHOOK_URL)";

    setText(notificationConfiguredEl, configured ? "設定済み" : "未設定");
    setText(notificationSourceEl, sourceLabel);
    setText(notificationMaskedEl, toText(payload?.webhook_url_masked, "-"));
    setText(notificationUpdatedAtEl, formatDateTime(payload?.updated_at));
  }

  async function refreshNotificationSettings(options = {}) {
    const keepInput = Boolean(options.keepInput);
    const keepResult = Boolean(options.keepResult);
    const payload = await apiGetJson("/api/workflow-events/notification-settings");
    renderNotificationSettings(payload);
    if (notificationWebhookInput && !keepInput) {
      notificationWebhookInput.value = "";
    }
    if (notificationLastResultEl && !keepResult) {
      notificationLastResultEl.textContent = "-";
    }
    notificationSettingsLoaded = true;
    return payload;
  }

  function schedulerWorkerLabel(running) {
    return running ? "active" : "stopped";
  }

  function schedulerToggleLabel(enabled) {
    return enabled ? "on" : "off";
  }

  function renderSchedulerTimers(rows) {
    if (!schedulerTimersEl) return;
    const timerRows = Array.isArray(rows) ? rows : [];
    schedulerTimersEl.innerHTML = "";
    timerRows.forEach((rowRaw) => {
      const row = rowRaw && typeof rowRaw === "object" ? rowRaw : {};
      const tr = document.createElement("tr");
      const lastResult =
        row.last_result && typeof row.last_result === "object"
          ? [toText(row.last_result.status), formatDateTime(row.last_result.at)].filter((v) => v && v !== "-").join(" @ ")
          : "";
      const cells = [
        toText(row.template_id, "-"),
        schedulerToggleLabel(Boolean(row.enabled)),
        formatDateTime(row.next_run_at),
        toText(row.action_key, "-"),
        toText(row.run_date, "-"),
        toText(row.run_time, "-"),
        formatDateTime(row.updated_at),
        lastResult || "-",
      ];
      cells.forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });
      schedulerTimersEl.appendChild(tr);
    });
    if (schedulerEmptyEl) {
      schedulerEmptyEl.classList.toggle("hidden", timerRows.length > 0);
    }
  }

  function renderSchedulerHealth(payload) {
    const workerRunning = Boolean(payload?.worker_running);
    const pollSeconds = toInt(payload?.worker_poll_seconds, 0);
    const workerStartedAt = formatDateTime(payload?.worker_started_at);
    const total = toInt(payload?.total_timers, 0);
    const enabled = toInt(payload?.enabled_timers, 0);
    const due = toInt(payload?.due_timers, 0);
    const activeLocks = toInt(payload?.active_locks, 0);
    const staleLocks = toInt(payload?.stale_locks, 0);

    setText(schedulerWorkerRunningEl, schedulerWorkerLabel(workerRunning));
    setText(schedulerWorkerPollEl, pollSeconds > 0 ? String(pollSeconds) : "-");
    setText(schedulerWorkerStartedEl, workerStartedAt);
    setText(schedulerTotalEl, String(total));
    setText(schedulerEnabledEl, String(enabled));
    setText(schedulerDueEl, String(due));
    setText(schedulerLockActiveEl, String(activeLocks));
    setText(schedulerLockStaleEl, String(staleLocks));
    setText(
      schedulerSummaryEl,
      `worker=${schedulerWorkerLabel(workerRunning)} / timers=${total} (enabled=${enabled}, due=${due}) / locks=${activeLocks} (stale=${staleLocks})`,
    );
    renderSchedulerTimers(payload?.timers);
  }

  async function refreshSchedulerHealth() {
    const payload = await apiGetJson("/api/scheduler/health?limit=100");
    renderSchedulerHealth(payload);
    schedulerLoaded = true;
    return payload;
  }

  async function updateAiSkillPermission(skillId, enabled) {
    const resolvedSkillId = String(skillId || "").trim().toLowerCase();
    if (!resolvedSkillId) return;
    aiSkillPending.add(resolvedSkillId);
    updateAiSkillControlsDisabled();
    try {
      await apiPostJson("/api/ai/skills/permissions", {
        skill: resolvedSkillId,
        enabled: Boolean(enabled),
      });
      await refreshAiSkills();
      setStatus("", "");
      showToast(`スキル権限を更新しました: ${resolvedSkillId}`, "success");
    } catch (error) {
      await refreshAiSkills().catch(() => {});
      const message = toFriendlyMessage(error?.message || "スキル権限の更新に失敗しました");
      setStatus(message, "error");
      showToast(message, "error");
    } finally {
      aiSkillPending.delete(resolvedSkillId);
      updateAiSkillControlsDisabled();
    }
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

  async function runNotificationAction(fn) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      setStatus("", "");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "通知設定の処理に失敗しました");
      setStatus(message, "error");
      showToast(message, "error");
      if (notificationLastResultEl) {
        notificationLastResultEl.textContent = message;
      }
    } finally {
      setBusy(false);
    }
  }

  async function runSchedulerAction(fn) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      setStatus("", "");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "Scheduler action failed");
      setStatus(message, "error");
      showToast(message, "error");
      if (schedulerLastResultEl) {
        schedulerLastResultEl.textContent = message;
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

  if (aiSkillsRefreshButton) {
    aiSkillsRefreshButton.addEventListener("click", () => {
      if (busy || aiSkillPending.size > 0) return;
      setBusy(true);
      refreshAiSkills()
        .then(() => {
          setStatus("", "");
          showToast("AIスキル権限を更新しました", "success");
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

  if (notificationSettingsRefreshButton) {
    notificationSettingsRefreshButton.addEventListener("click", () => {
      runNotificationAction(async () => {
        await refreshNotificationSettings({ keepInput: true, keepResult: true });
        showToast("通知設定を更新しました", "success");
      });
    });
  }

  if (notificationSaveButton) {
    notificationSaveButton.addEventListener("click", () => {
      runNotificationAction(async () => {
        const webhookUrl = toText(notificationWebhookInput?.value);
        const data = await apiPostJson("/api/workflow-events/notification-settings", {
          webhook_url: webhookUrl,
        });
        renderNotificationSettings(data);
        notificationSettingsLoaded = true;
        if (notificationWebhookInput) notificationWebhookInput.value = "";
        const message = webhookUrl ? "通知Webhook URLを保存しました" : "通知Webhook URL設定をクリアしました";
        if (notificationLastResultEl) notificationLastResultEl.textContent = message;
        showToast(message, "success");
      });
    });
  }

  if (notificationClearButton) {
    notificationClearButton.addEventListener("click", () => {
      runNotificationAction(async () => {
        const data = await apiPostJson("/api/workflow-events/notification-settings", {
          webhook_url: "",
        });
        renderNotificationSettings(data);
        notificationSettingsLoaded = true;
        if (notificationWebhookInput) notificationWebhookInput.value = "";
        if (notificationLastResultEl) notificationLastResultEl.textContent = "通知Webhook URL設定をクリアしました";
        showToast("通知Webhook URL設定をクリアしました", "success");
      });
    });
  }

  if (notificationTestButton) {
    notificationTestButton.addEventListener("click", () => {
      runNotificationAction(async () => {
        const data = await apiPostJson("/api/workflow-events/notification-settings/test", {});
        const statusCode = toInt(data?.http_status, 200);
        const message = toText(data?.message, "テスト通知を送信しました");
        if (notificationLastResultEl) notificationLastResultEl.textContent = `${message} (HTTP ${statusCode})`;
        await refreshNotificationSettings({ keepInput: true, keepResult: true });
        showToast("テスト通知を送信しました", "success");
      });
    });
  }

  if (schedulerRefreshButton) {
    schedulerRefreshButton.addEventListener("click", () => {
      runSchedulerAction(async () => {
        await refreshSchedulerHealth();
        if (schedulerLastResultEl) schedulerLastResultEl.textContent = "Scheduler health refreshed.";
        showToast("Scheduler health refreshed.", "success");
      });
    });
  }

  if (schedulerRestartButton) {
    schedulerRestartButton.addEventListener("click", () => {
      runSchedulerAction(async () => {
        const payload = await apiPostJson("/api/scheduler/restart", { limit: 100 });
        renderSchedulerHealth(payload);
        schedulerLoaded = true;
        const startedAt = formatDateTime(payload?.worker_started_at);
        const message = startedAt && startedAt !== "-" ? `Scheduler worker restarted at ${startedAt}.` : "Scheduler worker restarted.";
        if (schedulerLastResultEl) schedulerLastResultEl.textContent = message;
        showToast(message, "success");
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
    if (tabName === "notification-settings" && !notificationSettingsLoaded) {
      void refreshNotificationSettings().catch((error) => {
        const message = toFriendlyMessage(error?.message || "読み込みに失敗しました");
        setStatus(message, "error");
      });
      return;
    }
    if (tabName === "scheduler-monitor" && !schedulerLoaded) {
      void refreshSchedulerHealth().catch((error) => {
        const message = toFriendlyMessage(error?.message || "Failed to load scheduler health");
        setStatus(message, "error");
      });
      return;
    }
    if (tabName === "ai-skills" && !aiSkillsLoaded) {
      void refreshAiSkills().catch((error) => {
        const message = toFriendlyMessage(error?.message || "読み込みに失敗しました");
        setStatus(message, "error");
      });
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
      } else if (initialTab === "notification-settings") {
        tasks.push({ name: "通知設定", run: () => refreshNotificationSettings() });
      } else if (initialTab === "scheduler-monitor") {
        tasks.push({ name: "Scheduler monitor", run: () => refreshSchedulerHealth() });
      } else if (initialTab === "ai-skills") {
        tasks.push({ name: "AIスキル権限", run: () => refreshAiSkills() });
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
