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
    applyArchivePageLink(ym);

    try {
      const raw = await apiGetJson(`/api/steps/${ym}`);
      if (!raw) {
        renderNextStep("Status fetch failed. Retrying...");
        document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
        applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
        applyManualAvailability({ running_mode: "" });
        renderProviderSourceSummary(null, "Provider source folder status is unavailable.");
        renderProviderImportSummary(null, "", "Provider import result is unavailable.");
        renderMfSummary(null, "MF summary unavailable.");
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
        providers: raw.providers || {},
        mf_bulk_upload: raw.mf_bulk_upload || {},
        mf_csv_import: raw.mf_csv_import || {},
        archive: raw.archive || {},
        mf: raw.mf || {},
        running_mode: raw.running_mode || "",
        next_step: raw.next_step || "",
        allowed_run_modes: Array.isArray(raw.allowed_run_modes) ? raw.allowed_run_modes : [],
      };
      const archiveOverride = archiveStateOverrides[ym];
      if (archiveOverride && !(data.archive && data.archive.created)) {
        data.archive = { ...(data.archive || {}), ...archiveOverride, created: true };
      }

      const runningMode = String(data.running_mode || "");

      applyActionAvailability(data);
      await loadMonthCloseChecklist(ym);
      applyArchiveAvailability(data);
      applyManualAvailability(data);
      applyProviderAvailability(data);
      renderProviderSourceSummary(data.providers?.source);
      renderProviderImportSummary(data.providers, runningMode);
      applyLinkAvailability(data, ym);
      renderMfSummary(data);

      const stepStates = buildStepStates(data, runningMode);
      setStepStatus("preflight", stepStates.preflight);
      setStepStatus("amazon_download", stepStates.amazon_download);
      setStepStatus("amazon_decide_print", stepStates.amazon_decide_print);
      setStepStatus("rakuten_download", stepStates.rakuten_download);
      setStepStatus("rakuten_decide_print", stepStates.rakuten_decide_print);
      setStepStatus("provider_ingest", stepStates.provider_ingest);
      setStepStatus("mf_bulk_upload_task", stepStates.mf_bulk_upload_task);
      setStepStatus("mf_reconcile", stepStates.mf_reconcile);
      const taskStates = buildTaskStates(stepStates);
      setTaskStatus("amazon", taskStates.amazon);
      setTaskStatus("rakuten", taskStates.rakuten);

  const labels = {
    preflight: "事前準備",
    amazon_download: "Amazon取り込み",
    amazon_decide_print: "Amazon除外・印刷",
    rakuten_download: "楽天取り込み",
    rakuten_decide_print: "楽天除外・印刷",
    provider_ingest: "プロバイダ受領分の取り込み",
    mf_bulk_upload_task: "MF一括アップロード",
    mf_reconcile: "MF突合",
  };
      if (!window.__stepState) {
        window.__stepState = stepStates;
      } else {
        Object.keys(stepStates).forEach((key) => {
          if (key === "mf_reconcile") return;
          if (window.__stepState[key] && window.__stepState[key] !== "done" && stepStates[key] === "done") {
            showToast(`${labels[key]}が完了しました。`, "success");
          }
        });
      }
      window.__stepState = stepStates;
      const next = computeNextStep(data, ym);
      renderNextStep(next.message, next.href, next.reason, next.linkLabel);
      if (stepRetryTimer) {
        clearTimeout(stepRetryTimer);
        stepRetryTimer = null;
      }
      return data;


    } catch {
      renderNextStep("Step refresh failed.");
      document.querySelectorAll("[data-step-link]").forEach((link) => setStepLinkState(link, false, "#"));
      applyArchiveAvailability({ running_mode: "", amazon: {}, rakuten: {} });
      applyManualAvailability({ running_mode: "" });
      applyProviderAvailability({ running_mode: "", preflight: {} });
      renderProviderSourceSummary(null, "Failed to refresh provider status.");
      renderProviderImportSummary(null, "", "Failed to refresh provider import status.");
      renderMfSummary(null, "MF summary unavailable.");
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
          return;
        }
        if (button.dataset.archiveAction === "month_close") {
          monthClose(button);
        }
      });
    });

    document.querySelectorAll("[data-manual-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        runManualAction(String(button.dataset.manualAction || ""), button);
      });
    });

    document.querySelectorAll("[data-provider-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        runProviderAction(String(button.dataset.providerAction || ""), String(button.dataset.provider || ""), button);
      });
    });

    document.querySelectorAll("[data-step-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        if (link.getAttribute("aria-disabled") === "true") {
          event.preventDefault();
          showToast("(msg)", "error");
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

    const handleYmChanged = () => {
      const ym = getYmFromForm();
      persistYmSelection(ym);
      applyArchivePageLink(ym);
      refreshSteps();
    };

    const safeInit = (fn, label) => {
      try {
        fn();
      } catch (error) {
        console.error(`[index.events] ${label} failed`, error);
      }
    };

    const templateStepAddButton = document.getElementById("template-step-add");
    if (templateStepAddButton && templateStepAddButton.dataset.boundTemplateStepAdd !== "1") {
      templateStepAddButton.dataset.boundTemplateStepAdd = "1";
      templateStepAddButton.addEventListener("click", (event) => {
        event.preventDefault();
        addTemplateStepFromDefaultCard({});
      });
    }

    safeInit(hydrateTemplateSourceUrls, "hydrateTemplateSourceUrls");
    safeInit(applyTemplateModeUI, "applyTemplateModeUI");
    const templateSourceUrlAddButton = document.getElementById("template-source-url-add");
    templateSourceUrlAddButton?.addEventListener("click", (event) => {
      event.preventDefault();
      addTemplateSourceUrlRow("");
    });
    const onTemplateStepToggle = (event) => {
      const toggleButton = event.target.closest("[data-template-step-toggle]");
      if (!toggleButton) return;
      const row = toggleButton.closest("[data-template-step-row]");
      if (!(row instanceof HTMLElement) || row.dataset.templateStepRow !== "1") return;

      const currentMode = normalizeTemplateStepUiMode(
        row.dataset.templateStepUiMode,
        TEMPLATE_STEP_UI_MODE_DEFAULT,
      );
      const nextMode =
        currentMode === TEMPLATE_STEP_UI_MODE.advanced
          ? TEMPLATE_STEP_UI_MODE.compact
          : TEMPLATE_STEP_UI_MODE.advanced;
      row.dataset.templateStepUiMode = nextMode;
      row.dataset.templateStepAutoTimer = nextMode === TEMPLATE_STEP_UI_MODE.advanced ? "1" : "0";
      refreshTemplateStepRows();
    };
    getTemplateStepsListEl()?.addEventListener("click", onTemplateStepToggle);
    const workflowPageCreateButton = document.getElementById("workflow-page-create");
    workflowPageCreateButton?.addEventListener("click", (event) => {
      event.preventDefault();
      createWorkflowPage();
    });
    const workflowPageEditButton = document.getElementById("workflow-page-edit");
    workflowPageEditButton?.addEventListener("click", (event) => {
      event.preventDefault();
      editWorkflowPageSettings();
    });
    const workflowPageArchiveButton = document.getElementById("workflow-page-archive");
    workflowPageArchiveButton?.addEventListener("click", (event) => {
      event.preventDefault();
      archiveCurrentWorkflowPage();
    });
    const workflowPageEditStepsButton = document.getElementById("workflow-page-edit-steps");
    workflowPageEditStepsButton?.addEventListener("click", (event) => {
      event.preventDefault();
      editWorkflowPageSteps();
    });
    const workflowPageRollbackButton = document.getElementById("workflow-page-rollback-steps");
    workflowPageRollbackButton?.addEventListener("click", (event) => {
      event.preventDefault();
      rollbackWorkflowPageSteps();
    });
    const workflowPageLifecycleToggleButton = document.getElementById("workflow-page-lifecycle-toggle");
    workflowPageLifecycleToggleButton?.addEventListener("click", (event) => {
      event.preventDefault();
      toggleWorkflowPageLifecycle();
    });
    const onTemplateHeaderChanged = () => {
      syncTemplatePageHeader();
      renderWorkflowCreatePreview();
    };
    form.querySelector("[name=template_name]")?.addEventListener("input", onTemplateHeaderChanged);
    form.querySelector("[name=template_subheading]")?.addEventListener("input", onTemplateHeaderChanged);
    form.querySelector("[name=year]")?.addEventListener("change", handleYmChanged);
    form.querySelector("[name=month]")?.addEventListener("change", handleYmChanged);
    const templateSaveButton = document.getElementById("workflow-template-save");
    templateSaveButton?.addEventListener("click", (event) => {
      event.preventDefault();
      saveWorkflowTemplate();
    });
    const templateStepsListEl = getTemplateStepsListEl();
    templateStepsListEl?.addEventListener("template-steps-changed", () => {
      renderWorkflowCreatePreview();
    });

    safeInit(hydrateTemplateSteps, "hydrateTemplateSteps");
    safeInit(renderWorkflowCreatePreview, "renderWorkflowCreatePreview");
    safeInit(() => applyWorkflowPageStepLayout(workflowPage?.steps), "applyWorkflowPageStepLayout");
    safeInit(renderWorkflowPageStepVersionLabel, "renderWorkflowPageStepVersionLabel");
    safeInit(syncWorkflowPageLifecycleUi, "syncWorkflowPageLifecycleUi");
    safeInit(initWorkflowPageMoreMenu, "initWorkflowPageMoreMenu");
    safeInit(restoreYmSelection, "restoreYmSelection");
    const initialYm = getYmFromForm();
    applyArchivePageLink(initialYm);
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
        const message = "(msg)";
        showError(message);
        showToast(message, "error");
        return;
      }
      const message = "(msg)";
      showError(message);
      showToast(message, "success");
    });
  }

  bindCopyButtons();

  // ========== Month Close Checklist ==========
  async function loadMonthCloseChecklist(ym) {
    if (!ym) return;
    try {
      const data = await apiGetJson(`/api/month-close-checklist/${ym}`);
      if (data && data.checklist) {
        checklistState = normalizeChecklistState(data.checklist);
        updateCheckboxes();
      }
    } catch (err) {
      console.warn("Failed to load checklist:", err);
    }
  }

  async function saveMonthCloseChecklist(ym) {
    if (!ym) return;
    try {
      const res = await fetch(`/api/month-close-checklist/${ym}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checklist: normalizeChecklistState(checklistState) }),
      });
      if (!res.ok) {
        console.warn("Failed to save checklist:", res.statusText);
      }
    } catch (err) {
      console.warn("Failed to save checklist:", err);
    }
  }

  function updateCheckboxes() {
    document.querySelectorAll("[data-checklist-item]").forEach((checkbox) => {
      const key = checkbox.dataset.checklistItem;
      if (key in checklistState) {
        checkbox.checked = checklistState[key];
      }
    });
  }

  function initWorkflowPageMoreMenu() {
    const toggleButton = document.getElementById("workflow-page-more-toggle");
    const menuEl = document.getElementById("workflow-page-more-menu");
    if (!(toggleButton instanceof HTMLElement) || !(menuEl instanceof HTMLElement)) return;

    const closeMenu = ({ returnFocus = false } = {}) => {
      menuEl.hidden = true;
      toggleButton.setAttribute("aria-expanded", "false");
      if (returnFocus) toggleButton.focus();
    };
    const openMenu = () => {
      menuEl.hidden = false;
      toggleButton.setAttribute("aria-expanded", "true");
    };

    toggleButton.addEventListener("click", (event) => {
      event.preventDefault();
      if (menuEl.hidden) {
        openMenu();
        const firstItem = menuEl.querySelector("button[role='menuitem']");
        if (firstItem instanceof HTMLElement) {
          firstItem.focus();
        }
        return;
      }
      closeMenu({ returnFocus: true });
    });

    menuEl.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeMenu({ returnFocus: true });
    });

    document.addEventListener("click", (event) => {
      if (menuEl.hidden) return;
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (menuEl.contains(target) || toggleButton.contains(target)) return;
      closeMenu();
    });
  }

  // Bind checkbox change events
  document.querySelectorAll("[data-checklist-item]").forEach((checkbox) => {
    checkbox.addEventListener("change", async (e) => {
      const key = e.target.dataset.checklistItem;
      if (key in checklistState) {
        checklistState[key] = e.target.checked;
        const ym = getYmFromForm();
        await saveMonthCloseChecklist(ym);
        // Refresh steps to update button state
        refreshSteps({ force: true });
      }
    });
  });

window.DashboardIndexEvents = {
  refreshSteps,
  loadMonthCloseChecklist,
  saveMonthCloseChecklist,
  updateCheckboxes,
};
