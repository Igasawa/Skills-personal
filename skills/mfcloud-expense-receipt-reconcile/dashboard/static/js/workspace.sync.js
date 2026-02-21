(function () {
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.sync) || {};
  const fallback = window.DashboardWorkspaceSync || {};
  const namespace = dashboard.sync || source || fallback || {};
  const stateNamespace = dashboard.state || {};
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

  const resolveStateFn = function (name, fallback) {
    const candidate = stateNamespace[name];
    if (typeof candidate === "function") return candidate;
    if (typeof namespace[name] === "function") return namespace[name];
    return fallback;
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
    bootstrapWorkspaceState: resolveStateFn("bootstrapWorkspaceState", function () {}),
    scheduleWorkspaceSync: resolveStateFn("scheduleWorkspaceSync", function () {}),
    readPromptMap: resolveStateFn("readPromptMap", function () { return {}; }),
    saveWorkspaceState: resolveStateFn("saveWorkspaceState", function () { return null; }),
    bootstrap: bootstrapWorkspace,
    pushWorkspaceStateToServer: resolveStateFn("pushWorkspaceStateToServer", function () { return Promise.resolve(false); }),
    fetchWorkspaceStateFromServer: resolveStateFn("fetchWorkspaceStateFromServer", function () { return null; }),
    collectLocalWorkspaceState: resolveStateFn("collectLocalWorkspaceState", function () { return {}; }),
    schedule: resolveStateFn("scheduleWorkspaceSync", function () {}),
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
