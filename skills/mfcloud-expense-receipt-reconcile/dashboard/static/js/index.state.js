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


window.DashboardIndexState = {
  normalizeYm,
  parseYm,
  parseWorkflowTemplate,
  parseWorkflowPage,
  workflowTemplate,
  workflowPage,
  defaultTitleForStepAction,
  normalizeTemplateStepAutoRun,
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
