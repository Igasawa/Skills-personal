(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));

  const DEFAULT_TIMER_MINUTES = 5;
  const MAX_TIMER_MINUTES = 7 * 24 * 60;

  const form = document.getElementById("run-form");
  const listEl = document.querySelector("[data-template-steps-list]");
  const addButton = document.getElementById("template-step-add");
  const pageEl = document.querySelector(".page");

  if (!form || !listEl || !addButton) return;

  function normalizeTimerMinutes(value) {
    const parsed = Number.parseInt(String(value ?? "").trim(), 10);
    if (!Number.isInteger(parsed)) return DEFAULT_TIMER_MINUTES;
    if (parsed < 0) return 0;
    if (parsed > MAX_TIMER_MINUTES) return MAX_TIMER_MINUTES;
    return parsed;
  }

  function getRows() {
    return Array.from(listEl.querySelectorAll("[data-template-step-row]"));
  }

  function getTemplateStepActionOptionsHtml(selectedAction) {
    const rows = getRows();
    const firstSelect = rows[0]?.querySelector("[data-template-step-action]");
    const optionsHtml = String(firstSelect?.innerHTML || "").trim();
    if (optionsHtml) {
      const wrap = document.createElement("select");
      wrap.innerHTML = optionsHtml;
      if (selectedAction) wrap.value = selectedAction;
      return wrap.innerHTML;
    }
    const fallback = [
      ["preflight", "Preflight"],
      ["preflight_mf", "Preflight MF"],
      ["amazon_download", "Amazon Download"],
      ["rakuten_download", "Rakuten Download"],
      ["amazon_print", "Amazon Print"],
      ["rakuten_print", "Rakuten Print"],
    ];
    return fallback
      .map(([value, label]) => `<option value="${value}"${value === selectedAction ? " selected" : ""}>${label}</option>`)
      .join("");
  }

  function buildCloneTitle(title, index) {
    const raw = String(title || "").trim() || "Task";
    const base = raw.replace(/\s+\d+$/, "").trim() || "Task";
    return `${base} ${index}`;
  }

  function setRemoveButtonState() {
    const rows = getRows();
    const lock = rows.length <= 1;
    rows.forEach((row) => {
      const removeButton = row.querySelector("[data-template-step-remove]");
      if (!removeButton) return;
      removeButton.hidden = lock;
      removeButton.disabled = lock;
    });
  }

  function renumberRows() {
    const rows = getRows();
    rows.forEach((row, index) => {
      const indexEl = row.querySelector("[data-template-step-index]");
      if (indexEl) indexEl.textContent = `Task ${index + 1}`;

      const titleEl = row.querySelector("[data-template-step-title]");
      if (titleEl) {
        titleEl.setAttribute("aria-label", `Task ${index + 1} title`);
      }
      const timerEl = row.querySelector("[data-template-step-timer]");
      if (timerEl) {
        timerEl.value = String(normalizeTimerMinutes(timerEl.value));
        timerEl.setAttribute("aria-label", `Task ${index + 1} timer minutes`);
      }
    });
    setRemoveButtonState();

    listEl.dispatchEvent(
      new CustomEvent("template-steps-changed", {
        bubbles: true,
      }),
    );
  }

  function resolveSchedulerTemplateId() {
    const workflowPageRaw = String(pageEl?.dataset?.workflowPage || "").trim();
    if (workflowPageRaw) {
      try {
        const workflowPage = JSON.parse(workflowPageRaw);
        const workflowPageId = String(workflowPage?.id || "").trim();
        if (workflowPageId) return workflowPageId;
      } catch {
        // ignore
      }
    }
    const templateId = String(form.querySelector("[name=template_id]")?.value || "").trim();
    if (templateId) return templateId;
    return "";
  }

  function buildSchedulerStateUrl() {
    const templateId = resolveSchedulerTemplateId();
    if (!templateId) return "/api/scheduler/state";
    return `/api/scheduler/state?template_id=${encodeURIComponent(templateId)}`;
  }

  function resolveYearMonth() {
    const year = Number.parseInt(String(form.querySelector("[name=year]")?.value || "").trim(), 10);
    const month = Number.parseInt(String(form.querySelector("[name=month]")?.value || "").trim(), 10);
    if (!Number.isInteger(year) || !Number.isInteger(month) || month < 1 || month > 12) return null;
    return { year, month };
  }

  function resolvePrimarySourceUrl() {
    const direct = String(form.querySelector("[name=mfcloud_url]")?.value || "").trim();
    if (direct) return direct;
    const fromList = String(form.querySelector("[data-source-url-input]")?.value || "").trim();
    return fromList;
  }

  async function scheduleRow(row, button) {
    const action = String(row.querySelector("[data-template-step-action]")?.value || "").trim() || "preflight";
    const title = String(row.querySelector("[data-template-step-title]")?.value || "").trim() || "Task";
    const timerMinutes = normalizeTimerMinutes(row.querySelector("[data-template-step-timer]")?.value);
    const ym = resolveYearMonth();
    if (!ym) {
      showToast("Year/month is invalid.", "error");
      return;
    }

    const now = new Date();
    now.setSeconds(0, 0);
    now.setMinutes(now.getMinutes() + timerMinutes);
    const runDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    const runTime = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;

    const schedulerUrl = buildSchedulerStateUrl();
    const summaryEl = row.querySelector("[data-template-step-schedule-summary]");
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Scheduling...";
    try {
      const currentRes = await fetch(`${schedulerUrl}${schedulerUrl.includes("?") ? "&" : "?"}_=${Date.now()}`, {
        cache: "no-store",
      }).catch(() => null);
      const currentState = currentRes && currentRes.ok ? await currentRes.json().catch(() => ({})) : {};
      const cardId = String(row.dataset.templateStepId || row.dataset.templateStepCardId || `workflow-step:${action}`).trim();
      const payload = {
        enabled: true,
        card_id: cardId,
        action_key: action,
        year: ym.year,
        month: ym.month,
        mfcloud_url: String(currentState?.mfcloud_url || resolvePrimarySourceUrl() || "").trim(),
        notes: String(currentState?.notes || form.querySelector("[name=notes]")?.value || "").trim(),
        run_date: runDate,
        run_time: runTime,
        catch_up_policy: String(currentState?.catch_up_policy || "run_on_startup"),
        recurrence: "once",
      };

      const res = await fetch(schedulerUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => null);
      if (!res) throw new Error("network error");
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);

      const scheduledAt = `${runDate} ${runTime}`;
      if (summaryEl) summaryEl.textContent = `Scheduled: ${scheduledAt}`;
      showToast(`Task scheduled: ${title} (${scheduledAt})`, "success");
      document.dispatchEvent(new CustomEvent("scheduler-state-updated", { bubbles: true }));
    } catch (error) {
      showToast(toFriendlyMessage(error?.message || "Failed to schedule task."), "error");
    } finally {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }

  function bindRow(row) {
    const removeButton = row.querySelector("[data-template-step-remove]");
    if (removeButton && removeButton.dataset.timerBound !== "1") {
      removeButton.dataset.timerBound = "1";
      removeButton.addEventListener("click", () => {
        setTimeout(() => {
          renumberRows();
        }, 0);
      });
    }

    const scheduleButton = row.querySelector("[data-template-step-schedule]");
    if (scheduleButton && scheduleButton.dataset.timerBound !== "1") {
      scheduleButton.dataset.timerBound = "1";
      scheduleButton.addEventListener("click", (event) => {
        event.preventDefault();
        scheduleRow(row, scheduleButton);
      });
    }

    const titleEl = row.querySelector("[data-template-step-title]");
    const actionEl = row.querySelector("[data-template-step-action]");
    const timerEl = row.querySelector("[data-template-step-timer]");
    if (titleEl && titleEl.dataset.timerBound !== "1") {
      titleEl.dataset.timerBound = "1";
      titleEl.addEventListener("input", renumberRows);
    }
    if (actionEl && actionEl.dataset.timerBound !== "1") {
      actionEl.dataset.timerBound = "1";
      actionEl.addEventListener("change", renumberRows);
    }
    if (timerEl && timerEl.dataset.timerBound !== "1") {
      timerEl.dataset.timerBound = "1";
      timerEl.addEventListener("change", renumberRows);
    }
  }

  function ensureRowControls(row) {
    const actionEl = row.querySelector("[data-template-step-action]");
    const removeButton = row.querySelector("[data-template-step-remove]");
    if (!actionEl || !removeButton) return;

    let timerEl = row.querySelector("[data-template-step-timer]");
    if (!timerEl) {
      timerEl = document.createElement("input");
      timerEl.type = "number";
      timerEl.className = "template-step-timer";
      timerEl.dataset.templateStepTimer = "1";
      timerEl.min = "0";
      timerEl.max = String(MAX_TIMER_MINUTES);
      timerEl.step = "1";
      timerEl.value = String(DEFAULT_TIMER_MINUTES);
      timerEl.required = true;
      timerEl.title = "Timer (minutes)";
      row.insertBefore(timerEl, removeButton);
    } else {
      timerEl.value = String(normalizeTimerMinutes(timerEl.value));
    }

    let scheduleButton = row.querySelector("[data-template-step-schedule]");
    if (!scheduleButton) {
      scheduleButton = document.createElement("button");
      scheduleButton.type = "button";
      scheduleButton.className = "secondary";
      scheduleButton.dataset.templateStepSchedule = "1";
      scheduleButton.textContent = "Set Timer";
      row.insertBefore(scheduleButton, removeButton);
    }

    let summaryEl = row.querySelector("[data-template-step-schedule-summary]");
    if (!summaryEl) {
      summaryEl = document.createElement("span");
      summaryEl.className = "muted template-step-schedule-summary";
      summaryEl.dataset.templateStepScheduleSummary = "1";
      summaryEl.textContent = "";
      row.appendChild(summaryEl);
    }

    bindRow(row);
  }

  function createRowFromDefault() {
    const rows = getRows();
    const first = rows[0] || null;
    const nextIndex = rows.length + 1;
    const defaultTitle = String(first?.querySelector("[data-template-step-title]")?.value || "Task").trim() || "Task";
    const defaultAction = String(first?.querySelector("[data-template-step-action]")?.value || "preflight").trim() || "preflight";
    const defaultTimer = normalizeTimerMinutes(first?.querySelector("[data-template-step-timer]")?.value);

    const row = document.createElement("div");
    row.className = "template-step-row";
    row.dataset.templateStepRow = "1";
    row.dataset.templateStepId = `step-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

    const indexEl = document.createElement("span");
    indexEl.className = "muted";
    indexEl.dataset.templateStepIndex = "1";

    const titleEl = document.createElement("input");
    titleEl.type = "text";
    titleEl.className = "template-step-title";
    titleEl.dataset.templateStepTitle = "1";
    titleEl.required = true;
    titleEl.value = buildCloneTitle(defaultTitle, nextIndex);

    const actionEl = document.createElement("select");
    actionEl.className = "template-step-action";
    actionEl.dataset.templateStepAction = "1";
    actionEl.innerHTML = getTemplateStepActionOptionsHtml(defaultAction);
    actionEl.value = defaultAction;

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "secondary";
    removeButton.dataset.templateStepRemove = "1";
    removeButton.textContent = "-";
    removeButton.setAttribute("aria-label", "Remove task");
    removeButton.addEventListener("click", () => {
      row.remove();
      renumberRows();
    });

    row.appendChild(indexEl);
    row.appendChild(titleEl);
    row.appendChild(actionEl);
    row.appendChild(removeButton);
    listEl.appendChild(row);

    ensureRowControls(row);
    const timerEl = row.querySelector("[data-template-step-timer]");
    if (timerEl) timerEl.value = String(defaultTimer);
    renumberRows();
  }

  function enhanceExistingRows() {
    const rows = getRows();
    rows.forEach((row) => ensureRowControls(row));
    renumberRows();
  }

  addButton.addEventListener(
    "click",
    (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      createRowFromDefault();
    },
    true,
  );

  if (getRows().length === 0) {
    createRowFromDefault();
  } else {
    enhanceExistingRows();
  }

  const observer = new MutationObserver(() => {
    enhanceExistingRows();
  });
  observer.observe(listEl, { childList: true, subtree: false });
})();
