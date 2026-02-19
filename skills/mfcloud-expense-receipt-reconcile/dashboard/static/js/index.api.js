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

    // (msg)
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
        showToast("(msg)", "error");
      } else if (status === "success") {
        showToast("(msg)", "success");
      }
    }
    if (status) {
      runStatusById[runId] = status;
    }

    if (status === "failed") {
      showError("(msg)");
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
    const yearMonth = resolveFormYearMonth();
    const notesEl = form.querySelector("[name=notes]");
    const rakutenOrdersEl = form.querySelector("[name=rakuten_orders_url]");
    return {
      year: yearMonth.year,
      month: yearMonth.month,
      mfcloud_url: getPrimaryTemplateSourceUrl(),
      notes: (notesEl?.value || "").trim(),
      rakuten_orders_url: (rakutenOrdersEl?.value || "").trim(),
      auth_handoff: true,
      auto_receipt_name: true,
      mode,
    };
  }

  function resolveFormYearMonth() {
    const now = new Date();
    let year = now.getFullYear();
    let month = now.getMonth() + 1;
    if (!form) return { year, month };
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    const parsedYear = Number.parseInt(String(yearEl?.value || "").trim(), 10);
    const parsedMonth = Number.parseInt(String(monthEl?.value || "").trim(), 10);
    if (Number.isInteger(parsedYear) && parsedYear >= 2000) {
      year = parsedYear;
    }
    if (Number.isInteger(parsedMonth) && parsedMonth >= 1 && parsedMonth <= 12) {
      month = parsedMonth;
    }
    if (yearEl) yearEl.value = String(year);
    if (monthEl) monthEl.value = String(month);
    return { year, month };
  }

  function buildTemplatePayload() {
    if (!form) return null;
    const nameEl = form.querySelector("[name=template_name]");
    const subheadingEl = form.querySelector("[name=template_subheading]");
    const yearMonth = resolveFormYearMonth();
    const notesEl = form.querySelector("[name=notes]");
    const rakutenOrdersEl = form.querySelector("[name=rakuten_orders_url]");
    const sourceUrls = collectTemplateSourceUrls();
    const primarySourceUrl = sourceUrls[0] || "";
    const templateMode = "edit";
    const templateId = getTemplateIdFromForm();
    const name = String(nameEl?.value || "").trim();
    return {
      template_id: templateId,
      template_mode: templateMode,
      template_source_id: getTemplateSourceIdFromForm(),
      name,
      subheading: String(subheadingEl?.value || "").trim(),
      year: yearMonth.year,
      month: yearMonth.month,
      mfcloud_url: primarySourceUrl,
      source_urls: sourceUrls,
      notes: String(notesEl?.value || "").trim(),
      rakuten_orders_url: String(rakutenOrdersEl?.value || "").trim(),
      steps: collectTemplateSteps(),
      allow_duplicate_name: false,
      base_updated_at: getTemplateUpdatedAtFromForm() || String(workflowTemplate?.updated_at || ""),
    };
  }

  function buildWorkflowPagePayload() {
    const payload = buildTemplatePayload();
    if (!payload) return null;
    const sourceTemplateId =
      getTemplateSourceIdFromForm() || getTemplateIdFromForm() || String(workflowTemplate?.id || "").trim();
    return {
      name: payload.name,
      subheading: payload.subheading,
      year: payload.year,
      month: payload.month,
      mfcloud_url: payload.mfcloud_url,
      source_urls: Array.isArray(payload.source_urls) ? payload.source_urls : [],
      steps: Array.isArray(payload.steps) ? payload.steps : [],
      notes: payload.notes,
      rakuten_orders_url: payload.rakuten_orders_url,
      source_template_id: sourceTemplateId,
    };
  }

  function buildWorkflowStepPreviewLines(steps) {
    const rows = normalizeWorkflowStepRows(Array.isArray(steps) ? steps : [], {
      ensureRequired: false,
      includeTimer: true,
    });
    return rows.map((row, index) => {
      const action = String(row.action || "").trim();
      const actionLabel = TEMPLATE_STEP_ACTION_LABELS[action] || action || "(未設定)";
      const title = String(row.title || "").trim() || defaultTitleForStepAction(action, `手順${index + 1}`);
      const stepType = String(row.type || 'manual').trim() || 'manual';
      const trigger = String(row.trigger || 'manual').trim() || 'manual';
      const typeLabel =
        stepType === "browser" ? "Browser" : stepType === "agent" ? "Agent" : "手動";
      const triggerLabel =
        trigger === "schedule"
          ? "スケジュール"
          : trigger === "webhook"
            ? "Webhook"
            : trigger === "after_step"
              ? "前手順完了後"
              : "手動実行";
      const autoRun = normalizeTemplateStepAutoRun(row.auto_run);
      const timer = autoRun ? normalizeTemplateStepTimerForAutoRun(row.timer_minutes) : null;
      const mode = autoRun ? `自動 ${timer}分` : "手動";
      const suffix = [];
      if (stepType === "browser" && String(row.target_url || "").trim()) {
        suffix.push(`URL: ${String(row.target_url || "").trim()}`);
      }
      if (stepType === "agent" && String(row.agent_prompt || "").trim()) {
        const promptPreview = String(row.agent_prompt || "").trim().slice(0, 40);
        suffix.push(`Prompt: ${promptPreview}${promptPreview.length >= 40 ? "..." : ""}`);
      }
      const suffixText = suffix.length ? ` / ${suffix.join(" / ")}` : "";
      return `${index + 1}. ${title} / ${actionLabel} / ${typeLabel} / ${triggerLabel} / ${mode}${suffixText}`;
    });
  }

  function renderWorkflowCreatePreview(payload = null) {
    const listEl = document.getElementById("workflow-create-preview-list");
    if (!listEl) return;
    const currentPayload = payload || buildWorkflowPagePayload() || {};
    const name = String(currentPayload.name || "").trim() || "(未入力)";
    const subheading = String(currentPayload.subheading || "").trim() || "(なし)";
    const stepLines = buildWorkflowStepPreviewLines(currentPayload.steps);
    const lines = [`ワークフロー名: ${name}`, `補足説明: ${subheading}`, "作成される手順:"];
    if (stepLines.length > 0) {
      lines.push(...stepLines.map((line) => `  ${line}`));
    } else {
      lines.push("  (手順なし)");
    }
    listEl.innerHTML = "";
    lines.forEach((line) => {
      const item = document.createElement("li");
      item.className = "muted";
      item.textContent = line;
      listEl.appendChild(item);
    });
  }

  async function createWorkflowPage() {
    if (!form || workflowPageCreateState.inFlight) return;
    if (!validateTemplateSourceUrls()) return;
    if (!validateTemplateStepRows()) return;
    const payload = buildWorkflowPagePayload();
    if (!payload) return;
    if (!payload.name) {
      const message = "ワークフロー名を入力してください。";
      showError(message);
      showToast(message, "error");
      return;
    }
    const confirmed = await showConfirmModal({
      title: "ワークフロー作成の確認",
      lines: [
        "新しいワークフローページを作成します。",
        `ページ名: ${payload.name}`,
        `補足説明: ${payload.subheading || "(なし)"}`,
        ...buildWorkflowStepPreviewLines(payload.steps).map((line) => `手順: ${line}`),
        "テンプレートの手順定義と自動実行設定を引き継ぎます。",
      ],
      confirmLabel: "作成して開く",
      cancelLabel: "戻る",
    });
    if (!confirmed) return;

    const createButton = document.getElementById("workflow-page-create");
    const originalLabel = createButton ? String(createButton.textContent || "").trim() : "ワークフローを作成";
    workflowPageCreateState.inFlight = true;
    if (createButton) {
      createButton.disabled = true;
      createButton.textContent = "作成中...";
      createButton.dataset.busy = "1";
    }
    clearError();

    try {
      const res = await fetch("/api/workflow-pages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail) || "ワークフローページの作成に失敗しました。";
        showError(message);
        showToast(message, "error");
        return;
      }

      const workflowPage = data.workflow_page || null;
      const workflowPageId = String(workflowPage?.id || "").trim();
      if (data.scheduler_copied === true) {
        showToast("ワークフローを作成しました。自動実行設定も引き継ぎました。", "success");
      } else {
        showToast("ワークフローページを作成しました。", "success");
      }
      if (workflowPageId) {
        window.location.href = `/workflow/${encodeURIComponent(workflowPageId)}`;
        return;
      }
      const message = "作成は完了しましたが、遷移先が見つかりませんでした。";
      showError(message);
      showToast(message, "error");
    } catch {
      const message = "ワークフローページの作成に失敗しました。";
      showError(message);
      showToast(message, "error");
    } finally {
      if (createButton) {
        createButton.disabled = false;
        createButton.textContent = originalLabel;
        if (createButton.dataset) {
          delete createButton.dataset.busy;
        }
      }
      workflowPageCreateState.inFlight = false;
    }
  }

  async function editWorkflowPageSettings() {
    const workflowPageId = String(workflowPage?.id || "").trim();
    if (!workflowPageId) return;
    const heroTitleEl = document.querySelector(".hero h1");
    const heroSubheadingEl = document.querySelector(".hero .eyebrow");
    const currentName = String(workflowPage?.name || heroTitleEl?.textContent || "").trim();
    const currentSubheading = String(workflowPage?.subheading || heroSubheadingEl?.textContent || "").trim();
    const nextValues = await showWorkflowSettingsModal({ name: currentName, subheading: currentSubheading });
    if (!nextValues) return;
    const nextName = String(nextValues.name || "").trim();
    if (!nextName) {
      const message = "ワークフロー名を入力してください。";
      showError(message);
      showToast(message, "error");
      return;
    }
    const nextSubheading = String(nextValues.subheading || "").trim();
    if (nextName === currentName && nextSubheading === currentSubheading) {
      showToast("変更はありません。", "info");
      return;
    }
    const updates = {
      name: nextName,
      subheading: nextSubheading,
      base_updated_at: String(workflowPage?.updated_at || ""),
    };
    try {
      const res = await fetch(`/api/workflow-pages/${encodeURIComponent(workflowPageId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail) || "ページ設定の更新に失敗しました。";
        showError(message);
        showToast(message, "error");
        return;
      }
      showToast("ページ設定を更新しました。", "success");
      window.location.reload();
    } catch {
      const message = "ページ設定の更新に失敗しました。";
      showError(message);
      showToast(message, "error");
    }
  }

  async function archiveCurrentWorkflowPage() {
    const workflowPageId = String(workflowPage?.id || "").trim();
    if (!workflowPageId) return;
    const confirmed = await showConfirmModal({
      title: "ワークフローのアーカイブ",
      lines: [
        "このワークフローをサイドバーから非表示にします。",
        "必要な場合は WF作成テンプレート画面から復元できます。",
      ],
      confirmLabel: "アーカイブする",
      cancelLabel: "キャンセル",
    });
    if (!confirmed) return;
    try {
      const res = await fetch(`/api/workflow-pages/${encodeURIComponent(workflowPageId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          archived: true,
          base_updated_at: String(workflowPage?.updated_at || ""),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail) || "アーカイブに失敗しました。";
        showError(message);
        showToast(message, "error");
        return;
      }
      showToast("ワークフローをアーカイブしました。", "success");
      window.location.href = "/";
    } catch {
      const message = "アーカイブに失敗しました。";
      showError(message);
      showToast(message, "error");
    }
  }

  function getWorkflowPageStepModelListEl() {
    return document.querySelector("#workflow-page-step-model [data-template-steps-list]");
  }

  function syncWorkflowPageStepModelRows(stepRows) {
    const modelListEl = getWorkflowPageStepModelListEl();
    if (!modelListEl) return;
    const rows = normalizeWorkflowStepRows(stepRows, {
      ensureRequired: false,
      includeTimer: true,
    });
    modelListEl.innerHTML = "";
    rows.forEach((row, index) => {
      const rowEl = document.createElement("div");
      rowEl.dataset.templateStepRow = "1";
      rowEl.dataset.templateStepId = String(row.id || generateTemplateStepId()).trim();
      const titleEl = document.createElement("input");
      titleEl.type = "text";
      titleEl.dataset.templateStepTitle = "1";
      titleEl.value = String(row.title || "").trim() || defaultTitleForStepAction(row.action, `手順${index + 1}`);
      const actionEl = document.createElement("select");
      actionEl.dataset.templateStepAction = "1";
      actionEl.innerHTML = getTemplateStepActionOptionsHtml(row.action);
      rowEl.appendChild(titleEl);
      rowEl.appendChild(actionEl);
      modelListEl.appendChild(rowEl);
    });
    modelListEl.dispatchEvent(
      new CustomEvent("template-steps-changed", {
        bubbles: true,
      }),
    );
  }

  function renderWorkflowPageStepVersionLabel() {
    const labelEl = document.getElementById("workflow-page-step-version");
    if (!labelEl) return;
    const currentVersion = Number.parseInt(String(workflowPage?.step_version || 1), 10);
    const safeVersion = Number.isInteger(currentVersion) && currentVersion > 0 ? currentVersion : 1;
    const versions = Array.isArray(workflowPage?.step_versions) ? workflowPage.step_versions : [];
    const currentRow = versions.find((row) => Number.parseInt(String(row?.version || 0), 10) === safeVersion);
    const updatedAt = String(currentRow?.updated_at || "").trim();
    labelEl.textContent = updatedAt ? `手順版 v${safeVersion} (${updatedAt})` : `手順版 v${safeVersion}`;
  }

  function applyWorkflowPageStepLayout(stepRowsInput = null) {
    const workflowPageId = String(workflowPage?.id || "").trim();
    if (!workflowPageId) return;
    const containerEl = document.querySelector("#wizard .wizard-steps");
    if (!containerEl) return;
    const rows = normalizeWorkflowStepRows(
      Array.isArray(stepRowsInput) ? stepRowsInput : workflowPage?.steps,
      { ensureRequired: false, includeTimer: true },
    );
    const rowByAction = new Map(rows.map((row) => [String(row.action || "").trim(), row]));
    const visibleBlockSet = new Set();
    rows.forEach((row) => {
      const key = actionToWorkflowBlockKey(row.action);
      if (key) visibleBlockSet.add(key);
    });
    const orderedBlockKeys = WORKFLOW_STEP_BLOCK_ORDER.filter((key) => visibleBlockSet.has(key));
    const genericRows = rows.filter((row) => !actionToWorkflowBlockKey(row.action));

    const processConfigs = [
      { elementId: "step-amazon-download", action: "amazon_download" },
      { elementId: "step-amazon-decide-print", action: "amazon_print" },
      { elementId: "step-rakuten-download", action: "rakuten_download" },
      { elementId: "step-rakuten-decide-print", action: "rakuten_print" },
    ];
    processConfigs.forEach((config) => {
      const processEl = document.getElementById(config.elementId);
      if (!processEl) return;
      const row = rowByAction.get(config.action);
      processEl.hidden = !row;
      processEl.classList.toggle("hidden", !row);
      processEl.style.display = row ? "" : "none";
      if (!row) return;
      processEl.classList.remove("hidden");
      processEl.style.display = "";
      const titleEl = processEl.querySelector(".process-title");
      if (titleEl) {
        titleEl.textContent = String(row.title || "").trim() || defaultTitleForStepAction(row.action);
      }
    });

    WORKFLOW_STEP_BLOCK_ORDER.forEach((key) => {
      const selector = WORKFLOW_STEP_BLOCK_SELECTORS[key];
      if (!selector) return;
      const blockEl = document.querySelector(selector);
      if (!blockEl) return;
      const shouldHide = !visibleBlockSet.has(key);
      blockEl.hidden = shouldHide;
      blockEl.classList.toggle("hidden", shouldHide);
      blockEl.style.display = shouldHide ? "none" : "";
    });

    orderedBlockKeys.forEach((key, index) => {
      const selector = WORKFLOW_STEP_BLOCK_SELECTORS[key];
      if (!selector) return;
      const blockEl = document.querySelector(selector);
      if (!blockEl) return;
      blockEl.hidden = false;
      blockEl.classList.remove("hidden");
      blockEl.style.display = "";
      containerEl.appendChild(blockEl);
      const numberEl = blockEl.querySelector(".step-head .step-num, .task-head .step-num");
      if (numberEl) {
        numberEl.textContent = String(index + 1);
      }
      const actions = WORKFLOW_ACTIONS_BY_BLOCK_KEY[key] || [];
      const step = rows.find((row) => actions.includes(String(row.action || "").trim()));
      if (!step) return;
      const titleEl = blockEl.querySelector(".step-head .step-title, .task-head .step-title");
      if (titleEl) {
        titleEl.textContent = String(step.title || "").trim() || defaultTitleForStepAction(step.action);
      }
    });
    containerEl.querySelectorAll("[data-generic-step-row]").forEach((node) => node.remove());
    genericRows.forEach((step, index) => {
      const cardEl = document.createElement("div");
      cardEl.className = "wizard-step";
      cardEl.dataset.genericStepRow = "1";
      const stepType = String(step.type || 'manual').trim() || 'manual';
      const headEl = document.createElement("div");
      headEl.className = "step-head";
      const numEl = document.createElement("span");
      numEl.className = "step-num";
      numEl.textContent = String(orderedBlockKeys.length + index + 1);
      const titleEl = document.createElement("span");
      titleEl.className = "step-title";
      titleEl.textContent = String(step.title || "").trim() || `手順${index + 1}`;
      const statusEl = document.createElement("span");
      statusEl.className = "step-status pending";
      statusEl.textContent =
        stepType === "browser" ? "Browser" : stepType === "agent" ? "Agent" : "手動";
      headEl.appendChild(numEl);
      headEl.appendChild(titleEl);
      headEl.appendChild(statusEl);
      const actionsEl = document.createElement("div");
      actionsEl.className = "step-actions";
      const noteEl = document.createElement("span");
      noteEl.className = "muted";
      if (stepType === "browser") {
        const targetUrl = String(step.target_url || "").trim();
        noteEl.textContent = targetUrl
          ? `Browser手順: ${targetUrl}`
          : "この手順はBrowserタスクです。";
      } else if (stepType === "agent") {
        const prompt = String(step.agent_prompt || "").trim();
        noteEl.textContent = prompt
          ? `Agent手順: ${prompt.slice(0, 60)}${prompt.length > 60 ? "..." : ""}`
          : "この手順はAgentタスクです。";
      } else {
        noteEl.textContent = "この手順は手動タスクです。";
      }
      actionsEl.appendChild(noteEl);
      cardEl.appendChild(headEl);
      cardEl.appendChild(actionsEl);
      containerEl.appendChild(cardEl);
    });

    workflowPage.steps = rows;
    syncWorkflowPageStepModelRows(rows);
  }

  function applyWorkflowPageSnapshot(nextPage) {
    if (!workflowPage || !nextPage || typeof nextPage !== "object") return;
    Object.keys(workflowPage).forEach((key) => {
      delete workflowPage[key];
    });
    Object.assign(workflowPage, nextPage);
    if (pageEl) {
      try {
        pageEl.dataset.workflowPage = JSON.stringify(workflowPage);
      } catch {
        // Best-effort only.
      }
    }
    applyWorkflowPageStepLayout(workflowPage.steps);
    renderWorkflowPageStepVersionLabel();
  }

  function showWorkflowPageStepEditorModal(initialSteps = []) {
    return new Promise((resolve) => {
      const { overlay, modal, panel } = createModalShell("手順編集");
      const body = document.createElement("div");
      body.className = "dialog-body";
      const note = document.createElement("p");
      note.className = "muted";
      note.textContent = "手順は自由に追加・削除できます。";
      body.appendChild(note);

      const listEl = document.createElement("div");
      listEl.className = "template-steps";
      body.appendChild(listEl);

      const addWrap = document.createElement("div");
      addWrap.className = "form-row";
      const addButton = document.createElement("button");
      addButton.type = "button";
      addButton.className = "secondary";
      addButton.textContent = "+ 手順を追加";
      addWrap.appendChild(addButton);
      body.appendChild(addWrap);
      panel.appendChild(body);

      const actionBar = document.createElement("div");
      actionBar.className = "dialog-actions";
      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "secondary";
      cancelButton.textContent = "キャンセル";
      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "primary";
      saveButton.textContent = "保存";
      actionBar.appendChild(cancelButton);
      actionBar.appendChild(saveButton);
      panel.appendChild(actionBar);

      const close = bindModalDismiss(overlay, modal, resolve);
      const state = normalizeWorkflowStepRows(initialSteps, {
        ensureRequired: false,
        includeTimer: true,
      }).map((row) => ({ ...row }));

      const normalizeState = () => {
        const normalized = normalizeWorkflowStepRows(state, {
          ensureRequired: false,
          includeTimer: true,
        });
        state.splice(0, state.length, ...normalized.map((row) => ({ ...row })));
      };

      const renderState = (focusIndex = -1) => {
        normalizeState();
        listEl.innerHTML = "";
        const optionalCount = state.filter((row) => !isRequiredTemplateStepAction(row.action)).length;
        state.forEach((row, index) => {
          const rowEl = document.createElement("div");
          rowEl.className = "template-step-row";

          const indexEl = document.createElement("span");
          indexEl.className = "muted";
          indexEl.textContent = `手順${index + 1}`;

          const titleEl = document.createElement("input");
          titleEl.type = "text";
          titleEl.required = true;
          titleEl.value = String(row.title || "").trim() || defaultTitleForStepAction(row.action, `手順${index + 1}`);
          titleEl.addEventListener("input", () => {
            state[index].title = String(titleEl.value || "").trim() || defaultTitleForStepAction(state[index].action);
          });

          const actionEl = document.createElement("select");
          actionEl.innerHTML = getTemplateStepActionOptionsHtml(row.action);
          const requiredAction = isRequiredTemplateStepAction(row.action);
          actionEl.disabled = requiredAction;
          actionEl.title = requiredAction ? "必須手順は変更できません。" : "";
          actionEl.addEventListener("change", () => {
            const nextAction = normalizeTemplateStepAction(actionEl.value);
            const duplicated = Boolean(nextAction)
              && state.some((step, stepIndex) => stepIndex !== index && step.action === nextAction);
            if (duplicated) {
              actionEl.value = state[index].action;
              showToast("同じ処理は1回だけ追加できます。", "error");
              return;
            }
            state[index].action = nextAction;
            if (!String(state[index].title || "").trim()) {
              state[index].title = defaultTitleForStepAction(nextAction);
            }
            renderState(index);
          });

          const timerEl = document.createElement("input");
          timerEl.type = "number";
          timerEl.min = String(TEMPLATE_STEP_TIMER_MIN_MINUTES);
          timerEl.max = String(TEMPLATE_STEP_TIMER_MAX_MINUTES);
          timerEl.step = "1";
          timerEl.value = String(normalizeTemplateStepTimerMinutes(row.timer_minutes));
          timerEl.title = "タイマー（分）";
          timerEl.addEventListener("change", () => {
            state[index].timer_minutes = normalizeTemplateStepTimerMinutes(timerEl.value);
            timerEl.value = String(state[index].timer_minutes);
          });

          const removeButton = document.createElement("button");
          removeButton.type = "button";
          removeButton.className = "secondary";
          removeButton.textContent = "-";
          removeButton.hidden = requiredAction || optionalCount <= 0;
          removeButton.disabled = requiredAction || optionalCount <= 0;
          removeButton.title = requiredAction ? "必須手順は削除できません。" : "";
          removeButton.addEventListener("click", () => {
            if (requiredAction) return;
            state.splice(index, 1);
            renderState(Math.max(0, index - 1));
          });

          rowEl.appendChild(indexEl);
          rowEl.appendChild(titleEl);
          rowEl.appendChild(actionEl);
          rowEl.appendChild(timerEl);
          rowEl.appendChild(removeButton);
          listEl.appendChild(rowEl);

          if (index === focusIndex) {
            titleEl.focus();
            titleEl.select();
          }
        });
      };

      addButton.addEventListener("click", () => {
        const usedActions = new Set(state.map((row) => String(row.action || "").trim()));
        const action = nextAvailableTemplateStepAction(usedActions);
        state.push({
          id: generateTemplateStepId(),
          title: "",
          action,
          type: 'manual',
          trigger: 'manual',
          target_url: "",
          agent_prompt: "",
          auto_run: false,
          timer_minutes: null,
          execution_log: [],
        });
        renderState(state.length - 1);
      });

      cancelButton.addEventListener("click", () => close(null));
      saveButton.addEventListener("click", () => {
        normalizeState();
        close(state.map((row) => ({ ...row })));
      });

      renderState();
    });
  }

  async function saveWorkflowPageSteps(nextSteps, { successMessage = "手順を更新しました。" } = {}) {
    const workflowPageId = String(workflowPage?.id || "").trim();
    if (!workflowPageId) return false;
    const payload = {
      steps: normalizeWorkflowStepRows(nextSteps, {
        ensureRequired: false,
        includeTimer: true,
      }),
      base_updated_at: String(workflowPage?.updated_at || ""),
      base_step_version: Number.parseInt(String(workflowPage?.step_version || 1), 10) || 1,
    };
    try {
      const res = await fetch(`/api/workflow-pages/${encodeURIComponent(workflowPageId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail) || "手順の更新に失敗しました。";
        showError(message);
        showToast(message, "error");
        return false;
      }
      const updatedPage = data.workflow_page && typeof data.workflow_page === "object" ? data.workflow_page : null;
      if (updatedPage) {
        applyWorkflowPageSnapshot(updatedPage);
      }
      showToast(successMessage, "success");
      return true;
    } catch {
      const message = "手順の更新に失敗しました。";
      showError(message);
      showToast(message, "error");
      return false;
    }
  }

  async function editWorkflowPageSteps() {
    const workflowPageId = String(workflowPage?.id || "").trim();
    if (!workflowPageId) return;
    const currentSteps = normalizeWorkflowStepRows(workflowPage?.steps, {
      ensureRequired: false,
      includeTimer: true,
    });
    const nextSteps = await showWorkflowPageStepEditorModal(currentSteps);
    if (!nextSteps) return;
    const normalizedNext = normalizeWorkflowStepRows(nextSteps, {
      ensureRequired: false,
      includeTimer: true,
    });
    if (JSON.stringify(currentSteps) === JSON.stringify(normalizedNext)) {
      showToast("変更はありません。", "info");
      return;
    }
    const saved = await saveWorkflowPageSteps(normalizedNext, {
      successMessage: "手順を更新しました。",
    });
    if (saved) {
      refreshSteps({ force: true });
    }
  }

  async function rollbackWorkflowPageSteps() {
    const workflowPageId = String(workflowPage?.id || "").trim();
    if (!workflowPageId) return;
    const versions = Array.isArray(workflowPage?.step_versions) ? workflowPage.step_versions : [];
    if (versions.length < 2) {
      showToast("戻せる前版がありません。", "info");
      return;
    }
    const currentVersion = Number.parseInt(String(workflowPage?.step_version || 1), 10) || 1;
    let targetRow = null;
    for (let i = versions.length - 1; i >= 0; i -= 1) {
      const row = versions[i];
      const version = Number.parseInt(String(row?.version || 0), 10);
      if (version > 0 && version < currentVersion) {
        targetRow = row;
        break;
      }
    }
    if (!targetRow) {
      targetRow = versions.length >= 2 ? versions[versions.length - 2] : null;
    }
    if (!targetRow) {
      showToast("戻せる前版がありません。", "info");
      return;
    }
    const targetVersion = Number.parseInt(String(targetRow.version || 0), 10) || 1;
    const targetSteps = normalizeWorkflowStepRows(targetRow.steps, {
      ensureRequired: false,
      includeTimer: true,
    });
    const confirmed = await showConfirmModal({
      title: "手順を前版に戻す",
      lines: [
        `迴ｾ蝨ｨ迚・ v${currentVersion}`,
        `戻し先: v${targetVersion}`,
        ...buildWorkflowStepPreviewLines(targetSteps).map((line) => `手順: ${line}`),
      ],
      confirmLabel: "前版を反映",
      cancelLabel: "キャンセル",
    });
    if (!confirmed) return;
    const saved = await saveWorkflowPageSteps(targetSteps, {
      successMessage: `手順を前版(v${targetVersion})の内容で復元しました。`,
    });
    if (saved) {
      refreshSteps({ force: true });
    }
  }

  async function saveWorkflowTemplate() {
    if (!form || templateSaveState.inFlight) return;
    if (!validateTemplateSourceUrls()) return;
    if (!validateTemplateStepRows()) return;
    const payload = buildTemplatePayload();
    if (!payload) return;
    if (!payload.name) {
      const message = "ワークフロー名を入力してください。";
      showError(message);
      showToast(message, "error");
      return;
    }
    const saveButton = document.getElementById("workflow-template-save");
    const config = getTemplateModeConfig("edit");
    const templateIdInput = form.querySelector("[name=template_id]");
    const templateModeInput = form.querySelector("[name=template_mode]");
    const templateUpdatedAtInput = form.querySelector("[name=template_updated_at]");
    const originalButtonLabel =
      config.saveLabel || (saveButton ? String(saveButton.textContent || "").trim() : "作成テンプレートを更新");
    templateSaveState.inFlight = true;
    if (saveButton) {
      saveButton.disabled = true;
      saveButton.dataset.busy = "1";
      saveButton.textContent = "保存中...";
    }
    clearError();

    try {
      const res = await fetch("/api/workflow-templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail) || "テンプレートの保存に失敗しました。";
        showError(message);
        showToast(message, "error");
        return;
      }

      const template = data.template || null;
      const templateId = String(template?.id || payload.template_id || "").trim();
      const year = Number(payload.year || 0);
      const month = Number(payload.month || 0);
      if (templateIdInput && templateId) {
        templateIdInput.value = templateId;
      }
      if (templateModeInput) {
        templateModeInput.value = "edit";
      }
      if (templateUpdatedAtInput && template) {
        templateUpdatedAtInput.value = String(template.updated_at || "");
      }
      const successMessage = config.successMessage;
      showToast(successMessage, "success");
      if (templateId && year && month) {
        window.location.href = `/expense-workflow-copy?template=${encodeURIComponent(templateId)}&year=${year}&month=${month}`;
        return;
      }
      showError("");
    } catch {
      const message = "テンプレートの保存に失敗しました。";
      showError(message);
      showToast(message, "error");
    } finally {
      if (saveButton) {
        saveButton.disabled = false;
        saveButton.textContent = originalButtonLabel;
        if (saveButton.dataset) {
          delete saveButton.dataset.busy;
        }
      }
      templateSaveState.inFlight = false;
    }
  }

  async function startRun(mode) {
    const payload = buildPayload(mode);
    if (!payload) return;

    clearError();
    showToast("(msg)", "success");

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
        logEl.textContent = "(msg)";
      }

      awaitingRunFinalization = true;
      updateRunSummary({
        run_id: data.run_id,
        status: "running",
        started_at: new Date().toLocaleString("ja-JP", { hour12: false }),
        params: { year: payload.year, month: payload.month },
      });
      runStatusById[data.run_id] = "running";
      showToast("(msg)", "success");

      startLogPolling(data.run_id);
      refreshLog(data.run_id);
      scheduleStepSync();
    } catch {
      awaitingRunFinalization = false;
      const message = "(msg)";
      showError(message);
      showToast(message, "error");
    }
  }

  function nextYm(ym) {
    const parsed = parseYm(ym);
    if (!parsed) return "";
    const year = parsed.year;
    const month = parsed.month;
    if (month >= 12) return `${year + 1}-01`;
    return `${year}-${String(month + 1).padStart(2, "0")}`;
  }

  function setYmToForm(ym) {
    const parsed = parseYm(ym);
    if (!parsed || !form) return;
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    if (yearEl) yearEl.value = String(parsed.year);
    if (monthEl) monthEl.value = String(parsed.month);
    persistYmSelection(parsed.ym);
  }

  function prependArchiveHistoryRow(entry) {
    if (!entry || typeof entry !== "object") return;
    const list = document.querySelector("[data-archive-history-list]");
    if (!(list instanceof HTMLElement)) return;
    const empty = list.querySelector("[data-archive-history-empty]");
    if (empty) empty.remove();

    const ym = String(entry.ym || "").trim();
    const ts = String(entry.ts || "").trim();
    const actionLabel = String(entry.action_label || "").trim() || "(msg)";
    const href = String(entry.archive_url || "").trim() || (ym ? `/runs/${ym}/archived-receipts` : "#");

    const item = document.createElement("li");
    item.className = "archive-history-item";
    const text = document.createElement("span");
    text.className = "muted";
    text.textContent = `${ts || "-"} / ${ym || "-"} / ${actionLabel}`;
    const link = document.createElement("a");
    link.className = "secondary";
    link.href = href;
    link.textContent = "(msg)";
    item.appendChild(text);
    item.appendChild(link);
    list.prepend(item);
  }

  async function runArchiveAction(action, buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("Enter target year-month first.", "error");
      return;
    }

    const normalizedAction = String(action || "").trim();
    if (!normalizedAction) return;
    if (buttonEl && buttonEl.dataset.busy === "1") return;
    if (buttonEl) buttonEl.dataset.busy = "1";

    const currentStep = getCurrentStep();
    if (!checkAndHandleChecklist(currentStep, false)) {
      if (buttonEl) delete buttonEl.dataset.busy;
      return;
    }

    const isMonthClose = normalizedAction === "month_close";
    try {
      const endpoint = isMonthClose ? `/api/month-close/${ym}` : `/api/archive/${ym}`;
      const res = await fetch(endpoint, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || (isMonthClose ? "Month-close failed." : "Archive failed."));
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
      const cleanupSuffix = Number.isFinite(cleanupRemoved) ? ` / cleanup removed: ${cleanupRemoved}` : "";
      const baseMessage = isMonthClose ? "Month-close finished" : "Archive finished";
      let message = archivedTo ? `${baseMessage}: ${archivedTo}${cleanupSuffix}` : `${baseMessage}${cleanupSuffix}`;
      if (isMonthClose) {
        const next = nextYm(ym);
        if (next) {
          setYmToForm(next);
          if (window.__stepState) window.__stepState = null;
          message += ` / switched target to ${next}`;
        }
      }
      prependArchiveHistoryRow(data.history_entry || null);
      showToast(message, "success");
    } catch {
      const message = normalizedAction === "month_close" ? "Month-close failed." : "Archive failed.";
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
      showToast("(msg)", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("(msg)", "success");
    try {
      const res = await fetch(`/api/manual/${ym}/import`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "Operation failed.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.found_pdfs ?? 0), 10) || 0;
      const imported = Number.parseInt(String(data.imported ?? 0), 10) || 0;
      const skipped = Number.parseInt(String(data.skipped_duplicates ?? 0), 10) || 0;
      const failed = Number.parseInt(String(data.failed ?? 0), 10) || 0;
      const message = `(msg)${found}(msg)${imported}(msg)${skipped}(msg)${failed}(msg)`;
      showToast(message, failed > 0 ? "error" : "success");
      if (failed > 0) {
        showError(message);
      }
    } catch {
      const message = "(msg)";
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
      showToast("(msg)", "error");
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
        const message = toFriendlyMessage(data.detail || "Failed to open MF bulk inbox.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath
        ? `MF(msg)${openedPath}`
        : "MF bulk inbox opened.";
      showToast(message, "success");
    } catch {
      const message = "MF(msg)";
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
      showToast("(msg)", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("MF(msg)", "success");
    try {
      const res = await fetch(`/api/mf-bulk-upload/${ym}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "MF bulk upload failed.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.files_found ?? 0), 10) || 0;
      const submitted = Number.parseInt(String(data.submitted_count ?? 0), 10) || 0;
      const queued = Number.parseInt(String(data.queued_count ?? 0), 10) || 0;
      const readCount = Number.parseInt(String(data.read_count ?? 0), 10) || 0;
      const archivedDir = String(data.archived_dir || "").trim();
      const details = archivedDir ? ` / (msg)${archivedDir}` : "";
      const message = `MF(msg)${found}(msg)${readCount}(msg)${queued}(msg)${submitted}(msg)${details}`;
      showToast(message, "success");
    } catch {
      const message = "MF(msg)";
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function openMfCsvInbox(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("(msg)", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    try {
      const res = await fetch(`/api/folders/${ym}/mf-csv-inbox`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "Failed to open MF CSV inbox.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const message = openedPath
        ? `(msg)${openedPath}`
        : "MF CSV inbox opened.";
      showToast(message, "success");
    } catch {
      const message = "(msg)";
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function runMfCsvImport(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("(msg)", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("(msg)", "success");
    try {
      const res = await fetch(`/api/mf-csv-import/${ym}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "MF CSV import failed.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.files_found ?? 0), 10) || 0;
      const submitted = Number.parseInt(String(data.submitted_count ?? 0), 10) || 0;
      const queued = Number.parseInt(String(data.queued_count ?? 0), 10) || 0;
      const archivedDir = String(data.archived_dir || "").trim();
      const details = archivedDir ? ` / (msg)${archivedDir}` : "";
      const message = `(msg)${found}(msg)${queued}(msg)${submitted}(msg)${details}`;
      showToast(message, "success");
    } catch {
      const message = "(msg)";
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
      return;
    }
    if (action === "open_mf_csv_inbox") {
      openMfCsvInbox(buttonEl);
      return;
    }
    if (action === "run_mf_csv_import") {
      runMfCsvImport(buttonEl);
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
      showToast("(msg)", "error");
      return;
    }
    if (!normalizedProvider) {
      showToast("(msg)", "error");
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
        const message = toFriendlyMessage(data.detail || "Failed to open provider inbox.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      const label = providerLabel(normalizedProvider);
      const message = openedPath ? `${label} inbox opened: ${openedPath}` : `${label} inbox opened.`;
      showToast(message, "success");
    } catch {
      const message = "(msg)";
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  async function openProviderSource(buttonEl) {
    const ym = getYmFromForm();
    if (!ym) {
      showToast("(msg)", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    try {
      const res = await fetch(`/api/folders/${ym}/provider-source`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "Provider source folder could not be opened.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const openedPath = String(data.path || "").trim();
      renderProviderSourceSummary(data.source_status || data.providers?.source);
      const message = openedPath ? `Provider source folder opened: ${openedPath}` : "Provider source folder opened.";
      showToast(message, "success");
    } catch {
      const message = "Provider source folder could not be opened.";
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
      showToast("(msg)", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("(msg)", "success");
    try {
      const res = await fetch(`/api/providers/${ym}/import`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "Provider import failed.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const found = Number.parseInt(String(data.found_files ?? 0), 10) || 0;
      const imported = Number.parseInt(String(data.imported ?? 0), 10) || 0;
      const skipped = Number.parseInt(String(data.skipped_duplicates ?? 0), 10) || 0;
      const failed = Number.parseInt(String(data.failed ?? 0), 10) || 0;
      const message = `(msg)${found}(msg)${imported}(msg)${skipped}(msg)${failed}(msg)`;
      const manualActionRequired = Boolean(data.manual_action_required) || skipped > 0 || failed > 0;
      if (!manualActionRequired) {
        showToast(message, "success");
        return;
      }

      const details = [message, "Manual action required."];
      let skippedFolderPath = String(data.skipped_dir || "").trim();
      if (skipped > 0) {
        const openSkippedRes = await fetch(`/api/folders/${ym}/provider-skipped/latest`, { method: "POST" });
        const openSkippedData = await openSkippedRes.json().catch(() => ({}));
        if (openSkippedRes.ok) {
          const opened = String(openSkippedData.path || "").trim();
          if (opened) skippedFolderPath = opened;
        }
      }
      if (skippedFolderPath) {
        details.push(`(msg)${skippedFolderPath}`);
      }
      const skippedFiles = Array.isArray(data.skipped_files)
        ? data.skipped_files.map((value) => String(value || "").trim()).filter((value) => value)
        : [];
      if (skippedFiles.length > 0) {
        const preview = skippedFiles.slice(0, 8);
        const suffix = skippedFiles.length > preview.length ? ` (msg)` : "";
        details.push(`(msg)${preview.join(", ")}${suffix}`);
      }
      const errorMessage = details.join("\n");
      showError(errorMessage);
      showToast("(msg)", "error");
    } catch {
      const message = "(msg)";
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
      showToast("(msg)", "error");
      return;
    }

    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.dataset.busy = "1";
    }
    clearError();
    showToast("(msg)", "success");
    try {
      const res = await fetch(`/api/providers/${ym}/print-run`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = toFriendlyMessage(data.detail || "Provider print task failed.");
        showError(message);
        showToast(message, "error");
        return;
      }
      const count = Number.parseInt(String(data.count ?? 0), 10) || 0;
      const message = `${Math.max(0, count)} file(s) queued for print.`;
      showToast(message, "success");
    } catch {
      const message = "(msg)";
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) delete buttonEl.dataset.busy;
      refreshSteps({ force: true });
    }
  }

  function runProviderAction(action, provider, buttonEl) {
    if (action === "open_provider_source") {
      openProviderSource(buttonEl);
      return;
    }
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
      showToast("(msg)", "error");
      return;
    }
    const labelByStep = {
      amazon_download: "Amazon download",
      amazon_decide_print: "Amazon print decision",
      rakuten_download: "Rakuten download",
      rakuten_decide_print: "Rakuten print decision",
    };
    const label = labelByStep[String(stepId || "")] || String(stepId || "");
    const confirmed = window.confirm(`Reset step "${label}"?`);
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
      showToast(
        cancelledCount > 0
          ? `Step reset completed. Cancelled ${cancelledCount} running task(s).`
          : "Step reset completed.",
        "success",
      );
      scheduleStepSync();
      if (activeLogRunId) {
        refreshLog(activeLogRunId);
      }
    } catch {
      const message = "(msg)";
      showError(message);
      showToast(message, "error");
    } finally {
      if (buttonEl) buttonEl.disabled = false;
    }
  }


window.DashboardIndexApi = {
  apiGetJson,
  showError,
  clearError,
  scheduleStepSync,
  fetchStatus,
  isStepReflected,
  syncAfterRunCompletion,
  startLogPolling,
  stopLogPolling,
  normalizeStatusForDot,
  toYmText,
  updateRunSummary,
  refreshLog,
  buildPayload,
  resolveFormYearMonth,
  buildTemplatePayload,
  buildWorkflowPagePayload,
  createWorkflowPage,
  editWorkflowPageSettings,
  archiveCurrentWorkflowPage,
  showWorkflowPageStepEditorModal,
  saveWorkflowPageSteps,
  editWorkflowPageSteps,
  rollbackWorkflowPageSteps,
  saveWorkflowTemplate,
  startRun,
  prependArchiveHistoryRow,
  runArchiveAction,
  importManualReceipts,
  openMfBulkInbox,
  runMfBulkUpload,
  openMfCsvInbox,
  runMfCsvImport,
  runManualAction,
  providerLabel,
  openProviderInbox,
  openProviderSource,
  importProviderReceipts,
  printProviderReceipts,
  runProviderAction,
};
