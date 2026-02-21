(function () {
  const dashboard = window.DashboardWorkspace || {};
  const core = dashboard.core || {};
  const source = core.state || {};
  const fallback = window.DashboardWorkspaceState || {};
  const namespace = dashboard.state || source || fallback || {};
  if (!dashboard.state) {
    dashboard.state = namespace;
  }

  Object.assign(namespace, fallback, source, dashboard.state || {});
  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  const resolveFunction = function (name, fallback) {
    const value = namespace[name];
    return typeof value === "function" ? value : fallback;
  };

  register({
    bootstrapWorkspaceState: resolveFunction("bootstrapWorkspaceState", function () {}),
    bootstrap: resolveFunction(
      "bootstrap",
      resolveFunction("bootstrapWorkspaceState", function () {})
    ),
    readRawCustomLinks: resolveFunction("readRawCustomLinks", function () { return []; }),
    readCustomLinks: resolveFunction("readCustomLinks", function () { return []; }),
    readPromptMap: resolveFunction("readPromptMap", function () { return {}; }),
    readActivePromptKey: resolveFunction("readActivePromptKey", function () { return ""; }),
    savePromptMap: resolveFunction("savePromptMap", function () { return false; }),
    savePromptTextForKey: resolveFunction("savePromptTextForKey", function () { return false; }),
    getPromptTextForKey: resolveFunction("getPromptTextForKey", function () { return ""; }),
    storeActivePromptKey: resolveFunction("storeActivePromptKey", function () {}),
    saveWorkspaceState: resolveFunction("saveWorkspaceState", function () { return null; }),
    scheduleWorkspaceSync: resolveFunction("scheduleWorkspaceSync", function () {}),
    collectLocalWorkspaceState: resolveFunction("collectLocalWorkspaceState", function () { return {}; }),
    fetchWorkspaceStateFromServer: resolveFunction("fetchWorkspaceStateFromServer", function () { return null; }),
    pushWorkspaceStateToServer: resolveFunction("pushWorkspaceStateToServer", function () { return Promise.resolve(false); }),
    applyWorkspaceStateToLocalStorage: resolveFunction("applyWorkspaceStateToLocalStorage", function () {}),
    hasMeaningfulWorkspaceState: resolveFunction("hasMeaningfulWorkspaceState", function () { return false; }),
    getLinkNoteForKey: resolveFunction("getLinkNoteForKey", function () { return ""; }),
    getLinkProfileForKey: resolveFunction("getLinkProfileForKey", function () { return {}; }),
    saveLinkNoteForKey: resolveFunction("saveLinkNoteForKey", function () { return false; }),
    saveLinkProfileForKey: resolveFunction("saveLinkProfileForKey", function () { return false; }),
    readLinkNoteMap: resolveFunction("readLinkNoteMap", function () { return {}; }),
    readLinkProfileMap: resolveFunction("readLinkProfileMap", function () { return {}; }),
  });

  namespace.schedule = namespace.scheduleWorkspaceSync;

  if (!namespace.getWorkspaceData) {
    namespace.getWorkspaceData = function () {
      return {
        links: Array.isArray(namespace.readCustomLinks()) ? namespace.readCustomLinks() : [],
        pinnedGroups: Array.isArray(namespace.readPinnedLinkGroups ? namespace.readPinnedLinkGroups() : [])
          ? namespace.readPinnedLinkGroups()
          : [],
      };
    };
  }

  dashboard.state = namespace;
  dashboard.core = Object.assign(dashboard.core || {}, {
    state: namespace,
  });
  window.DashboardWorkspaceState = namespace;
  window.DashboardWorkspace = dashboard;
  window.DashboardWorkspaceSync = Object.assign(window.DashboardWorkspaceSync || {}, {
    bootstrapWorkspaceState: namespace.bootstrapWorkspaceState,
    scheduleWorkspaceSync: namespace.scheduleWorkspaceSync,
    bootstrap: namespace.bootstrap,
    schedule: namespace.scheduleWorkspaceSync,
  });
  window.DashboardWorkspaceState.getWorkspaceData = namespace.getWorkspaceData;
  window.DashboardWorkspaceSync.getWorkspaceData = namespace.getWorkspaceData;
})();
