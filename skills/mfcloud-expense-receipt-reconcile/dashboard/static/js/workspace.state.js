(function () {
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.state) || {};
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

  register({
    bootstrapWorkspaceState: namespace.bootstrapWorkspaceState || function () {},
    bootstrap: namespace.bootstrap || function () {},
    readRawCustomLinks: namespace.readRawCustomLinks || function () { return []; },
    readCustomLinks: namespace.readCustomLinks || function () { return []; },
    readPromptMap: namespace.readPromptMap || function () { return {}; },
    readActivePromptKey: namespace.readActivePromptKey || function () { return ""; },
    savePromptMap: namespace.savePromptMap || function () { return false; },
    savePromptTextForKey: namespace.savePromptTextForKey || function () { return false; },
    getPromptTextForKey: namespace.getPromptTextForKey || function () { return ""; },
    storeActivePromptKey: namespace.storeActivePromptKey || function () {},
    saveWorkspaceState: namespace.saveWorkspaceState || function () { return null; },
    scheduleWorkspaceSync: namespace.scheduleWorkspaceSync || function () {},
    collectLocalWorkspaceState: namespace.collectLocalWorkspaceState || function () { return {}; },
    fetchWorkspaceStateFromServer: namespace.fetchWorkspaceStateFromServer || function () { return null; },
    pushWorkspaceStateToServer: namespace.pushWorkspaceStateToServer || function () { return Promise.resolve(false); },
    applyWorkspaceStateToLocalStorage: namespace.applyWorkspaceStateToLocalStorage || function () {},
    hasMeaningfulWorkspaceState: namespace.hasMeaningfulWorkspaceState || function () { return false; },
    getLinkNoteForKey: namespace.getLinkNoteForKey || function () { return ""; },
    getLinkProfileForKey: namespace.getLinkProfileForKey || function () { return {}; },
    saveLinkNoteForKey: namespace.saveLinkNoteForKey || function () { return false; },
    saveLinkProfileForKey: namespace.saveLinkProfileForKey || function () { return false; },
    readLinkNoteMap: namespace.readLinkNoteMap || function () { return {}; },
    readLinkProfileMap: namespace.readLinkProfileMap || function () { return {}; },
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
