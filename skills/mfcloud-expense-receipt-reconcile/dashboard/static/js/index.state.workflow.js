(function () {
  const state = window.DashboardIndexStateValidation || window.DashboardIndexState || {};
  const fallback = window.DashboardIndexStateWorkflow || {};
  const namespace = Object.assign({}, fallback, state);

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  register({
    getTemplateSourceUrlListEl: namespace.getTemplateSourceUrlListEl || function () { return null; },
    getTemplateSourceUrlRows: namespace.getTemplateSourceUrlRows || function () { return []; },
    getTemplateSourceUrlInputs: namespace.getTemplateSourceUrlInputs || function () { return []; },
    collectTemplateSourceUrls: namespace.collectTemplateSourceUrls || function () { return []; },
    getPrimaryTemplateSourceUrl: namespace.getPrimaryTemplateSourceUrl || function () { return ""; },
    setTemplateSourceUrlInputNames: namespace.setTemplateSourceUrlInputNames || function () {},
    refreshTemplateSourceUrlRowMeta: namespace.refreshTemplateSourceUrlRowMeta || function () {},
    validateTemplateSourceUrls: namespace.validateTemplateSourceUrls || function () { return []; },
    ensureTemplateSourceUrlRows: namespace.ensureTemplateSourceUrlRows || function () {},
    addTemplateSourceUrlRow: namespace.addTemplateSourceUrlRow || function () {},
    normalizeTemplateSourceUrls: namespace.normalizeTemplateSourceUrls || function () { return []; },
    isValidHttpUrl: namespace.isValidHttpUrl || function () { return false; },
    getTemplateStepsListEl: namespace.getTemplateStepsListEl || function () { return null; },
    parseTemplateStepExecutionLogFromRow: namespace.parseTemplateStepExecutionLogFromRow || function () { return ""; },
    formatTemplateStepLatestExecutionLog:
      namespace.formatTemplateStepLatestExecutionLog || function () { return ""; },
    getTemplateStepDragAfterRow: namespace.getTemplateStepDragAfterRow || function () { return null; },
    ensureTemplateStepDnDBindings: namespace.ensureTemplateStepDnDBindings || function () {},
    emitTemplateStepsChanged: namespace.emitTemplateStepsChanged || function () {},
    getTemplateMode: namespace.getTemplateMode || function () { return "manual"; },
    getTemplateModeConfig: namespace.getTemplateModeConfig || function () { return {}; },
    syncTemplatePageHeader: namespace.syncTemplatePageHeader || function () {},
    isRequiredTemplateStepAction: namespace.isRequiredTemplateStepAction || function () { return false; },
    actionToWorkflowBlockKey: namespace.actionToWorkflowBlockKey || function () { return ""; },
    nextAvailableTemplateStepAction: namespace.nextAvailableTemplateStepAction || function () { return ""; },
  });

  window.DashboardIndexStateWorkflow = namespace;
  window.DashboardIndexState = Object.assign(window.DashboardIndexState || {}, namespace);
})();
