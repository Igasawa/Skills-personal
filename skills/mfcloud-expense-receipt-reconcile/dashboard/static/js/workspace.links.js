(function () {
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.links) || {};
  const fallback = window.DashboardWorkspaceLinks || {};
  const namespace = dashboard.links || source || fallback || {};
  if (!dashboard.links) {
    dashboard.links = namespace;
  }

  Object.assign(namespace, fallback, source, dashboard.links || {});

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  register({
    initializeLinks: namespace.initializeLinks || function () {},
    renderLinkLists: namespace.renderLinkLists || function () {},
    renderPinnedLinkGroups: namespace.renderPinnedLinkGroups || function () {},
    readPinnedLinkGroups: namespace.readPinnedLinkGroups || function () { return []; },
    readPinnedLinksAll: namespace.readPinnedLinksAll || function () { return []; },
    saveCustomLinks: namespace.saveCustomLinks || function () { return null; },
    savePinnedLinkGroups: namespace.savePinnedLinkGroups || function () { return null; },
    renderPinnedLinks: namespace.renderPinnedLinks || function () {},
    clearLinkUndoNotice: namespace.clearLinkUndoNotice || function () {},
    clearToast: namespace.clearToast || function () {},
    showToastConfirmDialog: namespace.showToastConfirmDialog || function () { return false; },
    getAllPinnedLinksFromGroups: namespace.getAllPinnedLinksFromGroups || function () { return []; },
    buildCustomPromptKey: namespace.buildCustomPromptKey || function () { return ""; },
    readCustomLinks: namespace.readCustomLinks || function () { return []; },
    readPinnedLinksFromGroup: namespace.readPinnedLinksFromGroup || function () { return []; },
    readRawCustomLinks: namespace.readRawCustomLinks || function () { return []; },
    getPinnedGroupIndexById: namespace.getPinnedGroupIndexById || function () { return -1; },
    readPinnedLinks: namespace.readPinnedLinks || function () { return []; },
    createPinnedGroup: namespace.createPinnedGroup || function () { return null; },
    savePinnedLinksToGroup: namespace.savePinnedLinksToGroup || function () {},
    promoteCustomLinkToGroup: namespace.promoteCustomLinkToGroup || function () {},
    demotePinnedLinkByUrl: namespace.demotePinnedLinkByUrl || function () { return false; },
    demoteGroupLink: namespace.demoteGroupLink || function () { return false; },
    bindStaticCopyButtons: namespace.bindStaticCopyButtons || function () {},
    bindCustomLinkDragAndDrop: namespace.bindCustomLinkDragAndDrop || function () {},
    bindLinkListDragAndDrop: namespace.bindLinkListDragAndDrop || function () {},
    bindLinkNoteEditors: namespace.bindLinkNoteEditors || function () {},
    bindWorkspaceMetadataToggle: namespace.bindWorkspaceMetadataToggle || function () {},
    bindLinkProfileEditors: namespace.bindLinkProfileEditors || function () {},
    renderCustomLinks: namespace.renderCustomLinks || function () {},
    renderPromptFronts: namespace.renderPromptFronts || function () {},
    renderProfileStatusForKey: namespace.renderProfileStatusForKey || function () {},
    showLinkUndoNotice: namespace.showLinkUndoNotice || function () {},
    updatePinnedCountMeta: namespace.updatePinnedCountMeta || function () {},
    makePinnedGroup: namespace.makePinnedGroup || function () { return {}; },
    normalizePinnedLinkGroups: namespace.normalizePinnedLinkGroups || function () { return []; },
    normalizeLinkPools: namespace.normalizeLinkPools || function () { return { links: [], pinned_links: [] }; },
  });

  namespace.render = namespace.render || {};
  if (!namespace.render.links) {
    namespace.render.links = namespace.renderLinkLists || namespace.renderPinnedLinks || null;
  }

  dashboard.links = namespace;
  dashboard.core = Object.assign(dashboard.core || {}, {
    links: namespace,
  });
  window.DashboardWorkspaceLinks = namespace;
  window.DashboardWorkspace = dashboard;
})();
