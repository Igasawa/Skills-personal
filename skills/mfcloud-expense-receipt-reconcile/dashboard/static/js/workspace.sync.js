(function () {
  const workspaceSync = window.DashboardWorkspaceSync || {};
  window.DashboardWorkspaceSync = workspaceSync;
  window.DashboardWorkspace = window.DashboardWorkspace || {};
  window.DashboardWorkspace.sync = workspaceSync;

  window.DashboardWorkspaceSync.bootstrap = workspaceSync.bootstrap || function () {};
  window.DashboardWorkspaceSync.schedule = workspaceSync.scheduleWorkspaceSync || function () {};
})();

