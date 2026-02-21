(function () {
  const dashboard = window.DashboardWorkspace || {};
  const core = dashboard.core || {};
  const source = core.sync || {};
  const fallback = window.DashboardWorkspaceSync || {};
  const namespace = dashboard.sync || source || fallback || {};
  const stateNamespace = core.state || dashboard.state || {};
  const linksNamespace = core.links || dashboard.links || {};
  const promptNamespace = core.prompt || dashboard.prompt || {};
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
    const bootstrapState = resolveStateFn("bootstrapWorkspaceState", function () {});
    const initializeLinks = linksNamespace.initializeLinks || function () {};
    const initializePrompt = promptNamespace.initializePrompt || function () {};
    const runStage = async (name, action) => {
      try {
        await Promise.resolve().then(() => action());
      } catch (_error) {
        if (typeof console !== "undefined" && console && typeof console.error === "function") {
          console.error(`Failed to ${name} workspace initialization.`, _error);
        }
      }
    };
    await runStage("bootstrap workspace state", () => bootstrapState());
    await runStage("initialize workspace links", () => initializeLinks());
    await runStage("initialize workspace prompt", () => initializePrompt());
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
  dashboard.bootstrap = bootstrapWorkspace;
  dashboard.core = Object.assign(dashboard.core || {}, {
    sync: namespace,
    bootstrap: bootstrapWorkspace,
  });
  window.DashboardWorkspaceSync = namespace;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      void dashboard.bootstrap();
    });
  } else {
    void dashboard.bootstrap();
  }

  window.DashboardWorkspace = dashboard;
})();
