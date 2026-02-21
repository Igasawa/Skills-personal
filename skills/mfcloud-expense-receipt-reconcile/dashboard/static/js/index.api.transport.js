(function () {
  const api = window.DashboardIndexApi || {};
  const fallback = window.DashboardIndexApiTransport || {};
  const namespace = Object.assign({}, fallback, api);

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  register({
    apiGetJson: namespace.apiGetJson || (async function () { return null; }),
    showError: namespace.showError || function () {},
    clearError: namespace.clearError || function () {},
    scheduleStepSync: namespace.scheduleStepSync || function () { return null; },
    fetchStatus: namespace.fetchStatus || (async function () { return null; }),
    isStepReflected: namespace.isStepReflected || function () { return false; },
    syncAfterRunCompletion: namespace.syncAfterRunCompletion || (async function () { return false; }),
    startLogPolling: namespace.startLogPolling || function () {},
    stopLogPolling: namespace.stopLogPolling || function () {},
    normalizeStatusForDot: namespace.normalizeStatusForDot || function () { return ""; },
    toYmText: namespace.toYmText || function () { return ""; },
    updateRunSummary: namespace.updateRunSummary || function () {},
    refreshLog: namespace.refreshLog || (async function () { return null; }),
  });

  window.DashboardIndexApiTransport = namespace;
  window.DashboardIndexApi = Object.assign(api, namespace);
})();
