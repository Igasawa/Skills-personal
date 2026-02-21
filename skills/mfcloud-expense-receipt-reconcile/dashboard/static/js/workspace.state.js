(function () {
  const workspaceState = window.DashboardWorkspaceState || {};
  window.DashboardWorkspaceState = workspaceState;
  window.DashboardWorkspace = window.DashboardWorkspace || {};
  window.DashboardWorkspace.state = workspaceState;

  if (!window.DashboardWorkspaceState.getWorkspaceData) {
    window.DashboardWorkspaceState.getWorkspaceData = function () {
      return {
        links: Array.isArray(window.DashboardWorkspaceState.readCustomLinks)
          ? window.DashboardWorkspaceState.readCustomLinks()
          : [],
        pinnedGroups: Array.isArray(window.DashboardWorkspaceState.readPinnedLinkGroups)
          ? window.DashboardWorkspaceState.readPinnedLinkGroups()
          : [],
      };
    };
  }
})();

