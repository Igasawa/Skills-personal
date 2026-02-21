(function () {
  const workspaceLinks = window.DashboardWorkspaceLinks || {};
  window.DashboardWorkspaceLinks = workspaceLinks;
  window.DashboardWorkspace = window.DashboardWorkspace || {};
  window.DashboardWorkspace.links = workspaceLinks;

  window.DashboardWorkspaceLinks.render = window.DashboardWorkspaceLinks.render || {};
  if (!Object.prototype.hasOwnProperty.call(window.DashboardWorkspaceLinks.render, "links")) {
    window.DashboardWorkspaceLinks.render.links = window.DashboardWorkspaceLinks.renderLinkLists
      || window.DashboardWorkspaceLinks.renderLinks
      || null;
  }
})();

