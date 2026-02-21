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

  const linkForm = document.getElementById("workspace-link-form");
  const linkLabelInput = document.getElementById("workspace-link-label");
  const linkUrlInput = document.getElementById("workspace-link-url");
  const linkPurposeInput = document.getElementById("workspace-link-purpose");
  const clearLinksButton = document.getElementById("workspace-clear-links");
  const MAX_LINKS = 100;

  function normalizeText(value, maxLength = 200) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
  }

  function normalizeLinkNoteText(value) {
    return String(value ?? "").slice(0, 4000);
  }

  function normalizeUrl(value) {
    const raw = String(value || "").trim();
    if (!raw) return null;
    try {
      const parsed = new URL(raw);
      if (!["http:", "https:"].includes(parsed.protocol)) return null;
      return parsed.toString();
    } catch {
      return null;
    }
  }

  function getCommon() {
    return window.DashboardCommon || {};
  }

  function getLinksNamespace() {
    return (window.DashboardWorkspace && window.DashboardWorkspace.links) || namespace;
  }

  function getStateNamespace() {
    return (
      (window.DashboardWorkspace && window.DashboardWorkspace.state) ||
      window.DashboardWorkspaceState ||
      {}
    );
  }

  function callNs(ns, name, args, fallback) {
    const fn = ns && ns[name];
    if (typeof fn === "function") return fn.apply(ns, args || []);
    if (typeof fallback === "function") return fallback();
    return fallback;
  }

  function showToast(message, type) {
    const common = getCommon();
    if (typeof common.showToast === "function") {
      common.showToast(message, type);
    }
  }

  function initializeLinks() {
    const linksNs = getLinksNamespace();
    const stateNs = getStateNamespace();

    const readCustomLinks = () => callNs(linksNs, "readCustomLinks", [], () => []);
    const readPinnedLinkGroups = () => callNs(linksNs, "readPinnedLinkGroups", [], () => []);
    const renderLinkLists = (links, pinnedLinkGroups) =>
      callNs(linksNs, "renderLinkLists", [links, pinnedLinkGroups], () => {});
    const bindStaticCopyButtons = () => callNs(linksNs, "bindStaticCopyButtons", [], () => {});
    const bindLinkNoteEditors = () => callNs(linksNs, "bindLinkNoteEditors", [document], () => {});
    const bindLinkProfileEditors = () => callNs(linksNs, "bindLinkProfileEditors", [document], () => {});
    const bindWorkspaceMetadataToggle = () =>
      callNs(linksNs, "bindWorkspaceMetadataToggle", [document], () => {});
    const getAllPinnedLinksFromGroups = () =>
      callNs(linksNs, "getAllPinnedLinksFromGroups", [readPinnedLinkGroups()], () => []);
    const showToastConfirmDialog = (message, options = {}) => {
      const dialog = callNs(linksNs, "showToastConfirmDialog", [message, options], undefined);
      if (typeof dialog === "undefined" && typeof options.onConfirm === "function") {
        options.onConfirm();
      }
    };
    const saveCustomLinks = (links) => callNs(linksNs, "saveCustomLinks", [links], null);
    const saveWorkspaceState = (links, pinnedGroups) =>
      callNs(stateNs, "saveWorkspaceState", [links, pinnedGroups], null);
    const saveLinkNoteForKey = (key, text) => callNs(stateNs, "saveLinkNoteForKey", [key, text], false);
    const buildCustomPromptKey = (url) =>
      callNs(linksNs, "buildCustomPromptKey", [url], String(url || ""));
    const clearLinkUndoNotice = () => callNs(linksNs, "clearLinkUndoNotice", [], () => {});

    const links = readCustomLinks();
    const pinnedLinkGroups = readPinnedLinkGroups();
    renderLinkLists(links, pinnedLinkGroups);
    bindStaticCopyButtons();
    bindLinkNoteEditors();
    bindLinkProfileEditors();
    bindWorkspaceMetadataToggle();

    if (linkForm && linkLabelInput && linkUrlInput) {
      linkForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const url = normalizeUrl(linkUrlInput.value);
        if (!url) {
          showToast("Please enter a valid URL.", "error");
          linkUrlInput.focus();
          return;
        }
        const fallback = new URL(url).hostname;
        const label = normalizeText(linkLabelInput.value, 80) || fallback;
        const purpose = normalizeLinkNoteText(linkPurposeInput ? linkPurposeInput.value : "");

        const current = readCustomLinks();
        const currentPinned = getAllPinnedLinksFromGroups(readPinnedLinkGroups());
        const duplicate = [...current, ...currentPinned].some(
          (item) => String(item.url).toLowerCase() === String(url).toLowerCase()
        );

        if (duplicate) {
          showToast("The same URL is already registered.", "error");
          return;
        }

        const next = [{ label, url }, ...current].slice(0, MAX_LINKS);
        const saved = saveCustomLinks(next);
        if (!saved) {
          showToast("Failed to save link.", "error");
          return;
        }
        if (!saveLinkNoteForKey(buildCustomPromptKey(url), purpose)) {
          showToast("Failed to save link note.", "error");
        }

        clearLinkUndoNotice();
        renderLinkLists(next, readPinnedLinkGroups());
        linkForm.reset();
        if (linkPurposeInput) linkPurposeInput.value = "";
        linkLabelInput.focus();
        showToast("Link saved.", "success");
      });
    }

    if (clearLinksButton) {
      clearLinksButton.addEventListener("click", () => {
        const currentLinks = readCustomLinks();
        if (currentLinks.length <= 0) {
          showToast("There are no links to clear.", "error");
          return;
        }
        showToastConfirmDialog("Are you sure you want to clear all links?", {
          confirmText: "Clear",
          cancelText: "Cancel",
          type: "error",
          onConfirm: () => {
            const currentPinned = readPinnedLinkGroups();
            const saved = saveWorkspaceState([], currentPinned);
            if (!saved) {
              showToast("Failed to clear links.", "error");
              return;
            }
            clearLinkUndoNotice();
            renderLinkLists(saved.links, saved.pinned_link_groups);
            showToast("All links were cleared.", "success");
          },
        });
      });
    }
  }

  register({
    initializeLinks,
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
