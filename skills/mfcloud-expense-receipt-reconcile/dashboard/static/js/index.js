(function () {
  window.DashboardIndex = window.DashboardIndex || {};
  window.DashboardIndex.loaded = true;

  const constants = window.DashboardIndexConstants || {};
  const workflowTemplateDefaultTimer =
    Number(constants.WORKFLOW_TEMPLATE_DEFAULT_STEP_TIMER_MINUTES || constants.TEMPLATE_STEP_TIMER_DEFAULT_MINUTES);
  const templateTimerDefault = Number.isFinite(workflowTemplateDefaultTimer) ? workflowTemplateDefaultTimer : 5;
  window.TEMPLATE_STEP_TIMER_DEFAULT_MINUTES = window.TEMPLATE_STEP_TIMER_DEFAULT_MINUTES || templateTimerDefault;
})();