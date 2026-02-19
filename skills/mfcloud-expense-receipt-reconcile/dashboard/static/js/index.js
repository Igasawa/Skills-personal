(function () {
  // UI copy is centralized in this file.
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const pageEl = document.querySelector(".page");
  const form = document.getElementById("run-form");
  const logEl = document.getElementById("run-log");
  const errorBox = document.getElementById("error-box");
  const stopButton = document.getElementById("stop-run");
  const wizardNext = document.getElementById("wizard-next");
  const latestRunDotEl = document.querySelector("[data-latest-run-dot]");
  const latestRunStatusEl = document.querySelector("[data-latest-run-status]");
  const latestRunTimeEl = document.querySelector("[data-latest-run-time]");
  const latestRunIdEl = document.querySelector("[data-latest-run-id]");
  const latestRunYmEl = document.querySelector("[data-latest-run-ym]");
  const latestRunLinkEl = document.querySelector("[data-latest-run-link]");
  const logRunIdEl = document.querySelector("[data-log-run-id]");
  const logRunStatusEl = document.querySelector("[data-log-run-status]");

  const runStatusById = {};
  let awaitingRunFinalization = false;
  let stepRetryTimer = null;
  let activeLogRunId = "";
  let stepRefreshInFlight = false;
  let stepRefreshStartedAt = 0;
  let stepFocusTimer = null;
  let autoReloadScheduled = false;
  const REQUEST_TIMEOUT_MS = 12000;
  const STEP_REFRESH_STALE_MS = 15000;
  const archiveStateOverrides = Object.create(null);
  const PROVIDER_SOURCE_SETUP_GUIDE_URL =
    "https://github.com/Igasawa/Skills-personal/blob/main/skills/mfcloud-expense-receipt-reconcile/SKILL.md";

  const monthCloseChecklistKeys = ["expense_submission", "document_printout", "mf_accounting_link"];
  const YM_STORAGE_KEY = "mfcloud.dashboard.selectedYm";
  const YM_PATTERN = /^(\d{4})-(\d{2})$/;
  const TEMPLATE_STEP_DEFAULT_ACTION = "preflight";
  // Canonical action list is mirror of API validation (`WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS`)
  // and scheduler action whitelist (`SCHEDULER_ALLOWED_ACTION_KEYS`).
  const TEMPLATE_STEP_ACTIONS = [
    { value: "preflight", label: "手順0（準備）" },
    { value: "preflight_mf", label: "手順0（MFのみ）" },
    { value: "amazon_download", label: "手順1（Amazon取得）" },
    { value: "rakuten_download", label: "手順2（楽天取得）" },
    { value: "amazon_print", label: "Amazon除外判断・印刷" },
    { value: "rakuten_print", label: "楽天除外判断・印刷" },
    { value: "provider_ingest", label: "手順3（共通フォルダ取り込み）" },
    { value: "mf_bulk_upload_task", label: "手順4（MF一括アップロード）" },
    { value: "mf_reconcile", label: "MF遯∝粋" },
    { value: "month_close", label: "手順6（月次クローズ）" },
  ];
  const TEMPLATE_STEP_ACTION_LABELS = Object.fromEntries(TEMPLATE_STEP_ACTIONS.map((item) => [item.value, item.label]));
  const TEMPLATE_REQUIRED_STEPS = [
    { action: "preflight", title: "手順0 準備（ログイン確認・MF連携更新）" },
    { action: "mf_reconcile", title: "手順5 MF突合・下書き作成" },
  ];
  const TEMPLATE_REQUIRED_STEP_ACTION_SET = new Set(TEMPLATE_REQUIRED_STEPS.map((row) => row.action));
  const TEMPLATE_STEP_DEFAULT_TITLES = {
    preflight: "手順0 準備（ログイン確認・MF連携更新）",
    preflight_mf: "手順0 MF再取得のみ",
    amazon_download: "手順1 Amazon領収書取得",
    amazon_print: "手順1 Amazon除外判断・印刷",
    rakuten_download: "手順2 楽天領収書取得",
    rakuten_print: "手順2 楽天除外判断・印刷",
    provider_ingest: "手順3 共通フォルダ取り込み",
    mf_bulk_upload_task: "手順4 MF一括アップロード",
    mf_reconcile: "手順5 MF突合・下書き作成",
    month_close: "手順6 月次クローズ",
  };
  const WORKFLOW_STEP_BLOCK_KEYS_BY_ACTION = {
    preflight: "preflight",
    preflight_mf: "preflight",
    amazon_download: "amazon",
    amazon_print: "amazon",
    rakuten_download: "rakuten",
    rakuten_print: "rakuten",
    provider_ingest: "provider_ingest",
    mf_bulk_upload_task: "mf_bulk_upload_task",
    mf_reconcile: "mf_reconcile",
    month_close: "month_close",
  };
  const WORKFLOW_STEP_BLOCK_SELECTORS = {
    preflight: "#step-preflight",
    amazon: "#step-amazon-task",
    rakuten: "#step-rakuten-task",
    provider_ingest: "#step-provider-ingest",
    mf_bulk_upload_task: "#step-mf-bulk-upload-task",
    mf_reconcile: "#step-mf-reconcile",
    month_close: "#step-month-close",
  };
  const WORKFLOW_ACTIONS_BY_BLOCK_KEY = {
    preflight: ["preflight", "preflight_mf"],
    amazon: ["amazon_download", "amazon_print"],
    rakuten: ["rakuten_download", "rakuten_print"],
    provider_ingest: ["provider_ingest"],
    mf_bulk_upload_task: ["mf_bulk_upload_task"],
    mf_reconcile: ["mf_reconcile"],
    month_close: ["month_close"],
  };
  const WORKFLOW_STEP_BLOCK_ORDER = [
    "preflight",
    "amazon",
    "rakuten",
    "provider_ingest",
    "mf_bulk_upload_task",
    "mf_reconcile",
    "month_close",
  ];
  const TEMPLATE_STEP_ACTION_VALUES = new Set(TEMPLATE_STEP_ACTIONS.map((item) => item.value));
  const templateSaveState = { inFlight: false };
  const workflowPageCreateState = { inFlight: false };
  let activeTemplateStepDragRow = null;
  const TEMPLATE_MODE_CONFIG = {
    edit: {
      chip: "邱ｨ髮・,
      saveLabel: "作成テンプレートを更新",
      description: "作成元テンプレートを編集中です。保存すると現在のテンプレート設定を更新します。",
      summary: "フォームモード: 編集",
      successMessage: "作成テンプレートを更新しました。",
    },
  };

  function normalizeYm(yearValue, monthValue) {
    const year = Number.parseInt(String(yearValue ?? "").trim(), 10);
    const month = Number.parseInt(String(monthValue ?? "").trim(), 10);
    if (!Number.isInteger(year) || year < 1) return "";
    if (!Number.isInteger(month) || month < 1 || month > 12) return "";
    return `${year.toString().padStart(4, "0")}-${String(month).padStart(2, "0")}`;
  }

  function parseYm(ymValue) {
    const text = String(ymValue || "").trim();
    const match = text.match(YM_PATTERN);
    if (!match) return null;
    const year = Number.parseInt(match[1], 10);
    const month = Number.parseInt(match[2], 10);
    if (!Number.isInteger(year) || year < 1) return null;
    if (!Number.isInteger(month) || month < 1 || month > 12) return null;
    return { year, month, ym: `${year.toString().padStart(4, "0")}-${String(month).padStart(2, "0")}` };
  }

  function parseWorkflowTemplate(page) {
    if (!page) return null;
    const raw = String(page.dataset.workflowTemplate || "").trim();
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      // Ignore malformed metadata.
    }
    return null;
  }

  function parseWorkflowPage(page) {
    if (!page) return null;
    const raw = String(page.dataset.workflowPage || "").trim();
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      // Ignore malformed metadata.
    }
    return null;
  }

  const workflowTemplate = parseWorkflowTemplate(pageEl);
  const workflowPage = parseWorkflowPage(pageEl);

  function defaultTitleForStepAction(action, fallback = "") {
    const normalizedAction = String(action || "").trim();
    const fallbackTitle = String(fallback || "").trim();
    if (fallbackTitle) return fallbackTitle;
    return TEMPLATE_STEP_DEFAULT_TITLES[normalizedAction] || TEMPLATE_STEP_ACTION_LABELS[normalizedAction] || "Task";
  }

  function normalizeTemplateStepAutoRun(value) {
    if (typeof value === "boolean") return value;
    const text = String(value ?? "").trim().toLowerCase();
    if (!text) return false;
    return ["1", "true", "yes", "on"].includes(text);
  }

  function normalizeTemplateStepOrder(value, fallback = 1) {
    const parsed = Number.parseInt(String(value ?? "").trim(), 10);
    if (!Number.isInteger(parsed) || parsed < 1) return fallback;
    return parsed;
  }

  function normalizeTemplateStepExecutionLog(value) {
    const rows = Array.isArray(value) ? value : [];
    const normalized = [];
    rows.forEach((row) => {
      if (!(row && typeof row === "object")) return;
      const rawResult = String(row.result || "").trim().toLowerCase();
      const result = rawResult === "failed" ? "failed" : "success";
      const executedAt = String(row.executed_at ?? row.executedAt ?? "").trim();
      const message = String(row.message || "").trim().slice(0, TEMPLATE_STEP_EXECUTION_LOG_MESSAGE_MAX_CHARS);
      if (!executedAt && !message) return;
      normalized.push({
        executed_at: executedAt,
        result,
        message,
      });
    });
    if (normalized.length > TEMPLATE_STEP_EXECUTION_LOG_MAX_ITEMS) {
      return normalized.slice(-TEMPLATE_STEP_EXECUTION_LOG_MAX_ITEMS);
    }
    return normalized;
  }

  function normalizeTemplateStepTimerForAutoRun(value) {
    const normalized = normalizeTemplateStepTimerMinutes(value, TEMPLATE_STEP_TIMER_DEFAULT_MINUTES);
    if (!Number.isInteger(normalized) || normalized < TEMPLATE_STEP_TIMER_REQUIRED_MINUTES) {
      return TEMPLATE_STEP_TIMER_DEFAULT_MINUTES;
    }
    return normalized;
  }

  function normalizeWorkflowStepRows(rawRows, options = {}) {
    const rows = Array.isArray(rawRows) ? rawRows : [];
    const ensureRequired = options.ensureRequired !== false;
    const includeTimer = options.includeTimer !== false;
    const seen = new Set();
    const normalized = [];

    rows.forEach((row, index) => {
      const raw = row && typeof row === "object" ? row : {};
      const action = normalizeTemplateStepAction(raw.action);
      if (!action || seen.has(action)) return;
      const title = String(raw.title || "").trim() || defaultTitleForStepAction(action, `Task ${index + 1}`);
      const id = String(raw.id || "").trim() || generateTemplateStepId();
      const autoRun = normalizeTemplateStepAutoRun(raw.auto_run ?? raw.autoRun);
      const timerRaw = raw.timer_minutes ?? raw.timer;
      const timerProvided = Object.prototype.hasOwnProperty.call(raw, "timer_minutes") || Object.prototype.hasOwnProperty.call(raw, "timer");
      let timerMinutes = timerProvided ? normalizeTemplateStepTimerMinutes(timerRaw, null) : null;
      if (autoRun) {
        timerMinutes = normalizeTemplateStepTimerForAutoRun(timerMinutes);
      }
      const executionLog = normalizeTemplateStepExecutionLog(raw.execution_log ?? raw.executionLog);
      const order = normalizeTemplateStepOrder(raw.order, index + 1);
      seen.add(action);
      const nextRow = {
        id,
        order,
        title,
        action,
        auto_run: autoRun,
        execution_log: executionLog,
      };
      if (includeTimer) {
        nextRow.timer_minutes = timerMinutes;
      }
      normalized.push(nextRow);
    });

    if (ensureRequired) {
      const byAction = new Map(normalized.map((row) => [String(row.action || "").trim(), row]));
      const requiredRows = TEMPLATE_REQUIRED_STEPS.map((requiredStep) => {
        const existing = byAction.get(requiredStep.action);
        if (existing) return existing;
        const nextRow = {
          id: generateTemplateStepId(),
          title: defaultTitleForStepAction(requiredStep.action, requiredStep.title),
          action: requiredStep.action,
          auto_run: false,
          execution_log: [],
        };
        if (includeTimer) {
          nextRow.timer_minutes = null;
        }
        return nextRow;
      });
      const optionalRows = normalized.filter((row) => !isRequiredTemplateStepAction(row.action));
      normalized.splice(0, normalized.length, ...requiredRows, ...optionalRows);
    }

    const limited = normalized.filter((row) => TEMPLATE_STEP_ACTION_VALUES.has(String(row.action || "").trim()));
    if (limited.length === 0) {
      const fallbackAction = TEMPLATE_REQUIRED_STEPS[0]?.action || TEMPLATE_STEP_DEFAULT_ACTION;
      const nextRow = {
        id: generateTemplateStepId(),
        title: defaultTitleForStepAction(fallbackAction),
        action: fallbackAction,
        auto_run: false,
        execution_log: [],
      };
      if (includeTimer) {
        nextRow.timer_minutes = null;
      }
      limited.push(nextRow);
    }
    return limited.map((row, index) => ({
      ...row,
      order: index + 1,
    }));
  }

  function isRequiredTemplateStepAction(action) {
    return TEMPLATE_REQUIRED_STEP_ACTION_SET.has(String(action || "").trim());
  }

  function actionToWorkflowBlockKey(action) {
    const normalized = String(action || "").trim();
    return WORKFLOW_STEP_BLOCK_KEYS_BY_ACTION[normalized] || "";
  }

  function nextAvailableTemplateStepAction(usedActions = new Set()) {
    const used = usedActions instanceof Set ? usedActions : new Set();
    for (const row of TEMPLATE_STEP_ACTIONS) {
      const action = String(row?.value || "").trim();
      if (!action || used.has(action) || isRequiredTemplateStepAction(action)) continue;
      return action;
    }
    for (const row of TEMPLATE_STEP_ACTIONS) {
      const action = String(row?.value || "").trim();
      if (!action || used.has(action)) continue;
      return action;
    }
    return TEMPLATE_STEP_DEFAULT_ACTION;
  }

  function getTemplateMode() {
    return "edit";
  }

  function getTemplateModeConfig(mode) {
    return TEMPLATE_MODE_CONFIG[mode] || TEMPLATE_MODE_CONFIG.edit;
  }

  function syncTemplatePageHeader() {
    const titleEl = document.getElementById("workflow-template-page-title");
    const subheadingEl = document.getElementById("workflow-template-page-subheading");
    const nameInput = form?.querySelector("[name=template_name]");
    const subheadingInput = form?.querySelector("[name=template_subheading]");
    if (!titleEl && !subheadingEl && !nameInput && !subheadingInput) return;
    const fallbackTitle = String(titleEl?.dataset.defaultTitle || "").trim() || "ワークフロー作成テンプレート";
    const title = String(nameInput?.value || workflowTemplate?.name || "").trim() || fallbackTitle;
    const subheading = String(subheadingInput?.value || workflowTemplate?.subheading || "").trim();

    if (titleEl) {
      titleEl.textContent = title;
    }
    if (subheadingEl) {
      subheadingEl.textContent = subheading;
      subheadingEl.hidden = !subheading;
    }
    if (titleEl || nameInput) {
      document.title = title;
    }
  }

  function createModalShell(titleText) {
    const overlay = document.createElement("div");
    overlay.className = "modal-backdrop";

    const modal = document.createElement("div");
    modal.className = "modal modal-center";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    const panel = document.createElement("div");
    panel.className = "dialog-card";

    const title = document.createElement("h3");
    title.className = "dialog-title";
    title.textContent = titleText;
    panel.appendChild(title);

    modal.appendChild(panel);
    document.body.appendChild(overlay);
    document.body.appendChild(modal);
    return { overlay, modal, panel };
  }

  function bindModalDismiss(overlay, modal, onDismiss) {
    let closed = false;
    const close = (result) => {
      if (closed) return;
      closed = true;
      window.removeEventListener("keydown", onKeyDown);
      overlay.remove();
      modal.remove();
      onDismiss(result);
    };
    const onKeyDown = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      close(false);
    };
    overlay.addEventListener("click", () => close(false));
    modal.addEventListener("click", (event) => {
      if (event.target === modal) close(false);
    });
    window.addEventListener("keydown", onKeyDown);
    return close;
  }

  function showConfirmModal({
    title = "遒ｺ隱・,
    lines = [],
    confirmLabel = "螳溯｡・,
    cancelLabel = "キャンセル",
  }) {
    return new Promise((resolve) => {
      const { overlay, modal, panel } = createModalShell(title);
      const body = document.createElement("div");
      body.className = "dialog-body";
      const messageList = document.createElement("ul");
      messageList.className = "dialog-message-list";
      lines.forEach((line) => {
        const li = document.createElement("li");
        li.className = "muted";
        li.textContent = String(line || "");
        messageList.appendChild(li);
      });
      body.appendChild(messageList);
      panel.appendChild(body);

      const actions = document.createElement("div");
      actions.className = "dialog-actions";

      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "secondary";
      cancelButton.textContent = cancelLabel;

      const confirmButton = document.createElement("button");
      confirmButton.type = "button";
      confirmButton.className = "primary";
      confirmButton.textContent = confirmLabel;

      const close = bindModalDismiss(overlay, modal, resolve);

      cancelButton.addEventListener("click", () => close(false));
      confirmButton.addEventListener("click", () => close(true));

      actions.appendChild(cancelButton);
      actions.appendChild(confirmButton);
      panel.appendChild(actions);
      confirmButton.focus();
    });
  }

  function showWorkflowSettingsModal({ name = "", subheading = "" }) {
    return new Promise((resolve) => {
      const { overlay, modal, panel } = createModalShell("ページ設定");
      const formEl = document.createElement("form");
      formEl.className = "dialog-form";

      const nameLabel = document.createElement("label");
      nameLabel.className = "dialog-field";
      nameLabel.textContent = "ワークフロー名";
      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.required = true;
      nameInput.value = String(name || "");
      nameLabel.appendChild(nameInput);
      formEl.appendChild(nameLabel);

      const subheadingLabel = document.createElement("label");
      subheadingLabel.className = "dialog-field";
      subheadingLabel.textContent = "陬懆ｶｳ隱ｬ譏趣ｼ井ｻｻ諢擾ｼ・;
      const subheadingInput = document.createElement("input");
      subheadingInput.type = "text";
      subheadingInput.value = String(subheading || "");
      subheadingLabel.appendChild(subheadingInput);
      formEl.appendChild(subheadingLabel);

      const actions = document.createElement("div");
      actions.className = "dialog-actions";

      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "secondary";
      cancelButton.textContent = "キャンセル";

      const saveButton = document.createElement("button");
      saveButton.type = "submit";
      saveButton.className = "primary";
      saveButton.textContent = "保存";

      const close = bindModalDismiss(overlay, modal, resolve);

      cancelButton.addEventListener("click", () => close(null));
      formEl.addEventListener("submit", (event) => {
        event.preventDefault();
        const nextName = String(nameInput.value || "").trim();
        const nextSubheading = String(subheadingInput.value || "").trim();
        if (!nextName) {
          nameInput.setCustomValidity("ワークフロー名を入力してください。");
          nameInput.reportValidity();
          return;
        }
        nameInput.setCustomValidity("");
        close({ name: nextName, subheading: nextSubheading });
      });

      actions.appendChild(cancelButton);
      actions.appendChild(saveButton);
      formEl.appendChild(actions);
      panel.appendChild(formEl);
      nameInput.focus();
      nameInput.select();
    });
  }

  function normalizeTemplateSourceUrls(rawValues) {
    const values = Array.isArray(rawValues) ? rawValues : [];
    const urls = [];
    const seen = new Set();
    values.forEach((value) => {
      const url = String(value || "").trim();
      if (!url) return;
      const key = url.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      urls.push(url);
    });
    return urls;
  }

  function isValidHttpUrl(value) {
    const text = String(value || "").trim();
    if (!text) return true;
    try {
      const parsed = new URL(text);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  }

  function getTemplateSourceUrlListEl() {
    return form ? form.querySelector("[data-source-url-list]") : null;
  }

  function getTemplateSourceUrlRows() {
    if (!form) return [];
    return Array.from(form.querySelectorAll("[data-source-url-row]"));
  }

  function getTemplateSourceUrlInputs() {
    if (!form) return [];
    return Array.from(form.querySelectorAll("[data-source-url-input]"));
  }

  function collectTemplateSourceUrls() {
    return normalizeTemplateSourceUrls(
      getTemplateSourceUrlInputs().map((input) => String(input?.value || "").trim()),
    );
  }

  function getPrimaryTemplateSourceUrl() {
    const urls = collectTemplateSourceUrls();
    return urls[0] || "";
  }

  function setTemplateSourceUrlInputNames() {
    getTemplateSourceUrlInputs().forEach((input, index) => {
      input.name = index === 0 ? "mfcloud_url" : `mfcloud_url_${index + 1}`;
      if (index === 0) {
        input.id = "template-source-url-primary";
      } else if (input.id === "template-source-url-primary") {
        input.removeAttribute("id");
      }
    });
  }

  function refreshTemplateSourceUrlRowMeta() {
    const rows = getTemplateSourceUrlRows();
    rows.forEach((row, index) => {
      let labelEl = row.querySelector("[data-source-url-index]");
      if (!labelEl) {
        labelEl = document.createElement("span");
        labelEl.className = "muted";
        labelEl.dataset.sourceUrlIndex = "1";
        row.insertBefore(labelEl, row.firstChild);
      }
      labelEl.textContent = `URL ${index + 1}`;
      const input = row.querySelector("[data-source-url-input]");
      if (input) {
        input.setAttribute("aria-label", `ソースURL ${index + 1}`);
      }
    });
  }

  function validateTemplateSourceUrls() {
    const inputs = getTemplateSourceUrlInputs();
    let firstInvalid = null;
    inputs.forEach((input) => {
      if (!input) return;
      const value = String(input.value || "").trim();
      const valid = isValidHttpUrl(value);
      input.classList.toggle("is-invalid", !valid);
      input.setCustomValidity(valid ? "" : "http:// もしくは https:// のURLを入力してください。");
      if (!valid && !firstInvalid) {
        firstInvalid = input;
      }
    });
    if (firstInvalid) {
      firstInvalid.focus();
      firstInvalid.reportValidity();
      return false;
    }
    return true;
  }

  function ensureTemplateSourceUrlRows() {
    const listEl = getTemplateSourceUrlListEl();
    if (!listEl) return;
    const rows = getTemplateSourceUrlRows();
    if (rows.length === 0) {
      addTemplateSourceUrlRow("", { focus: false });
      return;
    }
    const hideRemove = rows.length <= 1;
    rows.forEach((row) => {
      const removeButton = row.querySelector("[data-source-url-remove]");
      if (!removeButton) return;
      removeButton.hidden = hideRemove;
      removeButton.disabled = hideRemove;
    });
    refreshTemplateSourceUrlRowMeta();
    setTemplateSourceUrlInputNames();
  }

  function addTemplateSourceUrlRow(initialValue = "", options = {}) {
    const listEl = getTemplateSourceUrlListEl();
    if (!listEl) return;
    const shouldFocus = options.focus !== false;
    const row = document.createElement("div");
    row.className = "form-row template-source-url-row";
    row.dataset.sourceUrlRow = "1";

    const input = document.createElement("input");
    input.type = "url";
    input.value = String(initialValue || "").trim();
    input.placeholder = "https://example.com/path";
    input.dataset.sourceUrlInput = "1";

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "secondary";
    removeButton.dataset.sourceUrlRemove = "1";
    removeButton.setAttribute("aria-label", "このURL行を削除");
    removeButton.textContent = "-";
    removeButton.addEventListener("click", () => {
      row.remove();
      ensureTemplateSourceUrlRows();
    });

    row.appendChild(input);
    row.appendChild(removeButton);
    listEl.appendChild(row);
    ensureTemplateSourceUrlRows();
    if (shouldFocus) input.focus();
  }

  function getTemplateStepsListEl() {
    if (form) {
      const inForm = form.querySelector("[data-template-steps-list]");
      if (inForm) return inForm;
    }
    return document.querySelector("[data-template-steps-list]");
  }

  function getTemplateStepRows() {
    const listEl = getTemplateStepsListEl();
    if (!listEl) return [];
    return Array.from(listEl.querySelectorAll("[data-template-step-row]"));
  }

  function getTemplateStepActionOptionsHtml(selectedAction) {
    const normalizedAction = normalizeTemplateStepAction(selectedAction);
    return TEMPLATE_STEP_ACTIONS.map(
      (item) =>
        `<option value="${item.value}"${item.value === normalizedAction ? " selected" : ""}>${item.label}</option>`,
    ).join("");
  }

  function normalizeTemplateStepAction(value) {
    const action = String(value || TEMPLATE_STEP_DEFAULT_ACTION).trim();
    return TEMPLATE_STEP_ACTIONS.some((item) => item.value === action) ? action : TEMPLATE_STEP_DEFAULT_ACTION;
  }

  function generateTemplateStepId() {
    return `step-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function emitTemplateStepsChanged() {
    const listEl = getTemplateStepsListEl();
    if (!listEl) return;
    listEl.dispatchEvent(
      new CustomEvent("template-steps-changed", {
        bubbles: true,
      }),
    );
  }

  const TEMPLATE_STEP_TIMER_DEFAULT_MINUTES = 5;
  const TEMPLATE_STEP_TIMER_MIN_MINUTES = 0;
  const TEMPLATE_STEP_TIMER_REQUIRED_MINUTES = 1;
  const TEMPLATE_STEP_TIMER_MAX_MINUTES = 7 * 24 * 60;
  const TEMPLATE_STEP_EXECUTION_LOG_MAX_ITEMS = 20;
  const TEMPLATE_STEP_EXECUTION_LOG_MESSAGE_MAX_CHARS = 200;

  function normalizeTemplateStepTimerMinutes(value, fallback = TEMPLATE_STEP_TIMER_DEFAULT_MINUTES) {
    const parsed = Number.parseInt(String(value ?? "").trim(), 10);
    if (!Number.isInteger(parsed)) return fallback;
    if (parsed < TEMPLATE_STEP_TIMER_MIN_MINUTES) return TEMPLATE_STEP_TIMER_MIN_MINUTES;
    if (parsed > TEMPLATE_STEP_TIMER_MAX_MINUTES) return TEMPLATE_STEP_TIMER_MAX_MINUTES;
    return parsed;
  }

  function parseTemplateStepExecutionLogFromRow(row) {
    const raw = String(row?.dataset?.templateStepExecutionLog || "").trim();
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return normalizeTemplateStepExecutionLog(parsed);
    } catch {
      return [];
    }
  }

  function formatTemplateStepLatestExecutionLog(executionLog) {
    const rows = normalizeTemplateStepExecutionLog(executionLog);
    const latest = rows.length ? rows[rows.length - 1] : null;
    if (!latest) {
      return { text: "No runs yet", status: "none" };
    }
    const result = String(latest.result || "").trim().toLowerCase() === "failed" ? "failed" : "success";
    const label = result === "failed" ? "Failed" : "Success";
    const executedAt = String(latest.executed_at || "").trim() || "-";
    const message = String(latest.message || "").trim();
    const summary = message ? `${label} ${executedAt} (${message})` : `${label} ${executedAt}`;
    return {
      text: summary,
      status: result,
    };
  }

  function setTemplateStepExecutionLogOnRow(row, executionLog) {
    if (!(row instanceof HTMLElement)) return;
    const normalized = normalizeTemplateStepExecutionLog(executionLog);
    row.dataset.templateStepExecutionLog = JSON.stringify(normalized);
  }

  function getTemplateStepDragAfterRow(listEl, pointerY) {
    const rows = getTemplateStepRows().filter((row) => row !== activeTemplateStepDragRow);
    let closestOffset = Number.NEGATIVE_INFINITY;
    let closestRow = null;
    rows.forEach((row) => {
      const rect = row.getBoundingClientRect();
      const offset = pointerY - rect.top - rect.height / 2;
      if (offset < 0 && offset > closestOffset) {
        closestOffset = offset;
        closestRow = row;
      }
    });
    return closestRow;
  }

  function ensureTemplateStepDnDBindings(listEl) {
    if (!(listEl instanceof HTMLElement)) return;
    if (listEl.dataset.templateStepDndBound === "1") return;
    listEl.dataset.templateStepDndBound = "1";

    listEl.addEventListener("dragover", (event) => {
      if (!(activeTemplateStepDragRow instanceof HTMLElement)) return;
      event.preventDefault();
      const afterRow = getTemplateStepDragAfterRow(listEl, event.clientY);
      if (!afterRow) {
        listEl.appendChild(activeTemplateStepDragRow);
        return;
      }
      if (afterRow !== activeTemplateStepDragRow) {
        listEl.insertBefore(activeTemplateStepDragRow, afterRow);
      }
    });

    listEl.addEventListener("drop", (event) => {
      if (!(activeTemplateStepDragRow instanceof HTMLElement)) return;
      event.preventDefault();
      refreshTemplateStepRows();
    });
  }

  function parseTemplateStepRow(row, index = 0) {
    const rowId = String(row?.dataset?.templateStepId || "").trim();
    const action = normalizeTemplateStepAction(row?.querySelector("[data-template-step-action]")?.value);
    const title =
      String(row?.querySelector("[data-template-step-title]")?.value || "").trim() ||
      defaultTitleForStepAction(action, `Task ${index + 1}`);
    const order = normalizeTemplateStepOrder(row?.dataset?.templateStepOrder, index + 1);
    const autoRun = Boolean(row?.querySelector("[data-template-step-auto-run]")?.checked);
    const timerInput = row?.querySelector("[data-template-step-timer]");
    const timerRaw = String(timerInput?.value || "").trim();
    let timerMinutes = null;
    if (autoRun) {
      timerMinutes = normalizeTemplateStepTimerForAutoRun(timerRaw);
    } else if (timerRaw) {
      timerMinutes = normalizeTemplateStepTimerMinutes(timerRaw, null);
    }
    const executionLog = parseTemplateStepExecutionLogFromRow(row);
    return {
      id: rowId || generateTemplateStepId(),
      order,
      title,
      action,
      auto_run: autoRun,
      timer_minutes: timerMinutes,
      execution_log: executionLog,
    };
  }

  function refreshTemplateStepRows() {
    const listEl = getTemplateStepsListEl();
    if (!listEl) return;
    const rows = getTemplateStepRows();
    if (rows.length === 0) {
      return;
    }

    const parsedRows = rows.map((row, index) => parseTemplateStepRow(row, index));
    const actionCounts = new Map();
    parsedRows.forEach((step) => {
      const action = String(step.action || "").trim();
      if (!action) return;
      actionCounts.set(action, (actionCounts.get(action) || 0) + 1);
    });
    const optionalRowsCount = parsedRows.filter((row) => !isRequiredTemplateStepAction(row.action)).length;
    let hasDuplicates = false;

    rows.forEach((row, index) => {
      const parsed = parsedRows[index] || {
        action: TEMPLATE_STEP_DEFAULT_ACTION,
        title: "",
        auto_run: false,
        timer_minutes: null,
        execution_log: [],
      };
      const action = normalizeTemplateStepAction(parsed.action);
      const requiredAction = isRequiredTemplateStepAction(action) ? action : "";

      row.dataset.templateStepOrder = String(index + 1);
      setTemplateStepExecutionLogOnRow(row, parsed.execution_log);

      const handleEl = row.querySelector("[data-template-step-drag-handle]");
      if (handleEl) {
        handleEl.setAttribute("aria-label", `Move Task ${index + 1}`);
      }

      const indexEl = row.querySelector("[data-template-step-index]");
      if (indexEl) {
        indexEl.textContent = `Task ${index + 1}`;
      }

      const titleEl = row.querySelector("[data-template-step-title]");
      if (titleEl) {
        if (!String(titleEl.value || "").trim()) {
          titleEl.value = defaultTitleForStepAction(action, `Task ${index + 1}`);
        }
        titleEl.setAttribute("aria-label", `Task ${index + 1} title`);
      }

      const actionEl = row.querySelector("[data-template-step-action]");
      if (actionEl) {
        if (requiredAction) {
          row.dataset.requiredAction = requiredAction;
          actionEl.value = requiredAction;
          actionEl.disabled = true;
        } else {
          delete row.dataset.requiredAction;
          actionEl.disabled = false;
        }
        const duplicated = (actionCounts.get(action) || 0) > 1;
        hasDuplicates = hasDuplicates || duplicated;
        actionEl.classList.toggle("is-invalid", duplicated);
        actionEl.setCustomValidity(duplicated ? "Each action can only be used once." : "");
      }

      const autoRunEl = row.querySelector("[data-template-step-auto-run]");
      const autoRunEnabled = autoRunEl ? Boolean(autoRunEl.checked) : Boolean(parsed.auto_run);
      if (autoRunEl) {
        autoRunEl.checked = autoRunEnabled;
        autoRunEl.setAttribute("aria-label", `Task ${index + 1} auto run`);
      }

      const timerEl = row.querySelector("[data-template-step-timer]");
      if (timerEl) {
        timerEl.disabled = !autoRunEnabled;
        timerEl.required = autoRunEnabled;
        timerEl.min = autoRunEnabled ? String(TEMPLATE_STEP_TIMER_REQUIRED_MINUTES) : String(TEMPLATE_STEP_TIMER_MIN_MINUTES);
        timerEl.max = String(TEMPLATE_STEP_TIMER_MAX_MINUTES);
        timerEl.setAttribute("aria-label", `Task ${index + 1} timer minutes`);
        if (autoRunEnabled) {
          const nextTimer = normalizeTemplateStepTimerForAutoRun(
            String(timerEl.value || "").trim() || parsed.timer_minutes,
          );
          timerEl.value = String(nextTimer);
        } else if (String(timerEl.value || "").trim()) {
          timerEl.value = String(normalizeTemplateStepTimerMinutes(timerEl.value, 0));
        }
        timerEl.setCustomValidity("");
      }

      const logEl = row.querySelector("[data-template-step-log]");
      if (logEl) {
        const summary = formatTemplateStepLatestExecutionLog(parsed.execution_log);
        logEl.textContent = summary.text;
        logEl.classList.toggle("is-success", summary.status === "success");
        logEl.classList.toggle("is-failed", summary.status === "failed");
      }

      const removeButton = row.querySelector("[data-template-step-remove]");
      if (removeButton) {
        const locked = Boolean(requiredAction) || optionalRowsCount <= 0;
        removeButton.hidden = locked;
        removeButton.disabled = locked;
        removeButton.title = requiredAction ? "Required task cannot be removed." : "";
      }
    });

    listEl.dataset.stepHasDuplicates = hasDuplicates ? "1" : "0";
    emitTemplateStepsChanged();
  }

  function validateTemplateStepRows() {
    const listEl = getTemplateStepsListEl();
    if (!listEl) return true;
    if (listEl.dataset.stepHasDuplicates === "1") {
      showToast("Please remove duplicate actions.", "error");
      return false;
    }
    const rows = getTemplateStepRows();
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      const titleEl = row.querySelector("[data-template-step-title]");
      if (titleEl && !String(titleEl.value || "").trim()) {
        titleEl.setCustomValidity("Title is required.");
        titleEl.reportValidity();
        return false;
      }
      if (titleEl) titleEl.setCustomValidity("");

      const autoRunEnabled = Boolean(row.querySelector("[data-template-step-auto-run]")?.checked);
      const timerEl = row.querySelector("[data-template-step-timer]");
      if (!timerEl) continue;
      if (!autoRunEnabled) {
        timerEl.setCustomValidity("");
        continue;
      }
      const timerValue = Number.parseInt(String(timerEl.value || "").trim(), 10);
      const validTimer = Number.isInteger(timerValue)
        && timerValue >= TEMPLATE_STEP_TIMER_REQUIRED_MINUTES
        && timerValue <= TEMPLATE_STEP_TIMER_MAX_MINUTES;
      if (!validTimer) {
        timerEl.setCustomValidity(`Timer must be ${TEMPLATE_STEP_TIMER_REQUIRED_MINUTES}-${TEMPLATE_STEP_TIMER_MAX_MINUTES} minutes when auto run is enabled.`);
        timerEl.reportValidity();
        return false;
      }
      timerEl.setCustomValidity("");
    }
    return true;
  }

  function collectTemplateSteps() {
    const parsedRows = getTemplateStepRows()
      .map((row, index) => parseTemplateStepRow(row, index))
      .filter((row) => Boolean(row.title));
    return normalizeWorkflowStepRows(parsedRows, {
      ensureRequired: true,
      includeTimer: true,
    });
  }

  function addTemplateStepFromDefaultCard(options = {}) {
    const usedActions = new Set(
      getTemplateStepRows().map((row) => normalizeTemplateStepAction(row?.querySelector("[data-template-step-action]")?.value)),
    );
    let action = "amazon_download";
    if (usedActions.has(action)) {
      action = nextAvailableTemplateStepAction(usedActions);
    }
    const nextIndex = getTemplateStepRows().length + 1;
    addTemplateStepRow(
      {
        id: "",
        title: defaultTitleForStepAction(action, `Task ${nextIndex}`),
        action,
        auto_run: false,
        timer_minutes: null,
        execution_log: [],
      },
      options,
    );
  }

  function addTemplateStepRow(rawStep = {}, options = {}) {
    const listEl = getTemplateStepsListEl();
    if (!listEl) return;
    ensureTemplateStepDnDBindings(listEl);

    const shouldFocus = options.focus !== false;
    const title = String(rawStep?.title || "").trim();
    const action = normalizeTemplateStepAction(rawStep?.action);
    const requiredAction = isRequiredTemplateStepAction(action) ? action : "";
    const autoRun = normalizeTemplateStepAutoRun(rawStep?.auto_run ?? rawStep?.autoRun);
    const executionLog = normalizeTemplateStepExecutionLog(rawStep?.execution_log ?? rawStep?.executionLog);
    const rawTimer = rawStep?.timer_minutes ?? rawStep?.timer;
    const timerMinutes = autoRun
      ? normalizeTemplateStepTimerForAutoRun(rawTimer)
      : normalizeTemplateStepTimerMinutes(rawTimer, null);

    const row = document.createElement("div");
    row.className = "template-step-row";
    row.dataset.templateStepRow = "1";
    row.dataset.templateStepId = String(rawStep?.id || generateTemplateStepId()).trim();
    row.dataset.templateStepOrder = String(normalizeTemplateStepOrder(rawStep?.order, getTemplateStepRows().length + 1));
    row.dataset.lastAction = action;
    row.draggable = true;
    setTemplateStepExecutionLogOnRow(row, executionLog);
    if (requiredAction) {
      row.dataset.requiredAction = requiredAction;
    }

    const dragHandle = document.createElement("button");
    dragHandle.type = "button";
    dragHandle.className = "template-step-drag-handle";
    dragHandle.dataset.templateStepDragHandle = "1";
    dragHandle.setAttribute("aria-label", "Move task");
    dragHandle.textContent = "::";
    dragHandle.addEventListener("pointerdown", () => {
      row.dataset.dragReady = "1";
    });
    dragHandle.addEventListener("pointerup", () => {
      delete row.dataset.dragReady;
    });
    dragHandle.addEventListener("pointercancel", () => {
      delete row.dataset.dragReady;
    });

    const indexEl = document.createElement("span");
    indexEl.className = "muted";
    indexEl.dataset.templateStepIndex = "1";

    const titleEl = document.createElement("input");
    titleEl.type = "text";
    titleEl.className = "template-step-title";
    titleEl.value = title;
    titleEl.placeholder = "Task title";
    titleEl.dataset.templateStepTitle = "1";
    titleEl.required = true;

    const actionEl = document.createElement("select");
    actionEl.className = "template-step-action";
    actionEl.dataset.templateStepAction = "1";
    actionEl.innerHTML = getTemplateStepActionOptionsHtml(action);

    const autoRunLabel = document.createElement("label");
    autoRunLabel.className = "template-step-auto-run";
    const autoRunEl = document.createElement("input");
    autoRunEl.type = "checkbox";
    autoRunEl.dataset.templateStepAutoRun = "1";
    autoRunEl.checked = autoRun;
    const autoRunText = document.createElement("span");
    autoRunText.textContent = "Auto";
    autoRunLabel.appendChild(autoRunEl);
    autoRunLabel.appendChild(autoRunText);

    const timerEl = document.createElement("input");
    timerEl.type = "number";
    timerEl.className = "template-step-timer";
    timerEl.dataset.templateStepTimer = "1";
    timerEl.step = "1";
    timerEl.min = String(TEMPLATE_STEP_TIMER_MIN_MINUTES);
    timerEl.max = String(TEMPLATE_STEP_TIMER_MAX_MINUTES);
    timerEl.placeholder = "minutes";
    timerEl.value = timerMinutes === null ? "" : String(timerMinutes);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "secondary";
    removeButton.dataset.templateStepRemove = "1";
    removeButton.setAttribute("aria-label", "Remove task");
    removeButton.textContent = "-";
    removeButton.addEventListener("click", () => {
      if (row.dataset.requiredAction) {
        showToast("Required task cannot be removed.", "error");
        return;
      }
      row.remove();
      refreshTemplateStepRows();
    });

    const logEl = document.createElement("span");
    logEl.className = "muted template-step-log";
    logEl.dataset.templateStepLog = "1";

    row.addEventListener("dragstart", (event) => {
      const fromHandle = row.dataset.dragReady === "1" || Boolean(event.target?.closest?.("[data-template-step-drag-handle]"));
      if (!fromHandle) {
        event.preventDefault();
        return;
      }
      activeTemplateStepDragRow = row;
      row.classList.add("is-dragging");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.dataset.templateStepId || "");
      }
    });

    row.addEventListener("dragend", () => {
      row.classList.remove("is-dragging");
      delete row.dataset.dragReady;
      activeTemplateStepDragRow = null;
      refreshTemplateStepRows();
    });

    titleEl.addEventListener("input", refreshTemplateStepRows);
    autoRunEl.addEventListener("change", () => {
      if (autoRunEl.checked && !String(timerEl.value || "").trim()) {
        timerEl.value = String(TEMPLATE_STEP_TIMER_DEFAULT_MINUTES);
      }
      refreshTemplateStepRows();
    });
    timerEl.addEventListener("input", () => {
      timerEl.setCustomValidity("");
    });
    timerEl.addEventListener("change", () => {
      if (autoRunEl.checked) {
        timerEl.value = String(normalizeTemplateStepTimerForAutoRun(timerEl.value));
      } else if (String(timerEl.value || "").trim()) {
        timerEl.value = String(normalizeTemplateStepTimerMinutes(timerEl.value, 0));
      }
      refreshTemplateStepRows();
    });
    actionEl.addEventListener("change", () => {
      const lockedAction = String(row.dataset.requiredAction || "").trim();
      const previousAction = String(row.dataset.lastAction || "").trim() || action;
      const nextAction = normalizeTemplateStepAction(actionEl.value);
      if (lockedAction) {
        actionEl.value = lockedAction;
        refreshTemplateStepRows();
        return;
      }
      const duplicated = getTemplateStepRows().some((otherRow) => {
        if (!otherRow || otherRow === row) return false;
        const otherAction = normalizeTemplateStepAction(
          otherRow.querySelector("[data-template-step-action]")?.value,
        );
        return otherAction === nextAction;
      });
      if (duplicated) {
        actionEl.value = previousAction;
        showToast("Each action can only be used once.", "error");
        refreshTemplateStepRows();
        return;
      }
      row.dataset.lastAction = nextAction;
      refreshTemplateStepRows();
    });

    row.appendChild(dragHandle);
    row.appendChild(indexEl);
    row.appendChild(titleEl);
    row.appendChild(actionEl);
    row.appendChild(autoRunLabel);
    row.appendChild(timerEl);
    row.appendChild(removeButton);
    row.appendChild(logEl);
    listEl.appendChild(row);

    refreshTemplateStepRows();
    if (shouldFocus) {
      titleEl.focus();
      titleEl.select();
    }
  }

  function hydrateTemplateSteps() {
    const listEl = getTemplateStepsListEl();
    if (!listEl) return;

    const workflowPageSteps = Array.isArray(workflowPage?.steps) ? workflowPage.steps : [];
    const templateSteps = Array.isArray(workflowTemplate?.steps) ? workflowTemplate.steps : [];
    const initialRows = normalizeWorkflowStepRows(
      workflowPageSteps.length > 0 ? workflowPageSteps : templateSteps,
      { ensureRequired: true, includeTimer: true },
    );

    listEl.innerHTML = "";
    const rowsToRender =
      initialRows.length > 0
        ? initialRows
        : normalizeWorkflowStepRows([{ action: TEMPLATE_STEP_DEFAULT_ACTION }], {
            ensureRequired: true,
            includeTimer: true,
          });
    rowsToRender.forEach((row, index) => {
      const title = String(row?.title || "").trim() || defaultTitleForStepAction(row?.action, `Task ${index + 1}`);
      const action = normalizeTemplateStepAction(row?.action);
      addTemplateStepRow(
        {
          id: row?.id,
          order: row?.order,
          title,
          action,
          auto_run: row?.auto_run,
          timer_minutes: row?.timer_minutes,
          execution_log: row?.execution_log,
        },
        { focus: false },
      );
    });

    refreshTemplateStepRows();
  }

  function hydrateTemplateSourceUrls() {
    const listEl = getTemplateSourceUrlListEl();
    if (!listEl) return;
    const templateUrls = normalizeTemplateSourceUrls(workflowTemplate?.source_urls);
    const fallbackUrl = String(workflowTemplate?.mfcloud_url || "").trim();
    const initialInput = form?.querySelector("[name=mfcloud_url]");
    const initialValue = String(initialInput?.value || "").trim();

    let sourceUrls = templateUrls;
    if (sourceUrls.length === 0 && fallbackUrl) {
      sourceUrls = [fallbackUrl];
    }
    if (sourceUrls.length === 0 && initialValue) {
      sourceUrls = [initialValue];
    }
    if (sourceUrls.length === 0) {
      sourceUrls = [""];
    }

    listEl.innerHTML = "";
    sourceUrls.forEach((url) => addTemplateSourceUrlRow(url, { focus: false }));
    ensureTemplateSourceUrlRows();
  }

  function applyTemplateModeUI() {
    const mode = getTemplateMode();
    const config = getTemplateModeConfig(mode);
    const templateId = getTemplateIdFromForm() || String(workflowTemplate?.id || "").trim();
    const hasTemplateTarget = Boolean(templateId);
    const chipEl = document.getElementById("workflow-template-mode-chip");
    const descEl = document.getElementById("workflow-template-mode-description");
    const summaryEl = document.getElementById("workflow-template-mode-summary");
    const saveButton = document.getElementById("workflow-template-save");
    if (chipEl) chipEl.textContent = config.chip;
    if (descEl) {
      descEl.textContent = hasTemplateTarget
        ? config.description
        : "新規テンプレート作成は無効です。既存テンプレートを選択して更新してください。";
    }
    if (summaryEl) summaryEl.textContent = config.summary;
    if (saveButton) {
      saveButton.textContent = hasTemplateTarget ? config.saveLabel : "テンプレート更新（対象なし）";
      saveButton.disabled = !hasTemplateTarget;
      saveButton.title = hasTemplateTarget ? "" : "更新対象のテンプレートがありません。";
    }

    const sourceMeta = document.getElementById("workflow-template-source-meta");
    const sourceNameEl = document.getElementById("workflow-template-source-name");
    const sourceUpdatedEl = document.getElementById("workflow-template-source-updated");
    const sourceEditLink = document.getElementById("workflow-template-edit-source");
    if (!sourceMeta || !sourceEditLink || !sourceNameEl || !sourceUpdatedEl) {
      syncTemplatePageHeader();
      return;
    }

    const sourceId = String(workflowTemplate?.id || "").trim();
    const sourceUpdated = String(workflowTemplate?.updated_at || "").trim();
    const sourceName = String(workflowTemplate?.name || "").trim();
    if (sourceId && sourceName) {
      sourceNameEl.textContent = sourceName;
      sourceUpdatedEl.textContent = sourceUpdated || "-";
      sourceEditLink.href = `/expense-workflow-copy?template=${encodeURIComponent(sourceId)}`;
      sourceEditLink.hidden = false;
      sourceMeta.classList.remove("hidden");
      syncTemplatePageHeader();
      return;
    }

    sourceMeta.classList.add("hidden");
    sourceEditLink.hidden = true;
    syncTemplatePageHeader();
  }

  function getTemplateIdFromForm() {
    if (!form) return "";
    return String(form.querySelector("[name=template_id]")?.value || "").trim();
  }

  function getTemplateSourceIdFromForm() {
    if (!form) return "";
    return String(form.querySelector("[name=template_source_id]")?.value || "").trim();
  }

  function getTemplateUpdatedAtFromForm() {
    if (!form) return "";
    return String(form.querySelector("[name=template_updated_at]")?.value || "").trim();
  }

  function shouldSyncYmQueryParams() {
    const activeTab = String(pageEl?.dataset?.activeTab || "").trim();
    const isTemplatePage = activeTab === "wizard-copy";
    const isWorkflowPage = Boolean(String(workflowPage?.id || "").trim());
    return !isTemplatePage && !isWorkflowPage;
  }

  function readYmFromQueryString() {
    if (!shouldSyncYmQueryParams()) return "";
    if (typeof window === "undefined") return "";
    try {
      const params = new URLSearchParams(window.location.search || "");
      return normalizeYm(params.get("year"), params.get("month"));
    } catch {
      return "";
    }
  }

  function readYmFromLocalStorage() {
    if (typeof window === "undefined" || !window.localStorage) return "";
    try {
      const raw = window.localStorage.getItem(YM_STORAGE_KEY);
      const parsed = parseYm(raw);
      return parsed ? parsed.ym : "";
    } catch {
      return "";
    }
  }

  function persistYmSelection(ymValue) {
    const parsed = parseYm(ymValue);
    if (!parsed || typeof window === "undefined") return;
    try {
      if (window.localStorage) {
        window.localStorage.setItem(YM_STORAGE_KEY, parsed.ym);
      }
    } catch {
      // Best-effort only.
    }
    try {
      const url = new URL(window.location.href);
      if (!shouldSyncYmQueryParams()) {
        url.searchParams.delete("year");
        url.searchParams.delete("month");
        const nextUrl = `${url.pathname}${url.search}${url.hash}`;
        window.history.replaceState(window.history.state, "", nextUrl);
        return;
      }
      url.searchParams.set("year", String(parsed.year));
      url.searchParams.set("month", String(parsed.month));
      const nextUrl = `${url.pathname}${url.search}${url.hash}`;
      window.history.replaceState(window.history.state, "", nextUrl);
    } catch {
      // Best-effort only.
    }
  }

  function restoreYmSelection() {
    if (!form) return;
    if (!shouldSyncYmQueryParams()) {
      const normalized = resolveFormYearMonth();
      persistYmSelection(normalizeYm(normalized.year, normalized.month));
      return;
    }
    const queryYm = readYmFromQueryString();
    const savedYm = queryYm || readYmFromLocalStorage() || getYmFromForm();
    if (savedYm) setYmToForm(savedYm);
    const normalized = resolveFormYearMonth();
    persistYmSelection(normalizeYm(normalized.year, normalized.month));
  }

  function normalizeChecklistState(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const normalized = {};
    monthCloseChecklistKeys.forEach((key) => {
      normalized[key] = source[key] === true;
    });
    return normalized;
  }

  // Month Close Checklist state
  let checklistState = normalizeChecklistState({});

  function isChecklistComplete() {
    return monthCloseChecklistKeys.every((key) => checklistState[key] === true);
  }

  function formatDateTimeInJst(dateValue) {
    const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("sv-SE", {
      timeZone: "Asia/Tokyo",
      hour12: false,
    });
  }

  function nowIsoLikeInJst() {
    const text = formatDateTimeInJst(new Date());
    return text ? text.replace(" ", "T") : "";
  }

  async function apiGetJson(url) {
    const sep = url.includes("?") ? "&" : "?";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await fetch(`${url}${sep}_=${Date.now()}`, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
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
    refreshSteps({ force: true });
    [800, 2000, 4500, 9000].forEach((delayMs) => {
      setTimeout(() => {
        refreshSteps({ force: true });
      }, delayMs);
    });
  }

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
      ensureRequired: true,
      includeTimer: true,
    });
    return rows.map((row, index) => {
      const action = String(row.action || "").trim();
      const actionLabel = TEMPLATE_STEP_ACTION_LABELS[action] || action || "(譛ｪ險ｭ螳・";
      const title = String(row.title || "").trim() || defaultTitleForStepAction(action, `Task ${index + 1}`);
      const autoRun = normalizeTemplateStepAutoRun(row.auto_run);
      const timer = autoRun ? normalizeTemplateStepTimerForAutoRun(row.timer_minutes) : null;
      const mode = autoRun ? `auto ${timer}m` : "manual";
      return `${index + 1}. ${title} / ${actionLabel} / ${mode}`;
    });
  }

  function renderWorkflowCreatePreview(payload = null) {
    const listEl = document.getElementById("workflow-create-preview-list");
    if (!listEl) return;
    const currentPayload = payload || buildWorkflowPagePayload() || {};
    const name = String(currentPayload.name || "").trim() || "(譛ｪ蜈･蜉・";
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
      createButton.textContent = "菴懈・荳ｭ...";
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
      ensureRequired: true,
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
      { ensureRequired: true, includeTimer: true },
    );
    const rowByAction = new Map(rows.map((row) => [String(row.action || "").trim(), row]));
    const visibleBlockSet = new Set();
    rows.forEach((row) => {
      const key = actionToWorkflowBlockKey(row.action);
      if (key) visibleBlockSet.add(key);
    });
    const orderedBlockKeys = WORKFLOW_STEP_BLOCK_ORDER.filter((key) => visibleBlockSet.has(key));

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
      note.textContent = "必須手順（preflight / mf_reconcile）は削除・変更できません。";
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
        ensureRequired: true,
        includeTimer: true,
      }).map((row) => ({ ...row }));

      const normalizeState = () => {
        const normalized = normalizeWorkflowStepRows(state, {
          ensureRequired: true,
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
            const duplicated = state.some((step, stepIndex) => stepIndex !== index && step.action === nextAction);
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
          title: defaultTitleForStepAction(action),
          action,
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
        ensureRequired: true,
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
      ensureRequired: true,
      includeTimer: true,
    });
    const nextSteps = await showWorkflowPageStepEditorModal(currentSteps);
    if (!nextSteps) return;
    const normalizedNext = normalizeWorkflowStepRows(nextSteps, {
      ensureRequired: true,
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
      ensureRequired: true,
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
    if (!String(payload.template_id || "").trim()) {
      const message = "新規テンプレート作成は無効です。既存テンプレートを選択してください。";
      showError(message);
      showToast(message, "error");
      return;
    }
    if (!String(payload.base_updated_at || "").trim()) {
      const message = "テンプレート更新情報が不足しています。テンプレートを再読み込みしてください。";
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

  function getYmFromForm() {
    if (!form) return "";
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    return normalizeYm(yearEl?.value, monthEl?.value);
  }

  function setStepStatus(id, state) {
    const el = document.querySelector(`[data-step-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (id === "mf_reconcile" && state !== "running") {
      el.textContent = "譛ｪ螳溯｡・;
      el.classList.add("pending");
      return;
    }
    if (state === "done") {
      el.textContent = "螳御ｺ・;
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "螳溯｡御ｸｭ";
      el.classList.add("running");
      return;
    }
    el.textContent = "譛ｪ螳溯｡・;
    el.classList.add("pending");
  }

  function setTaskStatus(id, state) {
    const el = document.querySelector(`[data-task-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (state === "done") {
      el.textContent = "螳御ｺ・;
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "螳溯｡御ｸｭ";
      el.classList.add("running");
      return;
    }
    el.textContent = "譛ｪ螳溯｡・;
    el.classList.add("pending");
  }

  function renderNextStep(message, href, reason = "", linkLabel = "") {
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
    if (reason) {
      const reasonEl = document.createElement("span");
      reasonEl.className = "muted next-step-reason";
      reasonEl.textContent = reason;
      wizardNext.appendChild(reasonEl);
    }
    if (!href) return;
    const link = document.createElement("a");
    link.href = href;
    link.className = "secondary";
    link.textContent = String(linkLabel || "(msg)").trim() || "(msg)";
    if (String(href || "").trim().startsWith("#")) {
      link.href = href;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        navigateToStep(href);
      });
    }
    wizardNext.appendChild(link);
  }

  const FALLBACK_WIZARD_HREF = "#wizard";
  const FALLBACK_GUIDANCE_LIMIT = 8;

  function recordWizardFallback({ type, runningMode = "", nextStep = "", nextStepReason = "", href = "" }) {
    const entry = {
      ts: Date.now(),
      type: String(type || "").trim() || "unknown",
      runningMode: String(runningMode || "").trim(),
      nextStep: String(nextStep || "").trim(),
      nextStepReason: String(nextStepReason || "").trim(),
      href: String(href || FALLBACK_WIZARD_HREF).trim() || FALLBACK_WIZARD_HREF,
    };
    const log = Array.isArray(window.__wizardFallbackLog) ? window.__wizardFallbackLog : [];
    const last = log.length ? log[log.length - 1] : null;
    const shouldAppend =
      !last ||
      last.type !== entry.type ||
      last.runningMode !== entry.runningMode ||
      last.nextStep !== entry.nextStep ||
      last.nextStepReason !== entry.nextStepReason ||
      last.href !== entry.href;
    if (shouldAppend) {
      log.push(entry);
      if (log.length > FALLBACK_GUIDANCE_LIMIT) {
        log.shift();
      }
      window.__wizardFallbackLog = log;
    }
    const wizard = document.getElementById("wizard");
    if (!wizard) return;
    wizard.dataset.nextStepFallbackType = entry.type;
    wizard.dataset.nextStepFallbackStep = entry.nextStep;
    wizard.dataset.nextStepFallbackMode = entry.runningMode;
    wizard.dataset.nextStepFallbackReason = entry.nextStepReason;
    wizard.dataset.nextStepFallbackHref = entry.href;
    wizard.dataset.nextStepFallbackAt = String(entry.ts);
    wizard.dataset.nextStepFallbackCount = String(log.length);
  }

  function navigateToStep(href) {
    if (!href || typeof href !== "string") return;
    const id = href.trim();
    if (!id.startsWith("#")) return;
    const target = document.querySelector(id);
    if (!target) {
      showToast("(msg)", "warning");
      return;
    }

    if (stepFocusTimer) {
      clearTimeout(stepFocusTimer);
      stepFocusTimer = null;
    }

    target.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    const hadTabIndex = target.hasAttribute("tabindex");
    target.setAttribute("tabindex", "-1");
    const focusTarget =
      target.matches("button, a, input, select, textarea, [tabindex]")
      ? target
      : target.querySelector("button, a, input, select, textarea, [tabindex]");
    const focusable = focusTarget || target;
    if (typeof focusable.focus === "function") {
      try {
        focusable.focus({ preventScroll: true });
      } catch {
        focusable.focus();
      }
    }
    target.classList.add("step-focus");
    stepFocusTimer = setTimeout(() => {
      target.classList.remove("step-focus");
      if (!hadTabIndex) {
        target.removeAttribute("tabindex");
      }
      stepFocusTimer = null;
    }, 1400);
  }

  function inferNextStepFromFlags(data) {
    if (!data || typeof data !== "object") return "done";
    if (!data.preflight?.done) return "preflight";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const amazonPending = Boolean(data.amazon?.downloaded && !amazonDone);
    const rakutenPending = Boolean(data.rakuten?.downloaded && !rakutenDone);
    const providerPendingCount = Number.parseInt(String(data.providers?.pending_total ?? 0), 10);
    const providerPending = Number.isFinite(providerPendingCount) ? providerPendingCount > 0 : false;
    if (amazonPending) return "amazon_decide_print";
    if (rakutenPending) return "rakuten_decide_print";
    if (!data.amazon?.downloaded && !data.rakuten?.downloaded) return "amazon_or_rakuten_download";
    if (!data.amazon?.downloaded) return "amazon_download";
    if (!data.rakuten?.downloaded) return "rakuten_download";
    if (providerPending) return "provider_ingest";
    const mfDone = Boolean(data.mf?.step_done ?? data.mf?.reconciled);
    if (!mfDone && (Boolean(data.mf_bulk_upload?.done || data.mf_csv_import?.done))) return "mf_bulk_upload_task";
    const canReconcile =
      "can_reconcile" in data ? Boolean(data.can_reconcile) : (Boolean(data.amazon?.downloaded || data.rakuten?.downloaded) && !(amazonPending || rakutenPending));
    if (!mfDone && canReconcile) return "mf_reconcile";
    if (!mfDone) return "mf_reconcile";
    return "done";
  }

  const KNOWN_NEXT_STEP_VALUES = new Set([
      "preflight_mf",
      "preflight",
      "amazon_or_rakuten_download",
      "amazon_download",
      "amazon_decide_print",
      "rakuten_download",
      "rakuten_decide_print",
      "amazon_print",
      "rakuten_print",
      "provider_ingest",
      "import_provider_receipts",
      "mf_bulk_upload_task",
      "mf_bulk_upload",
      "mf_csv_import",
      "mf_reconcile",
      "done",
  ]);

  function normalizeNextStepValue(rawValue) {
    return String(rawValue || "").trim().toLowerCase();
  }

  function isKnownNextStep(rawValue) {
    return KNOWN_NEXT_STEP_VALUES.has(normalizeNextStepValue(rawValue));
  }

  function resolveNextStep(data) {
    const apiNextStep = normalizeNextStepValue(data?.next_step);
    if (isKnownNextStep(apiNextStep)) {
      return apiNextStep;
    }
    const inferred = inferNextStepFromFlags(data);
    if (apiNextStep) {
      recordWizardFallback({
        type: "next_step_unknown",
        runningMode: String(data?.running_mode || ""),
        nextStep: apiNextStep,
        nextStepReason: String(data?.next_step_reason || "").trim(),
        href: FALLBACK_WIZARD_HREF,
      });
    }
    return inferred;
  }

  function formatArchiveTimeForDisplay(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const normalized = text.includes("T") ? text : text.replace(" ", "T");
    if (/(Z|[+-]\d{2}:?\d{2})$/.test(normalized)) {
      const jstText = formatDateTimeInJst(normalized);
      if (jstText) return `${jstText} JST`;
    }
    const basicMatch = normalized.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
    if (basicMatch) return `${basicMatch[1]} ${basicMatch[2]} JST`;
    return text;
  }

  function archivePageHref(ym) {
    const value = String(ym || "").trim();
    if (!/^\d{4}-\d{2}$/.test(value)) return "";
    const wizard = document.getElementById("wizard");
    const template = String(wizard?.dataset?.archiveHrefTemplate || "").trim();
    if (template && template.includes("__YM__")) {
      return template.replace("__YM__", encodeURIComponent(value));
    }
    return `/runs/${value}/archived-receipts`;
  }

  function applyArchivePageLink(ym) {
    document.querySelectorAll("[data-archive-page-link]").forEach((link) => {
      if (!(link instanceof HTMLAnchorElement)) return;
      const fallbackHref = String(link.dataset.fallbackHref || link.getAttribute("href") || "").trim();
      const href = archivePageHref(ym) || fallbackHref || "#";
      link.href = href;
      if (href === "#") {
        link.classList.add("disabled");
        link.setAttribute("aria-disabled", "true");
        link.setAttribute("tabindex", "-1");
      } else {
        link.classList.remove("disabled");
        link.removeAttribute("aria-disabled");
        link.removeAttribute("tabindex");
      }
    });
  }

  function computeNextStep(data, ym) {
    const nextStep = resolveNextStep(data);
    const apiNextStep = normalizeNextStepValue(data?.next_step);
    const apiNextStepWasUnknown = apiNextStep && !isKnownNextStep(apiNextStep);
    const nextStepKey = String(nextStep || "").trim();
    const runningMode = String(data?.running_mode || "").trim();
    const nextStepReasonCode = String(data?.next_step_reason || "").trim();
    const nextStepGuidance = {
      preflight: {
        message: "準備フローを確認してください。",
        reason: "対象ワークフローの実行条件を確認してから次の工程へ進めてください。",
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      amazon_or_rakuten_download: {
        message: "まずは Amazon か楽天のいずれかの領収書取得を先に実行してください。",
        reason: "少なくとも1社分の領収書取得が必要です。未取得があると次の処理に進めません。",
        linkLabel: "Amazon／楽天 取得へ",
      },
      amazon_download: {
        message: "Amazon の領収書を取得してください。",
        reason: "Amazon 側の対象月データを取得して、次の除外判断・印刷へ進みます。",
        linkLabel: "Amazon 取得へ",
      },
      amazon_decide_print: {
        message: "Amazon の除外設定・印刷対象を確認してください。",
        reason: "除外対象を確定して印刷完了まで進めると状態が保存されます。",
        linkLabel: "Amazon 除外・印刷へ",
      },
      amazon_print: {
        message: "Amazonの印刷完了待ちステータスを確認してください。",
        reason: "Amazonの印刷処理が完了し、必要に応じて確認・反映を行ってください。",
        linkLabel: "Amazonの印刷ステータスへ",
      },
      rakuten_download: {
        message: "楽天の領収書を取得してください。",
        reason: "楽天側の対象月データを取得して、次の除外判断・印刷へ進みます。",
        linkLabel: "楽天 取得へ",
      },
      rakuten_print: {
        message: "楽天の印刷完了待ちステータスを確認してください。",
        reason: "楽天の印刷処理が完了し、必要に応じて確認・反映を行ってください。",
        linkLabel: "楽天の印刷ステータスへ",
      },
      rakuten_decide_print: {
        message: "楽天の除外設定・印刷対象を確認してください。",
        reason: "除外対象を確定して印刷完了まで進めると状態が保存されます。",
        linkLabel: "楽天 除外・印刷へ",
      },
      provider_ingest: {
        message: "外部CSVの取り込みを実行してください。",
        reason: "Amazon/楽天で取得しきれない分を、共通フォルダ経由で取り込むフェーズです。",
        linkLabel: "共通フォルダ取込へ",
      },
      mf_reconcile: {
        message: "MF連携の突合せ実行へ進めてください。",
        reason: "取り込み済みデータをMFの下書き作成へ反映します。",
        linkLabel: "MF 突合作業へ",
      },
      preflight_mf: {
        message: "MF再取得のみのステップを完了してください。",
        reason: "MF再取得後、ダッシュボードの最新状態を確認して次の作業に進んでください。",
        linkLabel: "MF蜀榊叙蠕励ｒ遒ｺ隱・,
      },
      mf_bulk_upload_task: {
        message: "Step 4: MF一括アップロード手順があります。",
        reason: "MF向けの手入力ファイルが用意できている場合、取り込みを実行してください。",
        linkLabel: "MF一括アップロードを開く",
      },
      import_provider_receipts: {
        message: "Provider取り込みステップを実行してください。",
        reason: "外部ベンダーの未処理CSVをMF突合前に取り込んで反映してください。",
        linkLabel: "Provider取り込みへ進む",
      },
      mf_bulk_upload: {
        message: "MF一括アップロードを実行してください。",
        reason: "MFのインポート画面を開いて、対象月の下書き対象を確認してください。",
        linkLabel: "MF一括アップロードを開く",
      },
      mf_csv_import: {
        message: "MF CSVインポートを実行してください。",
        reason: "CSVをMF形式へ揃えたうえで取り込みを実行してください。",
        linkLabel: "MF CSVインポートを開く",
      },
      done: {
        message: "すべて完了しました。月次アーカイブを実行できます。",
        reason: "最後に月次クローズやアーカイブを実行して、次月運用に備えます。",
        linkLabel: "月次クローズへ",
      },
      fallback: {
        message: "処理の取得に時間がかかっています。更新を待ってください。",
        reason: "バックエンドから最新状態を反映するまで数秒待って再取得してください。",
      },
    };

    const runningModeGuidance = {
      preflight: {
        message: "準備処理を実行中です。",
        reason: "処理が完了するまで待機してください。完了後に次の操作が自動で更新されます。",
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      preflight_mf: {
        message: "MF再取得を実行中です。",
        reason: "MF再取得処理を完了するまで、進行完了後の状態更新を待ってください。",
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      amazon_download: {
        message: "Amazon 領収書取得を実行中です。",
        reason: "取得が完了すると次の工程へ進める状態になります。完了までお待ちください。",
        linkLabel: "Amazon 取得進行状況へ",
      },
      amazon_print: {
        message: "Amazon 印刷処理を実行中です。",
        reason: "除外・印刷の進行中です。完了後に状態が反映され、次の案内へ進みます。",
        linkLabel: "Amazon 蜊ｰ蛻ｷ迥ｶ豕√∈",
      },
      rakuten_download: {
        message: "楽天領収書取得を実行中です。",
        reason: "取得が完了すると次の工程へ進める状態になります。完了までお待ちください。",
        linkLabel: "楽天 取得進行状況へ",
      },
      rakuten_print: {
        message: "楽天 印刷処理を実行中です。",
        reason: "除外・印刷の進行中です。完了後に状態が反映され、次の案内へ進みます。",
        linkLabel: "讌ｽ螟ｩ 蜊ｰ蛻ｷ迥ｶ豕√∈",
      },
      provider_ingest: {
        message: "共通フォルダ取り込みを実行中です。",
        reason: "取り込み処理完了後に突合せ可能かどうかを再評価します。",
        linkLabel: "共通フォルダ取込へ",
      },
      mf_reconcile: {
        message: "MF突合せを実行中です。",
        reason: "突合せ完了まで暫くお待ちください。完了後に下書きの作成状況が更新されます。",
        linkLabel: "MF遯∝粋迥ｶ豕√∈",
      },
      import_provider_receipts: {
        message: "Provider receipt import is running.",
        reason: "After import, verify files are reflected in MF draft workflow.",
        linkLabel: "Open provider import step",
      },
      mf_bulk_upload: {
        message: "MF bulk upload is running.",
        reason: "Check MF login state and selected bulk import target.",
        linkLabel: "Open MF bulk upload step",
      },
      mf_csv_import: {
        message: "MF CSV import is running.",
        reason: "If CSV import is pending, confirm file encoding and dedupe rules.",
        linkLabel: "Open MF CSV import step",
      },
    };

    const nextStepAnchors = {
      preflight: "#step-preflight",
      preflight_mf: "#step-preflight",
      amazon_or_rakuten_download: "#step-amazon-download",
      amazon_download: "#step-amazon-download",
      amazon_decide_print: "#step-amazon-decide-print",
      rakuten_download: "#step-rakuten-download",
      rakuten_decide_print: "#step-rakuten-decide-print",
      rakuten_print: "#step-rakuten-decide-print",
      amazon_print: "#step-amazon-decide-print",
      provider_ingest: "#step-provider-ingest",
      import_provider_receipts: "#step-provider-ingest",
      mf_bulk_upload_task: "#step-mf-bulk-upload-task",
      mf_bulk_upload: "#step-mf-bulk-upload-task",
      mf_csv_import: "#step-mf-bulk-upload-task",
      mf_reconcile: "#step-mf-reconcile",
      done: "#step-month-close",
    };

    const fallbackHref = FALLBACK_WIZARD_HREF;
    const nextTargetHref = nextStepAnchors[nextStepKey] || fallbackHref;
    const runningTargetHref = nextStepAnchors[runningMode] || nextTargetHref || FALLBACK_WIZARD_HREF;
    if (runningMode) {
      const runningGuidance = runningModeGuidance[runningMode];
      if (runningTargetHref === fallbackHref) {
        recordWizardFallback({
          type: "running_mode_anchor",
          runningMode,
          nextStep: nextStepKey,
          nextStepReason: nextStepReasonCode,
          href: runningTargetHref,
        });
      }
      return {
        message: runningGuidance?.message || `${runningMode} を実行中です。`,
        reason:
          runningGuidance?.reason ||
          "別の処理が進行中です。完了するまで待機してください。",
        href: runningTargetHref,
        linkLabel: runningGuidance?.linkLabel || (runningTargetHref === FALLBACK_WIZARD_HREF ? "手順を確認" : "進捗を確認"),
      };
    }

    const reasonHint = {
      preflight_required: {
        reason: "準備フローが未完了です。まず前提設定の完了が必要です。",
      },
      source_download_required: {
        message: "Amazon か楽天のどちらかの領収書取得を先に実行してください。",
        reason: "少なくとも1社分の対象月データを取得してください。",
      },
      amazon_download_required: {
        message: "Amazon の領収書を取得してください。",
        reason: "対象月分を取得すると次の除外・印刷工程へ進めます。",
      },
      rakuten_download_required: {
        message: "楽天の領収書を取得してください。",
        reason: "対象月分を取得すると次の除外・印刷工程へ進めます。",
      },
      amazon_print_pending: {
        message: "Amazon の除外設定・印刷対象を確認してください。",
        reason: "除外対象の確定と印刷完了を行うと次工程へ進みます。",
      },
      rakuten_print_pending: {
        message: "楽天の除外設定・印刷対象を確認してください。",
        reason: "除外対象の確定と印刷完了を行うと次工程へ進みます。",
      },
      provider_ingest_pending: {
        message: "外部CSVの取り込みを実行してください。",
        reason: "Amazon/楽天で取得しきれない分を共通フォルダから取り込んでください。",
      },
      mf_reconcile_ready: {
        message: "MF連携の突合せ実行へ進めてください。",
        reason: "取り込み済みデータをMFの下書き作成へ反映する準備が整いました。",
      },
      workflow_complete: {
        message: "すべて完了しました。月次アーカイブを実行できます。",
        reason: "最終確認として月次クローズやアーカイブで次月準備に進んでください。",
      },
    };

    const href = nextTargetHref;
    if (href === fallbackHref) {
      recordWizardFallback({
        type: "next_step_anchor",
        runningMode,
        nextStep: nextStepKey,
        nextStepReason: nextStepReasonCode,
        href,
      });
    }
    const baseGuidance = nextStepGuidance[nextStepKey] || nextStepGuidance.fallback;
    const reasonGuidance = reasonHint[nextStepReasonCode];
    const reasonKnown = Object.prototype.hasOwnProperty.call(reasonHint, nextStepReasonCode);
    const apiFallbackReason = apiNextStepWasUnknown
      ? ` [fallback: next_step "${apiNextStep}" was unknown and inferred from current flags]`
      : "";
    if (nextStepReasonCode && !reasonKnown) {
      recordWizardFallback({
        type: "next_step_reason_unknown",
        runningMode,
        nextStep: nextStepKey,
        nextStepReason: nextStepReasonCode,
        href,
      });
    }
    const guidance = reasonGuidance
      ? {
          ...baseGuidance,
          message: reasonGuidance.message || baseGuidance.message,
          reason: `${reasonGuidance.reason || baseGuidance.reason}${apiFallbackReason}`,
        }
      : {
          ...baseGuidance,
          reason: `${baseGuidance.reason || ""}${apiFallbackReason}`,
        };
    return {
      message: guidance.message,
      reason: guidance.reason,
      href,
      linkLabel: guidance.linkLabel || (href === FALLBACK_WIZARD_HREF ? "手順を確認" : ""),
    };
  }
  function inferAllowedModes(data) {
    const apiModes = Array.isArray(data?.allowed_run_modes) ? data.allowed_run_modes : [];
    if (apiModes.length > 0) {
      const normalized = [];
      const seen = new Set();
      for (const mode of apiModes) {
        const normalizedMode = String(mode || "").trim();
        if (!normalizedMode || seen.has(normalizedMode)) continue;
        seen.add(normalizedMode);
        normalized.push(normalizedMode);
      }
      return normalized;
    }
    const allowed = ["preflight", "preflight_mf"];
    if (!data.preflight?.done) return allowed;
    allowed.push("amazon_download");
    allowed.push("rakuten_download");
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const amazonPending = Boolean(data.amazon?.downloaded && !amazonDone);
    const rakutenPending = Boolean(data.rakuten?.downloaded && !rakutenDone);
    if (data.amazon?.downloaded) {
      allowed.push("amazon_print");
    }
    if (data.rakuten?.downloaded) {
      allowed.push("rakuten_print");
    }
    const canReconcile =
      "can_reconcile" in data ? Boolean(data.can_reconcile) : Boolean(data.amazon?.downloaded || data.rakuten?.downloaded) && !(amazonPending || rakutenPending);
    if (canReconcile) {
      allowed.push("mf_reconcile");
    }
    return allowed;
  }

  function applyActionAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const allowedModes = inferAllowedModes(data);
    document.querySelectorAll("[data-step-action]").forEach((button) => {
      const mode = String(button.dataset.stepAction || "");
      const allowed = allowedModes.includes(mode);
      const blockedByRunning = Boolean(runningMode);
      const blockedByOrder = !allowed;
      button.disabled = blockedByRunning || blockedByOrder;
      if (blockedByRunning) {
        button.title = "Another task is running.";
      } else if (blockedByOrder) {
        button.title = "Follow the wizard order.";
      } else {
        button.title = "";
      }
    });
  }

  function applyArchiveAvailability(data) {
    document.querySelectorAll("[data-archive-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const runningMode = String(data.running_mode || "");
      const amazonDownloaded = Boolean(data.amazon?.downloaded);
      const rakutenDownloaded = Boolean(data.rakuten?.downloaded);
      const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
      const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
      const amazonPending = Boolean(amazonDownloaded && !amazonDone);
      const rakutenPending = Boolean(rakutenDownloaded && !rakutenDone);
      const hasDownloadedSource = amazonDownloaded || rakutenDownloaded;
      const canArchive =
        "archive" in data && data.archive && typeof data.archive === "object"
          ? Boolean(data.archive.can_archive)
          : (hasDownloadedSource && !(amazonPending || rakutenPending));
      const allowed = canArchive;
      const blockedByRunning = Boolean(runningMode);
      const action = button.dataset.archiveAction;

      // For month_close button, also check checklist state
      if (action === "month_close") {
        const checklistComplete = isChecklistComplete();
        button.disabled = blockedByRunning || !allowed || !checklistComplete;
        if (blockedByRunning) {
          button.title = "Another task is running.";
        } else if (!allowed && !checklistComplete) {
          button.title = "Archive conditions and month-close checklist are incomplete.";
        } else if (!allowed) {
          button.title = "Archive is not available yet.";
        } else if (!checklistComplete) {
          button.title = "Complete month-close checklist first.";
        } else {
          button.title = "";
        }
      } else {
        // For archive_outputs button, keep original logic
        button.disabled = blockedByRunning || !allowed;
        if (blockedByRunning) {
          button.title = "Another task is running.";
        } else if (!allowed) {
          button.title = "Archive is not available yet.";
        } else {
          button.title = "";
        }
      }
    });
  }

  function applyManualAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const preflightDone = Boolean(data.preflight?.done);
    document.querySelectorAll("[data-manual-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const blockedByRunning = Boolean(runningMode);
      const action = String(button.dataset.manualAction || "");
      const needsPreflight = action === "run_mf_bulk_upload" || action === "run_mf_csv_import";
      const blockedByPreflight = needsPreflight && !preflightDone;
      button.disabled = blockedByRunning || blockedByPreflight;
      if (blockedByRunning) {
        button.title = "Another task is running.";
      } else if (blockedByPreflight) {
        button.title = "Run preflight first.";
      } else {
        button.title = "";
      }
    });
  }

  function applyProviderAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const providers = data && typeof data === "object" ? data.providers : null;
    const sourceStatus = providers && typeof providers === "object" ? providers.source : null;
    const sourceConfigured = Boolean(sourceStatus && sourceStatus.configured);
    const sourceExists = Boolean(sourceStatus && sourceStatus.exists);
    document.querySelectorAll("[data-provider-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const blockedByRunning = Boolean(runningMode);
      const action = String(button.dataset.providerAction || "");
      if (action === "open_provider_source") {
        const blockedBySource = !sourceConfigured || !sourceExists;
        button.disabled = blockedByRunning || blockedBySource;
        if (blockedByRunning) {
          button.title = "Another task is running.";
        } else if (!sourceConfigured) {
          button.title = "Provider source folder is not configured.";
        } else if (!sourceExists) {
          button.title = "Provider source folder not found.";
        } else {
          button.title = "";
        }
      } else {
        button.disabled = blockedByRunning;
        button.title = blockedByRunning ? "(msg)" : "";
      }
    });
  }

  function toCount(value) {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 0) return 0;
    return parsed;
  }

  function buildMfSummaryText(data) {
    const runningMode = String(data?.running_mode || "");
    if (runningMode === "mf_reconcile") {
      return "MF reconcile is running.";
    }
    const mf = data && typeof data === "object" ? data.mf : null;
    const summary = mf && typeof mf === "object" ? mf.summary : null;
    const missingCandidates = toCount(summary?.missing_candidates);
    const targetsTotal = toCount(summary?.targets_total);
    const created = toCount(summary?.created);
    const failed = toCount(summary?.failed);
    const status = String(summary?.status || "").trim().toLowerCase();
    const hasDraftResult = targetsTotal > 0 || created > 0 || failed > 0 || Boolean(status);
    const reconciled = Boolean(mf?.reconciled);

    if (!reconciled && !hasDraftResult && missingCandidates === 0) {
      return "MF reconcile not started.";
    }
    if (!hasDraftResult) {
      return `Pending candidates: ${missingCandidates}`;
    }
    return `Pending: ${missingCandidates} / Created: ${created}/${targetsTotal} / Failed: ${failed}`;
  }
  function renderMfSummary(data, fallbackMessage = "") {
    const summaryEl = document.querySelector("[data-mf-summary]");
    if (!summaryEl) return;
    if (fallbackMessage) {
      summaryEl.textContent = fallbackMessage;
      return;
    }
    summaryEl.textContent = buildMfSummaryText(data);
  }

  function fileNameFromPath(rawPath) {
    const path = String(rawPath || "").trim();
    if (!path) return "";
    const normalized = path.replace(/\\/g, "/");
    const parts = normalized.split("/");
    return parts.length > 0 ? parts[parts.length - 1] : normalized;
  }

  function buildProviderSourceSummarySuffix(scanSummary, pendingFiles) {
    const summary = scanSummary && typeof scanSummary === "object" ? scanSummary : {};
    const matched = toCount(summary.matched);
    const checked = toCount(summary.checked);
    const pdfFiles = toCount(summary.pdf_files);
    const ignoredOutOfMonth = toCount(summary.ignored_out_of_month);
    const ignoredUnmatchedName = toCount(summary.ignored_unmatched_name);
    const ignoredNonPdf = toCount(summary.ignored_non_pdf);
    const ignoredHidden = toCount(summary.ignored_hidden);
    const parts = [];
    const effectivePending = Math.max(0, pendingFiles);
    if (checked > 0) {
      parts.push(`${checked} file(s) checked`);
    }
    if (pdfFiles > 0) {
      parts.push(`${pdfFiles} PDF file(s)`);
    }
    if (effectivePending > 0) {
      parts.push(`${effectivePending} matched file(s)`);
    }
    if (matched > 0 && pendingFiles === 0) {
      parts.push(`${matched} matched in scan`);
    }
    if (ignoredOutOfMonth > 0) {
      parts.push(`${ignoredOutOfMonth} outside target month`);
    }
    if (ignoredNonPdf > 0) {
      parts.push(`${ignoredNonPdf} non-PDF ignored`);
    }
    if (ignoredHidden > 0) {
      parts.push(`${ignoredHidden} hidden file(s) ignored`);
    }
    const scanError = String(summary.scan_error || "").trim();
    if (scanError) {
      parts.push(`scan status: ${scanError}`);
    }
    return parts.length > 0 ? ` (${parts.join(", ")})` : "";
  }

  function buildProviderSourceSummaryText(rawSource) {
    const source = rawSource && typeof rawSource === "object" ? rawSource : {};
    const configured = Boolean(source.configured);
    const exists = Boolean(source.exists);
    const pending = toCount(source.pending_files);
    const path = String(source.path || "").trim();
    const scanSummary = source.scan_summary && typeof source.scan_summary === "object" ? source.scan_summary : {};
    const sampleMatched = Array.isArray(scanSummary.sample_matched)
      ? scanSummary.sample_matched.map(fileNameFromPath).filter(Boolean).slice(0, 3)
      : [];
    const detailsSuffix = buildProviderSourceSummarySuffix(scanSummary, pending);
    const sampleText = sampleMatched.length > 0 ? ` e.g. ${sampleMatched.join(", ")}` : "";

    if (!configured) {
      return "Provider source folder is not configured.";
    }
    if (!exists) {
      return `Configured provider source folder not found: ${path || "(not set)"}`;
    }
    const checked = toCount(scanSummary.checked);
    if (pending === 0 && checked > 0) {
      const scanHint = String(scanSummary.scan_error || "").trim();
      const status = scanHint ? `${scanHint}; ` : "";
      return `${path}: no files matched the selected year-month. ${status}Checked ${checked} file(s).${sampleText ? ` (sample: ${sampleText})` : ""}${detailsSuffix}`;
    }
    if (!path) {
      return `Provider source folder is ready${detailsSuffix}`;
    }
    if (sampleText) {
      return `${path}: ${sampleText}${detailsSuffix}`;
    }
    return `${path}${detailsSuffix}`;
  }

  function renderProviderSourceSummary(rawSource, fallbackMessage = "") {
    const source = rawSource && typeof rawSource === "object" ? rawSource : {};
    const summaryEl = document.querySelector("[data-provider-source-summary]");
    if (!summaryEl) return;
    const text = fallbackMessage || buildProviderSourceSummaryText(rawSource);
    summaryEl.textContent = text;
    const guideEl = document.querySelector("[data-provider-source-setup-guide]");
    if (guideEl) {
      const needsGuide =
        Boolean(fallbackMessage) ||
        !Boolean(source.configured) ||
        !Boolean(source.exists) ||
        text.toLowerCase().includes("not configured") ||
        text.toLowerCase().includes("not found");
      guideEl.hidden = !needsGuide;
      const guideLinkEl = guideEl.querySelector("a");
      if (guideLinkEl) {
        guideLinkEl.href = PROVIDER_SOURCE_SETUP_GUIDE_URL;
      }
    }
  }

  function buildProviderImportSummaryText(rawProviders, runningMode) {
    const providers = rawProviders && typeof rawProviders === "object" ? rawProviders : {};
    const running = String(runningMode || "").trim() === "import_provider_receipts";
    if (running) {
      return "Provider import is running...";
    }

    const lastImport = providers.last_import && typeof providers.last_import === "object" ? providers.last_import : {};
    const attempted = Boolean(lastImport.attempted);
    const pending = toCount(providers.pending_total);
    const updatedAt = String(lastImport.updated_at || "").trim();
    const updatedText = updatedAt ? ` (${updatedAt})` : "";

    if (!attempted) {
      if (pending > 0) {
        return `${pending} file(s) are waiting to be imported.`;
      }
      return `No provider import has been executed yet.${updatedText}`;
    }

    const foundFiles = toCount(lastImport.found_files);
    const foundPdfs = toCount(lastImport.found_pdfs);
    const imported = toCount(lastImport.imported);
    const skipped = toCount(lastImport.skipped_duplicates);
    const failed = toCount(lastImport.failed);
    const manualActionRequired = Boolean(lastImport.manual_action_required);
    const manualActionReason = String(lastImport.manual_action_reason || "").trim();

    const detected = foundPdfs > 0 ? foundPdfs : foundFiles;
    const parts = [];
    if (detected > 0) {
      parts.push(`Detected: ${detected}`);
    }
    if (imported > 0) {
      parts.push(`Imported: ${imported}`);
    }
    if (skipped > 0) {
      parts.push(`Skipped(dup): ${skipped}`);
    }
    if (failed > 0) {
      parts.push(`Failed: ${failed}`);
    }

    const prefix = manualActionRequired || failed > 0 ? "⚠ Import completed with warnings: " : "Import completed: ";
    const summary = parts.length > 0 ? parts.join(" / ") : "No rows were detected.";
    const reason = manualActionReason ? ` (reason: ${manualActionReason})` : "";
    return `${prefix}${summary}${reason}${updatedText}`;
  }

  function renderProviderImportSummary(rawProviders, runningMode, fallbackMessage = "") {
    const summaryEl = document.querySelector("[data-provider-import-summary]");
    if (!summaryEl) return;
    summaryEl.textContent = fallbackMessage || buildProviderImportSummaryText(rawProviders, runningMode);
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
    const providerRunning = runningMode === "import_provider_receipts";
    const mfBulkUploadRunning = runningMode === "mf_bulk_upload" || runningMode === "mf_csv_import";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const providerDone = Boolean(data.providers?.step_done);
    const mfBulkUploadDone = Boolean(data.mf_bulk_upload?.done || data.mf_csv_import?.done);
    return {
      preflight: data.preflight?.done ? "done" : runningMode === "preflight" ? "running" : "pending",
      amazon_download: amazonRunning ? "running" : data.amazon?.downloaded ? "done" : "pending",
      amazon_decide_print: runningMode === "amazon_print" ? "running" : amazonDone ? "done" : "pending",
      rakuten_download: rakutenRunning ? "running" : data.rakuten?.downloaded ? "done" : "pending",
      rakuten_decide_print: runningMode === "rakuten_print" ? "running" : rakutenDone ? "done" : "pending",
      provider_ingest: providerRunning ? "running" : providerDone ? "done" : "pending",
      mf_bulk_upload_task: mfBulkUploadRunning ? "running" : mfBulkUploadDone ? "done" : "pending",
      mf_reconcile:
        runningMode === "mf_reconcile"
          ? "running"
          : Boolean(data.mf?.step_done ?? data.mf?.reconciled)
            ? "done"
            : "pending",
    };
  }

  function buildTaskStates(stepStates) {
    const amazonRunning = stepStates.amazon_download === "running" || stepStates.amazon_decide_print === "running";
    const rakutenRunning = stepStates.rakuten_download === "running" || stepStates.rakuten_decide_print === "running";
    return {
      amazon: amazonRunning ? "running" : stepStates.amazon_decide_print === "done" ? "done" : "pending",
      rakuten: rakutenRunning ? "running" : stepStates.rakuten_decide_print === "done" ? "done" : "pending",
    };
  }

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
        preflight: "莠句燕貅門ｙ",
        amazon_download: "Amazon取り込み",
        amazon_decide_print: "Amazon蜊ｰ蛻ｷ蛻､螳・,
        rakuten_download: "楽天取り込み",
        rakuten_decide_print: "讌ｽ螟ｩ蜊ｰ蛻ｷ蛻､螳・,
        provider_ingest: "プロバイダ受領分の取り込み",
        mf_bulk_upload_task: "MF一括アップロード",
        mf_reconcile: "MF遯∝粋",
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
    hydrateTemplateSourceUrls();
    applyTemplateModeUI();
    const templateSourceUrlAddButton = document.getElementById("template-source-url-add");
    templateSourceUrlAddButton?.addEventListener("click", (event) => {
      event.preventDefault();
      addTemplateSourceUrlRow("");
    });
    const templateStepAddButton = document.getElementById("template-step-add");
    templateStepAddButton?.addEventListener("click", (event) => {
      event.preventDefault();
      addTemplateStepFromDefaultCard({});
    });
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

    hydrateTemplateSteps();
    renderWorkflowCreatePreview();
    applyWorkflowPageStepLayout(workflowPage?.steps);
    renderWorkflowPageStepVersionLabel();
    restoreYmSelection();
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
})();
