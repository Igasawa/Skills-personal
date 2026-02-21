(function () {
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.sync) || {};
  const fallback = window.DashboardWorkspaceSync || {};
  const namespace = dashboard.sync || source || fallback || {};
  if (!dashboard.sync) {
    dashboard.sync = namespace;
  }

  Object.assign(namespace, fallback, source, dashboard.sync || {});

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  register({
    bootstrapWorkspaceState: namespace.bootstrapWorkspaceState || function () {},
    scheduleWorkspaceSync: namespace.scheduleWorkspaceSync || function () {},
    readPromptMap: namespace.readPromptMap || function () { return {}; },
    saveWorkspaceState: namespace.saveWorkspaceState || function () { return null; },
    bootstrap: namespace.bootstrap || function () {},
    pushWorkspaceStateToServer: namespace.pushWorkspaceStateToServer || function () { return Promise.resolve(false); },
    fetchWorkspaceStateFromServer: namespace.fetchWorkspaceStateFromServer || function () { return null; },
    collectLocalWorkspaceState: namespace.collectLocalWorkspaceState || function () { return {}; },
    schedule: namespace.scheduleWorkspaceSync || function () {},
  });

  namespace.schedule = namespace.scheduleWorkspaceSync;

  dashboard.sync = namespace;
  dashboard.core = Object.assign(dashboard.core || {}, {
    sync: namespace,
  });
  window.DashboardWorkspaceSync = namespace;
  window.DashboardWorkspace = dashboard;
})();
