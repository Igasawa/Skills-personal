(function () {
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.sync) || {};
  const fallback = window.DashboardWorkspaceSync || {};
  const namespace = dashboard.sync || source || fallback || {};
  const linksNamespace = dashboard.links || {};
  const promptNamespace = dashboard.prompt || {};
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

  async function bootstrapWorkspace() {
    const bootstrapState = namespace.bootstrapWorkspaceState || function () {};
    const initializeLinks = linksNamespace.initializeLinks || function () {};
    const initializePrompt = promptNamespace.initializePrompt || function () {};
    await Promise.resolve().then(() => bootstrapState());
    initializeLinks();
    initializePrompt();
  }

  register({
    bootstrapWorkspaceState: namespace.bootstrapWorkspaceState || function () {},
    scheduleWorkspaceSync: namespace.scheduleWorkspaceSync || function () {},
    readPromptMap: namespace.readPromptMap || function () { return {}; },
    saveWorkspaceState: namespace.saveWorkspaceState || function () { return null; },
    bootstrap: bootstrapWorkspace,
    pushWorkspaceStateToServer: namespace.pushWorkspaceStateToServer || function () { return Promise.resolve(false); },
    fetchWorkspaceStateFromServer: namespace.fetchWorkspaceStateFromServer || function () { return null; },
    collectLocalWorkspaceState: namespace.collectLocalWorkspaceState || function () { return {}; },
    schedule: namespace.scheduleWorkspaceSync || function () {},
  });

  namespace.schedule = namespace.scheduleWorkspaceSync;

  dashboard.sync = namespace;
  dashboard.core = Object.assign(dashboard.core || {}, {
    sync: namespace,
    bootstrap: bootstrapWorkspace,
  });
  window.DashboardWorkspaceSync = namespace;
  dashboard.bootstrap = dashboard.core.bootstrap || bootstrapWorkspace;
  if (typeof dashboard.bootstrap !== "function") {
    dashboard.bootstrap = bootstrapWorkspace;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      void dashboard.bootstrap();
    });
  } else {
    void dashboard.bootstrap();
  }

  window.DashboardWorkspace = dashboard;
})();
