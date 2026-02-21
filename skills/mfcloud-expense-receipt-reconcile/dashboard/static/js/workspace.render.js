(function () {
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.render) || {};
  const fallback = window.DashboardWorkspaceRender || {};
  const namespace = dashboard.render || source || fallback || {};
  if (!dashboard.render) {
    dashboard.render = namespace;
  }

  Object.assign(namespace, fallback, source, dashboard.render || {});

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  register({
    renderPromptFrontElement: namespace.renderPromptFrontElement || function () {},
    renderPromptFronts: namespace.renderPromptFronts || function () {},
    renderLinkLists: namespace.renderLinkLists || function () {},
    renderPinnedLinkGroups: namespace.renderPinnedLinkGroups || function () {},
    renderPinnedLinks: namespace.renderPinnedLinks || function () {},
    updatePromptMeta: namespace.updatePromptMeta || function () {},
    setPromptOptimizeButtonLoading: namespace.setPromptOptimizeButtonLoading || function () {},
    setPromptDiffVisibility: namespace.setPromptDiffVisibility || function () {},
    renderPromptDiffList: namespace.renderPromptDiffList || function () {},
    createLinkNode: namespace.createLinkNode || function () {},
    createPinnedGroupNode: namespace.createPinnedGroupNode || function () {},
    renderCustomLinks: namespace.renderCustomLinks || function () {},
    openPromptOptimizePreview: namespace.openPromptOptimizePreview || function () {},
    buildPromptPreview: namespace.buildPromptPreview || function () { return ""; },
    renderProfileStatusForKey: namespace.renderProfileStatusForKey || function () {},
    createAction: namespace.createAction || function () {},
  });

  namespace.promptFrontElementRenderer = namespace.renderPromptFrontElement;
  namespace.linkListRenderer = namespace.renderLinkLists;

  dashboard.render = namespace;
  dashboard.core = Object.assign(dashboard.core || {}, {
    render: namespace,
  });
  window.DashboardWorkspaceRender = namespace;
  window.DashboardWorkspace = dashboard;
})();
