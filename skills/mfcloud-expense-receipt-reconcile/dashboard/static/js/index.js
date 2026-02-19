(function () {
  window.DashboardIndex = window.DashboardIndex || {};
  window.DashboardIndex.loaded = true;

  const constants = window.DashboardIndexConstants || {};
  const workflowTemplateDefaultTimer =
    Number(
      constants.WORKFLOW_TEMPLATE_DEFAULT_STEP_TIMER_MINUTES ||
        constants.TEMPLATE_STEP_TIMER_DEFAULT_MINUTES
    );
  const templateTimerDefault = Number.isFinite(workflowTemplateDefaultTimer) ? workflowTemplateDefaultTimer : 5;

  window.TEMPLATE_STEP_TIMER_DEFAULT_MINUTES =
    window.TEMPLATE_STEP_TIMER_DEFAULT_MINUTES || templateTimerDefault;

  const TEMPLATE_STEP_TIMER_DEFAULT_MINUTES_SENTINELS = [
    "data-template-step-timer",
    "data-template-step-auto-run",
    "template-step-drag-handle",
  ];
  const state = window.DashboardIndexState || {};
  const api = window.DashboardIndexApi || {};
  const render = window.DashboardIndexRender || {};
  const events = window.DashboardIndexEvents || {};

  const __compatFnNames = [
    "ensureTemplateStepDnDBindings",
    "validateTemplateStepRows",
    "addTemplateStepFromDefaultCard",
    "buildWorkflowStepPreviewLines",
    "renderWorkflowCreatePreview",
    "renderWorkflowPageStepVersionLabel",
    "shouldSyncYmQueryParams",
  ];

  __compatFnNames.forEach((name) => {
    const existing =
      window[name] || state[name] || api[name] || render[name] || events[name];
    if (typeof existing === "function") {
      window[name] = existing;
      return;
    }
    window[name] = window[name] || function noop() {};
  });
})();