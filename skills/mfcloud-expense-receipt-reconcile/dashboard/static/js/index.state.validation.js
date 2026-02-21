(function () {
  const state = window.DashboardIndexState || {};
  const fallback = window.DashboardIndexStateValidation || {};
  const namespace = Object.assign({}, fallback, state);

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  register({
    normalizeYm: namespace.normalizeYm || function () { return ""; },
    parseYm: namespace.parseYm || function () { return null; },
    parseWorkflowTemplate: namespace.parseWorkflowTemplate || function () { return null; },
    parseWorkflowPage: namespace.parseWorkflowPage || function () { return null; },
    workflowTemplate: namespace.workflowTemplate || null,
    workflowPage: namespace.workflowPage || null,
    defaultTitleForStepAction: namespace.defaultTitleForStepAction || function () { return ""; },
    normalizeTemplateStepAutoRun: namespace.normalizeTemplateStepAutoRun || function () { return false; },
    normalizeTemplateStepType: namespace.normalizeTemplateStepType || function () { return "manual"; },
    normalizeTemplateStepTriggerKind: namespace.normalizeTemplateStepTriggerKind || function () { return "manual_start"; },
    normalizeTemplateStepTrigger: namespace.normalizeTemplateStepTrigger || function () { return "manual_start"; },
    normalizeTemplateStepExecutionMode: namespace.normalizeTemplateStepExecutionMode || function () { return "manual_confirm"; },
    executionModeFromAutoRun: namespace.executionModeFromAutoRun || function () { return "manual_confirm"; },
    autoRunFromExecutionMode: namespace.autoRunFromExecutionMode || function () { return false; },
    normalizeTemplateStepAction: namespace.normalizeTemplateStepAction || function (value) { return String(value || "").trim(); },
    normalizeTemplateStepOrder: namespace.normalizeTemplateStepOrder || function () { return 0; },
    normalizeTemplateStepExecutionLog: namespace.normalizeTemplateStepExecutionLog || function () { return ""; },
    normalizeTemplateStepTimerMinutes: namespace.normalizeTemplateStepTimerMinutes || function () { return 0; },
    parseTemplateStepExecutionLogFromRow: namespace.parseTemplateStepExecutionLogFromRow || function () { return ""; },
    formatTemplateStepLatestExecutionLog: namespace.formatTemplateStepLatestExecutionLog || function () { return ""; },
    setTemplateStepExecutionLogOnRow: namespace.setTemplateStepExecutionLogOnRow || function () {},
    getTemplateStepRows: namespace.getTemplateStepRows || function () { return []; },
    getTemplateStepActionOptionsHtml: namespace.getTemplateStepActionOptionsHtml || function () { return ""; },
    getTemplateStepTypeOptionsHtml: namespace.getTemplateStepTypeOptionsHtml || function () { return ""; },
    getAllowedExecutionModesForStepType: namespace.getAllowedExecutionModesForStepType || function () { return []; },
    getTemplateStepExecutionModeOptionsHtml:
      namespace.getTemplateStepExecutionModeOptionsHtml || function () { return ""; },
    getAllowedTriggerKindsForPosition: namespace.getAllowedTriggerKindsForPosition || function () { return []; },
    getTemplateStepTriggerOptionsHtml: namespace.getTemplateStepTriggerOptionsHtml || function () { return ""; },
    parseTemplateStepRow: namespace.parseTemplateStepRow || function () { return {}; },
    refreshTemplateStepRows: namespace.refreshTemplateStepRows || function () {},
    validateTemplateStepRows: namespace.validateTemplateStepRows || function () { return []; },
    collectTemplateSteps: namespace.collectTemplateSteps || function () { return []; },
    addTemplateStepFromDefaultCard: namespace.addTemplateStepFromDefaultCard || function () {},
    addTemplateStepRow: namespace.addTemplateStepRow || function () {},
    hydrateTemplateSteps: namespace.hydrateTemplateSteps || function () {},
    hydrateTemplateSourceUrls: namespace.hydrateTemplateSourceUrls || function () {},
    applyTemplateModeUI: namespace.applyTemplateModeUI || function () {},
    getTemplateIdFromForm: namespace.getTemplateIdFromForm || function () { return ""; },
    getTemplateSourceIdFromForm: namespace.getTemplateSourceIdFromForm || function () { return ""; },
    getTemplateUpdatedAtFromForm: namespace.getTemplateUpdatedAtFromForm || function () { return ""; },
    shouldSyncYmQueryParams: namespace.shouldSyncYmQueryParams || function () { return false; },
    readYmFromQueryString: namespace.readYmFromQueryString || function () { return ""; },
    readYmFromLocalStorage: namespace.readYmFromLocalStorage || function () { return ""; },
    persistYmSelection: namespace.persistYmSelection || function () {},
    restoreYmSelection: namespace.restoreYmSelection || function () {},
    normalizeChecklistState: namespace.normalizeChecklistState || function () { return {}; },
    isChecklistComplete: namespace.isChecklistComplete || function () { return false; },
    formatDateTimeInJst: namespace.formatDateTimeInJst || function () { return ""; },
    nowIsoLikeInJst: namespace.nowIsoLikeInJst || function () { return ""; },
  });

  window.DashboardIndexStateValidation = namespace;
  window.DashboardIndexState = Object.assign(state, namespace);
})();
