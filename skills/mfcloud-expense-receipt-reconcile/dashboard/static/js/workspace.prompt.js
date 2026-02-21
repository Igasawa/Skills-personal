(function () {
  const workspacePrompt = window.DashboardWorkspacePrompt || {};
  window.DashboardWorkspacePrompt = workspacePrompt;
  window.DashboardWorkspace = window.DashboardWorkspace || {};
  window.DashboardWorkspace.prompt = workspacePrompt;

  window.DashboardWorkspacePrompt.optimizeActivePrompt = workspacePrompt.optimizeActivePrompt || null;
  window.DashboardWorkspacePrompt.getPromptTextForKey =
    window.DashboardWorkspacePrompt.getPromptTextForKey || null;
  window.DashboardWorkspacePrompt.initializePrompt =
    window.DashboardWorkspacePrompt.initializePrompt || null;
})();

