(function () {
  const api = window.DashboardIndexApiTransport || window.DashboardIndexApi || {};
  const fallback = window.DashboardIndexApiCommands || {};
  const namespace = Object.assign({}, fallback, api);

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  register({
    buildPayload: namespace.buildPayload || function () { return {}; },
    resolveFormYearMonth: namespace.resolveFormYearMonth || function () { return {}; },
    buildTemplatePayload: namespace.buildTemplatePayload || function () { return {}; },
    buildWorkflowPagePayload: namespace.buildWorkflowPagePayload || function () { return {}; },
    createWorkflowPage: namespace.createWorkflowPage || function () {},
    editWorkflowPageSettings: namespace.editWorkflowPageSettings || function () {},
    archiveCurrentWorkflowPage: namespace.archiveCurrentWorkflowPage || function () {},
    showWorkflowPageStepEditorModal: namespace.showWorkflowPageStepEditorModal || function () {},
    saveWorkflowPageSteps: namespace.saveWorkflowPageSteps || function () {},
    editWorkflowPageSteps: namespace.editWorkflowPageSteps || function () {},
    rollbackWorkflowPageSteps: namespace.rollbackWorkflowPageSteps || function () {},
    saveWorkflowTemplate: namespace.saveWorkflowTemplate || function () {},
    startRun: namespace.startRun || function () {},
    prependArchiveHistoryRow: namespace.prependArchiveHistoryRow || function () {},
    runArchiveAction: namespace.runArchiveAction || function () {},
    importManualReceipts: namespace.importManualReceipts || function () {},
    openMfBulkInbox: namespace.openMfBulkInbox || function () {},
    runMfBulkUpload: namespace.runMfBulkUpload || function () {},
    openMfCsvInbox: namespace.openMfCsvInbox || function () {},
    runMfCsvImport: namespace.runMfCsvImport || function () {},
    runManualAction: namespace.runManualAction || function () {},
    providerLabel: namespace.providerLabel || function () { return ""; },
    openProviderInbox: namespace.openProviderInbox || function () {},
    openProviderSource: namespace.openProviderSource || function () {},
    importProviderReceipts: namespace.importProviderReceipts || function () {},
    printProviderReceipts: namespace.printProviderReceipts || function () {},
    runProviderAction: namespace.runProviderAction || function () {},
  });

  window.DashboardIndexApiCommands = namespace;
  window.DashboardIndexApi = Object.assign(window.DashboardIndexApi || {}, namespace);
})();
