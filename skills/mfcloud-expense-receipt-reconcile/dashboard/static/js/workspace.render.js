(function () {
  const workspaceRender = window.DashboardWorkspaceRender || {};
  window.DashboardWorkspaceRender = workspaceRender;
  window.DashboardWorkspace = window.DashboardWorkspace || {};
  window.DashboardWorkspace.render = workspaceRender;

  if (typeof workspaceRender.renderPromptFrontElement === "function") {
    window.DashboardWorkspaceRender.promptFrontElementRenderer = workspaceRender.renderPromptFrontElement;
  }
  if (typeof workspaceRender.renderLinkLists === "function") {
    window.DashboardWorkspaceRender.linkListRenderer = workspaceRender.renderLinkLists;
  }
})();

