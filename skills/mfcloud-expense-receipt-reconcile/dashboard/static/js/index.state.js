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
    if (normalizedAction === "preflight") {
      const defaultTitle = String(TEMPLATE_STEP_DEFAULT_TITLES[normalizedAction] || "").trim();
      return defaultTitle;
    }
    if (fallbackTitle) return fallbackTitle;
    return TEMPLATE_STEP_DEFAULT_TITLES[normalizedAction] || TEMPLATE_STEP_ACTION_LABELS[normalizedAction] || "手順";
  }

  function normalizeTemplateStepAutoRun(value) {
    if (typeof value === "boolean") return value;
    const text = String(value ?? "").trim().toLowerCase();
    if (!text) return false;
    return ["1", "true", "yes", "on"].includes(text);
  }

  function normalizeTemplateStepType(value, fallback = "manual") {
    const type = String(value || "").trim().toLowerCase();
    if (TEMPLATE_STEP_TYPE_VALUES.has(type)) return type;
    return TEMPLATE_STEP_TYPE_VALUES.has(fallback) ? fallback : "manual";
  }

  function legacyTriggerToTriggerKind(value, fallback = "manual_start") {
    const trigger = String(value || "").trim().toLowerCase();
    if (!trigger) return fallback;
    if (trigger === "manual") return "manual_start";
    if (trigger === "schedule") return "scheduled";
    if (trigger === "webhook") return "external_event";
    if (trigger === "after_step") return "after_previous";
    if (TEMPLATE_STEP_TRIGGER_KIND_VALUES.has(trigger)) return trigger;
    return fallback;
  }

  function triggerKindToLegacyTrigger(value, fallback = "manual") {
    const triggerKind = String(value || "").trim().toLowerCase();
    if (triggerKind === "manual_start") return "manual";
    if (triggerKind === "scheduled") return "schedule";
    if (triggerKind === "external_event") return "webhook";
    if (triggerKind === "after_previous") return "after_step";
    return fallback;
  }

  function normalizeTemplateStepTriggerKind(value, fallback = "manual_start") {
    const fallbackKind = legacyTriggerToTriggerKind(fallback, "manual_start");
    const triggerKind = legacyTriggerToTriggerKind(value, fallbackKind);
    if (TEMPLATE_STEP_TRIGGER_KIND_VALUES.has(triggerKind)) return triggerKind;
    return fallbackKind;
  }

  function normalizeTemplateStepTrigger(value, fallback = "manual_start") {
    return normalizeTemplateStepTriggerKind(value, fallback);
  }

  function normalizeTemplateStepExecutionMode(value, fallback = "manual_confirm") {
    const mode = String(value || "").trim().toLowerCase();
    if (TEMPLATE_STEP_EXECUTION_MODE_VALUES.has(mode)) return mode;
    if (mode === "manual") return "manual_confirm";
    if (mode === "confirm") return "manual_confirm";
    if (mode === "auto_run") return "auto";
    return TEMPLATE_STEP_EXECUTION_MODE_VALUES.has(fallback) ? fallback : "manual_confirm";
  }

  function executionModeFromAutoRun(value) {
    return normalizeTemplateStepAutoRun(value) ? "auto" : "manual_confirm";
  }

  function autoRunFromExecutionMode(value) {
    return normalizeTemplateStepExecutionMode(value) === "auto";
  }

  function normalizeTemplateStepTargetUrl(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (text.length > 2048) return "";
    try {
      const parsed = new URL(text);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      return text;
    } catch {
      return "";
    }
  }

  function normalizeTemplateStepAgentPrompt(value) {
    if (value === null || value === undefined) return "";
    return String(value).trim().slice(0, TEMPLATE_STEP_MAX_AGENT_PROMPT_CHARS);
  }

  function normalizeTemplateStepAutoTimerEnabled(value, fallback = false) {
    if (typeof value === "boolean") return value;
    if (typeof value === "string") {
      const text = value.trim().toLowerCase();
      if (text === "1" || text === "true" || text === "yes" || text === "on") return true;
      if (text === "0" || text === "false" || text === "off" || text === "") return false;
      return fallback;
    }
    if (typeof value === "number") return value > 0;
    return Boolean(value) ? fallback : false;
  }

  function normalizeTemplateStepUiMode(value, fallback = TEMPLATE_STEP_UI_MODE_DEFAULT) {
    const normalized = String(value || "").trim();
    if (!normalized) return fallback;
    if (Object.prototype.hasOwnProperty.call(TEMPLATE_STEP_UI_MODE, normalized)) {
      return normalized;
    }
    if (Object.values(TEMPLATE_STEP_UI_MODE).includes(normalized)) {
      return normalized;
    }
    return fallback;
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
      if (action && seen.has(action)) return;
      const title = String(raw.title || "").trim();
      const id = String(raw.id || "").trim() || generateTemplateStepId();
      const legacyAutoRun = normalizeTemplateStepAutoRun(raw.auto_run ?? raw.autoRun);
      const targetUrl = normalizeTemplateStepTargetUrl(raw.target_url ?? raw.targetUrl ?? raw.url);
      const agentPrompt = normalizeTemplateStepAgentPrompt(raw.agent_prompt ?? raw.agentPrompt ?? raw.prompt);
      const typeDefault = targetUrl ? "browser" : agentPrompt ? "agent" : "manual";
      const stepType = normalizeTemplateStepType(raw.type ?? raw.step_type, typeDefault);
      let executionMode = normalizeTemplateStepExecutionMode(
        raw.execution_mode,
        executionModeFromAutoRun(legacyAutoRun),
      );
      if (stepType === "manual") {
        executionMode = "manual_confirm";
      }
      let triggerDefault = index === 0
        ? (executionMode === "auto" ? "scheduled" : "manual_start")
        : "after_previous";
      const triggerKind = normalizeTemplateStepTriggerKind(
        raw.trigger_kind ?? raw.trigger,
        triggerDefault,
      );
      const normalizedTriggerKind = index === 0 ? triggerKind : "after_previous";
      const trigger = triggerKindToLegacyTrigger(normalizedTriggerKind);
      const autoRun = autoRunFromExecutionMode(executionMode);
      const hasAutoTimerEnabled = Object.prototype.hasOwnProperty.call(raw, "auto_timer_enabled");
      const hasUiMode = Object.prototype.hasOwnProperty.call(raw, "ui_mode");
      const autoTimerEnabled = normalizeTemplateStepAutoTimerEnabled(raw.auto_timer_enabled, false);
      const timerRaw = raw.timer_minutes ?? raw.timer;
      const timerProvided = Object.prototype.hasOwnProperty.call(raw, "timer_minutes") || Object.prototype.hasOwnProperty.call(raw, "timer");
      let timerMinutes = timerProvided ? normalizeTemplateStepTimerMinutes(timerRaw, null) : null;
      if (autoRun) {
        timerMinutes = normalizeTemplateStepTimerForAutoRun(timerMinutes);
      }
      const rawConfigs = raw.configs && typeof raw.configs === "object" ? raw.configs : {};
      const configs = {
        schedule: rawConfigs.schedule && typeof rawConfigs.schedule === "object" ? { ...rawConfigs.schedule } : {},
        event: rawConfigs.event && typeof rawConfigs.event === "object" ? { ...rawConfigs.event } : {},
        dependency: rawConfigs.dependency && typeof rawConfigs.dependency === "object" ? { ...rawConfigs.dependency } : {},
      };
      const executionLog = normalizeTemplateStepExecutionLog(raw.execution_log ?? raw.executionLog);
      const order = normalizeTemplateStepOrder(raw.order, index + 1);
      if (action) seen.add(action);
      const nextRow = {
        id,
        order,
        title,
        action,
        step_type: stepType,
        type: stepType,
        trigger_kind: normalizedTriggerKind,
        trigger,
        execution_mode: executionMode,
        target_url: targetUrl,
        agent_prompt: agentPrompt,
        auto_run: autoRun,
        configs,
        execution_log: executionLog,
      };
      if (hasAutoTimerEnabled || hasUiMode) {
        const normalizedUiModeFallback = autoTimerEnabled
          ? TEMPLATE_STEP_UI_MODE.advanced
          : TEMPLATE_STEP_UI_MODE_DEFAULT;
        nextRow.ui_mode = normalizeTemplateStepUiMode(
          raw.ui_mode,
          normalizedUiModeFallback,
        );
        nextRow.auto_timer_enabled = autoTimerEnabled;
      }
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
          step_type: "manual",
          type: "manual",
          trigger_kind: "manual_start",
          trigger: "manual",
          execution_mode: "manual_confirm",
          target_url: "",
          agent_prompt: "",
          auto_run: false,
          configs: { schedule: {}, event: {}, dependency: {} },
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
    return normalized.map((row, index) => ({
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
    if (!TEMPLATE_STEP_DEFAULT_ACTION) return "";
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
    title = "確認",
    lines = [],
    confirmLabel = "実行",
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
      subheadingLabel.textContent = "補足説明（任意）";
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
    const rawSelectedAction = String(selectedAction || "").trim();
    const normalizedAction = normalizeTemplateStepAction(rawSelectedAction);
    const options = ['<option value="">(未設定)</option>'];
    if (rawSelectedAction && !TEMPLATE_STEP_ACTIONS.some((item) => item.value === rawSelectedAction)) {
      options.push(`<option value="${rawSelectedAction}" selected>${rawSelectedAction}</option>`);
    }
    options.push(...TEMPLATE_STEP_ACTIONS.map(
      (item) =>
        `<option value="${item.value}"${item.value === normalizedAction ? " selected" : ""}>${item.label}</option>`,
    ));
    return options.join("");
  }

  function getTemplateStepTypeOptionsHtml(selectedType) {
    const normalizedType = normalizeTemplateStepType(selectedType, "manual");
    return TEMPLATE_STEP_TYPES.map(
      (item) =>
        `<option value="${item.value}"${item.value === normalizedType ? " selected" : ""}>${item.label}</option>`,
    ).join("");
  }

  function getAllowedTriggerKindsForPosition(index) {
    return index <= 0
      ? ["manual_start", "scheduled", "external_event"]
      : ["after_previous"];
  }

  function getTemplateStepTriggerOptionsHtml(selectedTriggerKind, allowedTriggerKinds = null) {
    const normalizedTriggerKind = normalizeTemplateStepTriggerKind(selectedTriggerKind, "manual_start");
    const allowed = Array.isArray(allowedTriggerKinds) && allowedTriggerKinds.length
      ? allowedTriggerKinds
      : TEMPLATE_STEP_TRIGGER_KINDS.map((item) => item.value);
    return TEMPLATE_STEP_TRIGGER_KINDS
      .filter((item) => allowed.includes(item.value))
      .map(
        (item) =>
          `<option value="${item.value}"${item.value === normalizedTriggerKind ? " selected" : ""}>${item.label}</option>`,
      )
      .join("");
  }

  function normalizeTemplateStepAction(value) {
    const action = String(value || "").trim();
    if (!action) return "";
    return action;
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
      return { text: "実行履歴はまだありません", status: "none" };
    }
    const result = String(latest.result || "").trim().toLowerCase() === "failed" ? "failed" : "success";
    const label = result === "failed" ? "失敗" : "成功";
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
    const action = normalizeTemplateStepAction(
      row?.dataset?.templateStepAction || row?.querySelector("[data-template-step-action]")?.value,
    );
    const typeEl = row?.querySelector("[data-template-step-type]");
    const triggerEl = row?.querySelector("[data-template-step-trigger-kind]") || row?.querySelector("[data-template-step-trigger]");
    const targetUrlEl = row?.querySelector("[data-template-step-target-url]");
    const agentPromptEl = row?.querySelector("[data-template-step-agent-prompt]");
    const title =
      String(row?.querySelector("[data-template-step-title]")?.value || "").trim();
    const order = normalizeTemplateStepOrder(row?.dataset?.templateStepOrder, index + 1);
    const autoRun = Boolean(row?.querySelector("[data-template-step-auto-run]")?.checked);
    const targetUrl = String(targetUrlEl?.value || "").trim().slice(0, 2048);
    const agentPrompt = normalizeTemplateStepAgentPrompt(agentPromptEl?.value);
    const typeDefault = normalizeTemplateStepTargetUrl(targetUrl) ? "browser" : agentPrompt ? "agent" : "manual";
    const stepType = normalizeTemplateStepType(typeEl?.value, typeDefault);
    const executionModeDefault = executionModeFromAutoRun(autoRun);
    let executionMode = normalizeTemplateStepExecutionMode(
      row?.dataset?.templateStepExecutionMode,
      executionModeDefault,
    );
    if (stepType === "manual") {
      executionMode = "manual_confirm";
    }
    const triggerDefault = index === 0
      ? (executionMode === "auto" ? "scheduled" : "manual_start")
      : "after_previous";
    const triggerKind = normalizeTemplateStepTriggerKind(triggerEl?.value, triggerDefault);
    const normalizedTriggerKind = index === 0 ? triggerKind : "after_previous";
    const trigger = triggerKindToLegacyTrigger(normalizedTriggerKind);
    const autoTimerEnabled = normalizeTemplateStepAutoTimerEnabled(
      row?.dataset?.templateStepAutoTimer,
      false,
    );
    const uiMode = normalizeTemplateStepUiMode(row?.dataset?.templateStepUiMode, TEMPLATE_STEP_UI_MODE_DEFAULT);
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
      auto_timer_enabled: autoTimerEnabled,
      ui_mode: uiMode,
      action,
      step_type: stepType,
      type: stepType,
      trigger_kind: normalizedTriggerKind,
      trigger,
      execution_mode: executionMode,
      target_url: targetUrl,
      agent_prompt: agentPrompt,
      auto_run: autoRunFromExecutionMode(executionMode),
      timer_minutes: timerMinutes,
      configs: { schedule: {}, event: {}, dependency: {} },
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
    const optionalRowsCount = parsedRows.filter((row) => !isRequiredTemplateStepAction(row.action)).length;

    rows.forEach((row, index) => {
      const parsed = parsedRows[index] || {
        action: "",
        title: "",
        step_type: "manual",
        type: "manual",
        trigger_kind: "manual_start",
        trigger: "manual",
        execution_mode: "manual_confirm",
        target_url: "",
        agent_prompt: "",
        auto_run: false,
        timer_minutes: null,
        configs: { schedule: {}, event: {}, dependency: {} },
        execution_log: [],
      };
      const action = normalizeTemplateStepAction(parsed.action);
      const uiMode = normalizeTemplateStepUiMode(
        parsed.ui_mode,
        parsed.auto_timer_enabled ? TEMPLATE_STEP_UI_MODE.advanced : TEMPLATE_STEP_UI_MODE_DEFAULT,
      );
      const autoTimerEnabled = normalizeTemplateStepAutoTimerEnabled(parsed.auto_timer_enabled, false);
      const requiredAction = isRequiredTemplateStepAction(action) ? action : "";

      row.dataset.templateStepAction = action;
      row.dataset.templateStepUiMode = uiMode;
      row.dataset.templateStepAutoTimer = autoTimerEnabled ? "1" : "0";

      row.dataset.templateStepOrder = String(index + 1);
      setTemplateStepExecutionLogOnRow(row, parsed.execution_log);

      const handleEl = row.querySelector("[data-template-step-drag-handle]");
      if (handleEl) {
        handleEl.setAttribute("aria-label", `手順${index + 1}を移動`);
      }

      const indexEl = row.querySelector("[data-template-step-index]");
      if (indexEl) {
        indexEl.textContent = `手順${index + 1}`;
      }

      const titleEl = row.querySelector("[data-template-step-title]");
      if (titleEl) {
        titleEl.setAttribute("aria-label", `手順${index + 1}のタイトル`);
      }

      if (requiredAction) {
        row.dataset.requiredAction = requiredAction;
      } else {
        delete row.dataset.requiredAction;
      }

      const stepType = normalizeTemplateStepType(
        parsed.step_type ?? parsed.type,
        parsed.target_url ? "browser" : parsed.agent_prompt ? "agent" : "manual",
      );
      row.dataset.templateStepType = stepType;
      const typeEl = row.querySelector("[data-template-step-type]");
      if (typeEl) {
        typeEl.value = stepType;
        typeEl.setAttribute("aria-label", `手順${index + 1}のタイプ`);
      }

      const autoRunEl = row.querySelector("[data-template-step-auto-run]");
      let executionMode = normalizeTemplateStepExecutionMode(
        parsed.execution_mode,
        executionModeFromAutoRun(parsed.auto_run),
      );
      if (stepType === "manual") {
        executionMode = "manual_confirm";
      }
      const autoRunEnabled = autoRunFromExecutionMode(executionMode);
      const triggerDefault = index === 0
        ? (autoRunEnabled ? "scheduled" : "manual_start")
        : "after_previous";
      let triggerKind = normalizeTemplateStepTriggerKind(
        parsed.trigger_kind ?? parsed.trigger,
        triggerDefault,
      );
      const allowedTriggerKinds = getAllowedTriggerKindsForPosition(index);
      if (!allowedTriggerKinds.includes(triggerKind)) {
        triggerKind = allowedTriggerKinds[0];
      }
      const trigger = triggerKindToLegacyTrigger(triggerKind);
      row.dataset.templateStepExecutionMode = executionMode;
      row.dataset.templateStepTriggerKind = triggerKind;
      row.dataset.templateStepTrigger = trigger;
      if (autoRunEl) {
        autoRunEl.checked = autoRunEnabled;
        autoRunEl.setAttribute("aria-label", `手順${index + 1}の自動実行`);
        autoRunEl.disabled = stepType === "manual";
      }

      const uiModeEnabled = uiMode === TEMPLATE_STEP_UI_MODE.advanced;
      const advancedContainer = row.querySelector("[data-template-step-advanced]");
      const toggleButton = row.querySelector("[data-template-step-toggle]");
      if (advancedContainer) {
    advancedContainer.dataset.templateStepExpanded = uiModeEnabled ? "1" : "0";
      }
      if (toggleButton) {
        toggleButton.textContent = uiModeEnabled ? AUTO_TIMER_LABEL_ON : AUTO_TIMER_LABEL_OFF;
        toggleButton.setAttribute("aria-expanded", uiModeEnabled ? "true" : "false");
      }

      const timerEl = row.querySelector("[data-template-step-timer]");
      if (timerEl) {
        timerEl.disabled = !autoRunEnabled;
        timerEl.required = autoRunEnabled;
        timerEl.min = autoRunEnabled ? String(TEMPLATE_STEP_TIMER_REQUIRED_MINUTES) : String(TEMPLATE_STEP_TIMER_MIN_MINUTES);
        timerEl.max = String(TEMPLATE_STEP_TIMER_MAX_MINUTES);
        timerEl.setAttribute("aria-label", `手順${index + 1}のタイマー（分）`);
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

      const triggerEl = row.querySelector("[data-template-step-trigger-kind]") || row.querySelector("[data-template-step-trigger]");
      if (triggerEl) {
        triggerEl.innerHTML = getTemplateStepTriggerOptionsHtml(triggerKind, allowedTriggerKinds);
        triggerEl.value = triggerKind;
        triggerEl.setAttribute("aria-label", `手順${index + 1}のトリガー`);
      }

      const targetUrlFieldEl = row.querySelector("[data-template-step-target-url-field]");
      const targetUrlEl = row.querySelector("[data-template-step-target-url]");
      const targetUrl = String(parsed.target_url || "").trim();
      const isBrowserStep = stepType === "browser";
      if (targetUrlFieldEl) {
        targetUrlFieldEl.hidden = !isBrowserStep;
      }
      if (targetUrlEl) {
        targetUrlEl.value = targetUrl;
        targetUrlEl.disabled = !isBrowserStep;
        targetUrlEl.required = isBrowserStep;
        targetUrlEl.setAttribute("aria-label", `手順${index + 1}の遷移URL`);
        if (!targetUrl) {
          targetUrlEl.setCustomValidity(
            isBrowserStep ? "Browserタイプでは遷移URLが必要です。" : "",
          );
        } else {
          const normalizedUrl = normalizeTemplateStepTargetUrl(targetUrl);
          targetUrlEl.setCustomValidity(
            normalizedUrl ? "" : "http:// または https:// 形式のURLを入力してください。",
          );
        }
      }

      const agentPromptFieldEl = row.querySelector("[data-template-step-agent-prompt-field]");
      const agentPromptEl = row.querySelector("[data-template-step-agent-prompt]");
      const agentPrompt = normalizeTemplateStepAgentPrompt(parsed.agent_prompt);
      const isAgentStep = stepType === "agent";
      if (agentPromptFieldEl) {
        agentPromptFieldEl.hidden = !isAgentStep;
      }
      if (agentPromptEl) {
        agentPromptEl.value = agentPrompt;
        agentPromptEl.disabled = !isAgentStep;
        agentPromptEl.required = isAgentStep;
        agentPromptEl.maxLength = TEMPLATE_STEP_MAX_AGENT_PROMPT_CHARS;
        agentPromptEl.setAttribute("aria-label", `手順${index + 1}のAgentプロンプト`);
        agentPromptEl.setCustomValidity(
          isAgentStep && !agentPrompt ? "Agentタイプではプロンプトが必要です。" : "",
        );
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
        removeButton.title = requiredAction ? "必須手順は削除できません。" : "";
      }
    });

    listEl.dataset.stepHasDuplicates = "0";
    emitTemplateStepsChanged();
  }

  function validateTemplateStepRows() {
    const listEl = getTemplateStepsListEl();
    if (!listEl) return true;
    if (listEl.dataset.stepHasDuplicates === "1") {
      showToast("同じアクションは1回だけ選択できます。", "error");
      return false;
    }
    const rows = getTemplateStepRows();
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      const titleEl = row.querySelector("[data-template-step-title]");
      if (titleEl && !String(titleEl.value || "").trim()) {
        titleEl.setCustomValidity("手順タイトルを入力してください。");
        titleEl.reportValidity();
        return false;
      }
      if (titleEl) titleEl.setCustomValidity("");

      const type = normalizeTemplateStepType(
        row.querySelector("[data-template-step-type]")?.value,
        "manual",
      );
      const autoRunEnabled = Boolean(row.querySelector("[data-template-step-auto-run]")?.checked);
      const executionMode = executionModeFromAutoRun(autoRunEnabled);
      if (type === "manual" && executionMode === "auto") {
        showToast("人ステップでは自動実行を選択できません。", "error");
        return false;
      }
      const triggerEl = row.querySelector("[data-template-step-trigger-kind]") || row.querySelector("[data-template-step-trigger]");
      const triggerDefault = index === 0
        ? (executionMode === "auto" ? "scheduled" : "manual_start")
        : "after_previous";
      const triggerKind = normalizeTemplateStepTriggerKind(triggerEl?.value, triggerDefault);
      const allowedTriggerKinds = getAllowedTriggerKindsForPosition(index);
      if (!allowedTriggerKinds.includes(triggerKind)) {
        if (triggerEl) {
          triggerEl.setCustomValidity(
            index === 0
              ? "先頭手順のトリガーは 手動開始 / スケジュール / 外部イベント のみ選択できます。"
              : "2手順目以降のトリガーは 前手順完了後 のみ選択できます。",
          );
          triggerEl.reportValidity();
        } else {
          showToast("トリガー設定が不正です。", "error");
        }
        return false;
      }
      if (triggerEl) {
        triggerEl.setCustomValidity("");
      }
      const targetUrlEl = row.querySelector("[data-template-step-target-url]");
      if (targetUrlEl) {
        const rawTargetUrl = String(targetUrlEl.value || "").trim();
        if (type === "browser") {
          if (!rawTargetUrl) {
            targetUrlEl.setCustomValidity("Browserタイプでは遷移URLが必要です。");
            targetUrlEl.reportValidity();
            return false;
          }
          if (!normalizeTemplateStepTargetUrl(rawTargetUrl)) {
            targetUrlEl.setCustomValidity("http:// または https:// 形式のURLを入力してください。");
            targetUrlEl.reportValidity();
            return false;
          }
        }
        targetUrlEl.setCustomValidity("");
      }

      const agentPromptEl = row.querySelector("[data-template-step-agent-prompt]");
      if (agentPromptEl) {
        const promptValue = normalizeTemplateStepAgentPrompt(agentPromptEl.value);
        if (type === "agent" && !promptValue) {
          agentPromptEl.setCustomValidity("Agentタイプではプロンプトが必要です。");
          agentPromptEl.reportValidity();
          return false;
        }
        agentPromptEl.setCustomValidity("");
      }

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
        timerEl.setCustomValidity(
          `自動実行を有効にする場合、タイマーは${TEMPLATE_STEP_TIMER_REQUIRED_MINUTES}-${TEMPLATE_STEP_TIMER_MAX_MINUTES}分で入力してください。`,
        );
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
    const normalized = normalizeWorkflowStepRows(parsedRows, {
      ensureRequired: false,
      includeTimer: true,
    });
    return normalized.map((row) => ({
      id: row.id,
      order: row.order,
      title: row.title,
      action: row.action,
      step_type: row.step_type ?? row.type,
      type: row.type,
      trigger_kind: row.trigger_kind,
      trigger: row.trigger,
      execution_mode: row.execution_mode,
      target_url: row.target_url,
      agent_prompt: row.agent_prompt,
      auto_run: row.auto_run,
      timer_minutes: row.timer_minutes,
      configs: row.configs || { schedule: {}, event: {}, dependency: {} },
      execution_log: row.execution_log,
    }));
  }

  function addTemplateStepFromDefaultCard(options = {}) {
    const action = "";
    addTemplateStepRow(
      {
        id: "",
        title: "",
        action,
        step_type: "manual",
        type: "manual",
        trigger_kind: "manual_start",
        trigger: "manual",
        execution_mode: "manual_confirm",
        target_url: "",
        agent_prompt: "",
        auto_run: false,
        auto_timer_enabled: false,
        timer_minutes: null,
        configs: { schedule: {}, event: {}, dependency: {} },
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
    const targetUrl = normalizeTemplateStepTargetUrl(rawStep?.target_url ?? rawStep?.targetUrl ?? rawStep?.url);
    const agentPrompt = normalizeTemplateStepAgentPrompt(rawStep?.agent_prompt ?? rawStep?.agentPrompt ?? rawStep?.prompt);
    const legacyAutoRun = normalizeTemplateStepAutoRun(rawStep?.auto_run ?? rawStep?.autoRun);
    const typeDefault = targetUrl ? "browser" : agentPrompt ? "agent" : "manual";
    const stepType = normalizeTemplateStepType(rawStep?.type ?? rawStep?.step_type, typeDefault);
    let executionMode = normalizeTemplateStepExecutionMode(
      rawStep?.execution_mode,
      executionModeFromAutoRun(legacyAutoRun),
    );
    if (stepType === "manual") {
      executionMode = "manual_confirm";
    }
    const autoRun = autoRunFromExecutionMode(executionMode);
    const triggerDefault = autoRun ? "scheduled" : "manual_start";
    const triggerKind = normalizeTemplateStepTriggerKind(rawStep?.trigger_kind ?? rawStep?.trigger, triggerDefault);
    const trigger = triggerKindToLegacyTrigger(triggerKind);
    const hasAutoTimerEnabled = Object.prototype.hasOwnProperty.call(rawStep || {}, "auto_timer_enabled");
    const autoTimerEnabled = normalizeTemplateStepAutoTimerEnabled(rawStep?.auto_timer_enabled, false);
    const uiMode = normalizeTemplateStepUiMode(
      rawStep?.ui_mode,
      hasAutoTimerEnabled
        ? autoTimerEnabled
          ? TEMPLATE_STEP_UI_MODE.advanced
          : TEMPLATE_STEP_UI_MODE_DEFAULT
        : TEMPLATE_STEP_UI_MODE_DEFAULT,
    );
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
    row.dataset.templateStepAction = action;
    row.dataset.templateStepType = stepType;
    row.dataset.templateStepExecutionMode = executionMode;
    row.dataset.templateStepTriggerKind = triggerKind;
    row.dataset.templateStepTrigger = trigger;
    row.dataset.templateStepUiMode = uiMode;
    row.dataset.templateStepAutoTimer = autoTimerEnabled ? "1" : "0";
    row.draggable = true;
    setTemplateStepExecutionLogOnRow(row, executionLog);
    if (requiredAction) {
      row.dataset.requiredAction = requiredAction;
    }

    const dragHandle = document.createElement("button");
    dragHandle.type = "button";
    dragHandle.className = "template-step-drag-handle";
    dragHandle.dataset.templateStepDragHandle = "1";
    dragHandle.setAttribute("aria-label", "手順を移動");
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
    titleEl.placeholder = "手順タイトル";
    titleEl.dataset.templateStepTitle = "1";
    titleEl.required = true;

    const advancedContainer = document.createElement("div");
    advancedContainer.className = "template-step-advanced";
    advancedContainer.dataset.templateStepAdvanced = "1";
    advancedContainer.dataset.templateStepExpanded = uiMode === TEMPLATE_STEP_UI_MODE.advanced ? "1" : "0";

    const typeEl = document.createElement("select");
    typeEl.className = "template-step-type";
    typeEl.dataset.templateStepType = "1";
    typeEl.innerHTML = getTemplateStepTypeOptionsHtml(stepType);

    const triggerEl = document.createElement("select");
    triggerEl.className = "template-step-trigger";
    triggerEl.dataset.templateStepTriggerKind = "1";
    triggerEl.dataset.templateStepTrigger = "1";
    triggerEl.innerHTML = getTemplateStepTriggerOptionsHtml(triggerKind, getAllowedTriggerKindsForPosition(0));

    const autoRunLabel = document.createElement("label");
    autoRunLabel.className = "template-step-auto-run";
    const autoRunEl = document.createElement("input");
    autoRunEl.type = "checkbox";
    autoRunEl.dataset.templateStepAutoRun = "1";
    autoRunEl.checked = autoRun;
    const autoRunText = document.createElement("span");
    autoRunText.textContent = "自動";
    autoRunLabel.appendChild(autoRunEl);
    autoRunLabel.appendChild(autoRunText);

    const timerEl = document.createElement("input");
    timerEl.type = "number";
    timerEl.className = "template-step-timer";
    timerEl.dataset.templateStepTimer = "1";
    timerEl.step = "1";
    timerEl.min = String(TEMPLATE_STEP_TIMER_MIN_MINUTES);
    timerEl.max = String(TEMPLATE_STEP_TIMER_MAX_MINUTES);
    timerEl.placeholder = "分";
    timerEl.value = timerMinutes === null ? "" : String(timerMinutes);

    const targetUrlFieldEl = document.createElement("label");
    targetUrlFieldEl.className = "template-step-target-url-field";
    targetUrlFieldEl.dataset.templateStepTargetUrlField = "1";
    targetUrlFieldEl.textContent = "遷移URL";
    const targetUrlEl = document.createElement("input");
    targetUrlEl.type = "url";
    targetUrlEl.className = "template-step-target-url";
    targetUrlEl.dataset.templateStepTargetUrl = "1";
    targetUrlEl.placeholder = "https://example.com/path";
    targetUrlEl.value = targetUrl;
    targetUrlFieldEl.appendChild(targetUrlEl);

    const agentPromptFieldEl = document.createElement("label");
    agentPromptFieldEl.className = "template-step-agent-prompt-field";
    agentPromptFieldEl.dataset.templateStepAgentPromptField = "1";
    agentPromptFieldEl.textContent = "Agentプロンプト";
    const agentPromptEl = document.createElement("textarea");
    agentPromptEl.className = "template-step-agent-prompt";
    agentPromptEl.dataset.templateStepAgentPrompt = "1";
    agentPromptEl.rows = 2;
    agentPromptEl.placeholder = "この手順でエージェントに実行させる内容を入力";
    agentPromptEl.maxLength = TEMPLATE_STEP_MAX_AGENT_PROMPT_CHARS;
    agentPromptEl.value = agentPrompt;
    agentPromptFieldEl.appendChild(agentPromptEl);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "secondary";
    removeButton.dataset.templateStepRemove = "1";
    removeButton.setAttribute("aria-label", "手順を削除");
    removeButton.textContent = "-";

    const toggleButton = document.createElement("button");
    toggleButton.type = "button";
    toggleButton.className = "secondary template-step-toggle";
    toggleButton.dataset.templateStepToggle = "1";
    toggleButton.textContent = uiMode === TEMPLATE_STEP_UI_MODE.advanced ? AUTO_TIMER_LABEL_ON : AUTO_TIMER_LABEL_OFF;
    toggleButton.setAttribute("aria-expanded", uiMode === TEMPLATE_STEP_UI_MODE.advanced ? "true" : "false");
    toggleButton.setAttribute("aria-label", "手順の詳細設定を切り替え");

    removeButton.addEventListener("click", () => {
      if (row.dataset.requiredAction) {
        showToast("必須手順は削除できません。", "error");
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
    typeEl.addEventListener("change", () => {
      row.dataset.templateStepType = normalizeTemplateStepType(typeEl.value, "manual");
      refreshTemplateStepRows();
    });
    triggerEl.addEventListener("change", refreshTemplateStepRows);
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
    targetUrlEl.addEventListener("input", () => {
      targetUrlEl.setCustomValidity("");
    });
    targetUrlEl.addEventListener("change", refreshTemplateStepRows);
    agentPromptEl.addEventListener("input", () => {
      agentPromptEl.setCustomValidity("");
    });
    agentPromptEl.addEventListener("change", refreshTemplateStepRows);
    row.appendChild(dragHandle);
    row.appendChild(indexEl);
    row.appendChild(titleEl);
    row.appendChild(toggleButton);
    row.appendChild(removeButton);
    advancedContainer.appendChild(typeEl);
    advancedContainer.appendChild(triggerEl);
    advancedContainer.appendChild(autoRunLabel);
    advancedContainer.appendChild(timerEl);
    advancedContainer.appendChild(targetUrlFieldEl);
    advancedContainer.appendChild(agentPromptFieldEl);
    row.appendChild(advancedContainer);
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
      { ensureRequired: false, includeTimer: true },
    );

    listEl.innerHTML = "";
    const rowsToRender = initialRows;
    rowsToRender.forEach((row, index) => {
      const title = String(row?.title || "").trim();
      const action = normalizeTemplateStepAction(row?.action);
      addTemplateStepRow(
        {
          id: row?.id,
          order: row?.order,
          title,
          action,
          step_type: row?.step_type,
          type: row?.type,
          trigger_kind: row?.trigger_kind,
          trigger: row?.trigger,
          execution_mode: row?.execution_mode,
          target_url: row?.target_url,
          agent_prompt: row?.agent_prompt,
          auto_run: row?.auto_run,
          timer_minutes: row?.timer_minutes,
          configs: row?.configs,
          execution_log: row?.execution_log,
          auto_timer_enabled: row?.auto_timer_enabled,
          ui_mode: row?.ui_mode,
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


window.DashboardIndexState = {
  normalizeYm,
  parseYm,
  parseWorkflowTemplate,
  parseWorkflowPage,
  workflowTemplate,
  workflowPage,
  defaultTitleForStepAction,
  normalizeTemplateStepAutoRun,
  legacyTriggerToTriggerKind,
  triggerKindToLegacyTrigger,
  normalizeTemplateStepTriggerKind,
  normalizeTemplateStepType,
  normalizeTemplateStepTrigger,
  normalizeTemplateStepExecutionMode,
  executionModeFromAutoRun,
  autoRunFromExecutionMode,
  normalizeTemplateStepTargetUrl,
  normalizeTemplateStepAgentPrompt,
  normalizeTemplateStepOrder,
  normalizeTemplateStepExecutionLog,
  normalizeTemplateStepTimerForAutoRun,
  normalizeWorkflowStepRows,
  isRequiredTemplateStepAction,
  actionToWorkflowBlockKey,
  nextAvailableTemplateStepAction,
  getTemplateMode,
  getTemplateModeConfig,
  syncTemplatePageHeader,
  normalizeTemplateSourceUrls,
  isValidHttpUrl,
  getTemplateSourceUrlListEl,
  getTemplateSourceUrlRows,
  getTemplateSourceUrlInputs,
  collectTemplateSourceUrls,
  getPrimaryTemplateSourceUrl,
  setTemplateSourceUrlInputNames,
  refreshTemplateSourceUrlRowMeta,
  validateTemplateSourceUrls,
  ensureTemplateSourceUrlRows,
  addTemplateSourceUrlRow,
  getTemplateStepsListEl,
  getTemplateStepRows,
  getTemplateStepActionOptionsHtml,
  getTemplateStepTypeOptionsHtml,
  getAllowedTriggerKindsForPosition,
  getTemplateStepTriggerOptionsHtml,
  normalizeTemplateStepAction,
  generateTemplateStepId,
  emitTemplateStepsChanged,
  normalizeTemplateStepTimerMinutes,
  parseTemplateStepExecutionLogFromRow,
  formatTemplateStepLatestExecutionLog,
  setTemplateStepExecutionLogOnRow,
  getTemplateStepDragAfterRow,
  ensureTemplateStepDnDBindings,
  parseTemplateStepRow,
  refreshTemplateStepRows,
  validateTemplateStepRows,
  collectTemplateSteps,
  addTemplateStepFromDefaultCard,
  addTemplateStepRow,
  hydrateTemplateSteps,
  hydrateTemplateSourceUrls,
  applyTemplateModeUI,
  getTemplateIdFromForm,
  getTemplateSourceIdFromForm,
  getTemplateUpdatedAtFromForm,
  shouldSyncYmQueryParams,
  readYmFromQueryString,
  readYmFromLocalStorage,
  persistYmSelection,
  restoreYmSelection,
  normalizeChecklistState,
  isChecklistComplete,
  formatDateTimeInJst,
  nowIsoLikeInJst,
};
