(function () {
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.prompt) || {};
  const fallback = window.DashboardWorkspacePrompt || {};
  const namespace = Object.assign({}, fallback, source, dashboard.prompt || {});

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  register({
    initializePrompt: namespace.initializePrompt || function () {},
    activatePromptEditorForKey: namespace.activatePromptEditorForKey || function () {},
    optimizeActivePrompt: namespace.optimizeActivePrompt || function () {},
    copyHandoffSetForKey: namespace.copyHandoffSetForKey || function () {},
    resolvePromptContextFromButton: namespace.resolvePromptContextFromButton || function () { return {}; },
    resolvePromptContextFromFront: namespace.resolvePromptContextFromFront || function () { return {}; },
    renderPromptFronts: namespace.renderPromptFronts || function () {},
    setActivePrompt: namespace.setActivePrompt || function () {},
    getPromptMapCached: namespace.getPromptMapCached || function () { return {}; },
    closePromptOptimizePreview: namespace.closePromptOptimizePreview || function () {},
    getPromptTextForKey: namespace.getPromptTextForKey || function () { return ""; },
    sendPromptForKey: namespace.sendPromptForKey || function () {},
    copyToClipboard: namespace.copyToClipboard || function () {},
    showPromptUndoNotice: namespace.showPromptUndoNotice || function () {},
    applyPromptOptimizePreview: namespace.applyPromptOptimizePreview || function () { return false; },
    requestPromptOptimization: namespace.requestPromptOptimization || function () { return Promise.resolve(null); },
    setPromptOptimizeButtonLoading: namespace.setPromptOptimizeButtonLoading || function () {},
    updatePromptMeta: namespace.updatePromptMeta || function () {},
    buildDefaultPromptForKey: namespace.buildDefaultPromptForKey || function () { return ""; },
    hasStoredPromptForKey: namespace.hasStoredPromptForKey || function () { return false; },
    resolvePromptLabel: namespace.resolvePromptLabel || function () { return "-"; },
    resolvePromptUrl: namespace.resolvePromptUrl || function () { return ""; },
    normalizePromptOptimizeList: namespace.normalizePromptOptimizeList || function () { return []; },
    getPromptMapCached: namespace.getPromptMapCached || function () { return {}; },
  });

  dashboard.prompt = namespace;
  dashboard.core = Object.assign(dashboard.core || {}, {
    prompt: namespace,
  });
  window.DashboardWorkspacePrompt = namespace;
  window.DashboardWorkspace = dashboard;
})();
