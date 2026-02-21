(function () {
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.render) || {};
  const fallback = window.DashboardWorkspaceRender || {};
  const namespace = dashboard.render || source || fallback || {};
  if (!dashboard.render) {
    dashboard.render = namespace;
  }

  Object.assign(namespace, fallback, source, dashboard.render || {});
  const optimizePromptButton = document.getElementById("workspace-optimize-prompt");
  const promptDiffBackdrop = document.getElementById("workspace-prompt-diff-backdrop");
  const promptDiffModal = document.getElementById("workspace-prompt-diff-modal");
  const promptStatus = document.getElementById("workspace-prompt-status");
  const promptCount = document.getElementById("workspace-prompt-count");
  const promptDiffEscapeListenerBound = { value: false };
  const promptCountNode = promptCount;
  const promptStatusNode = promptStatus;
  const promptDiffBackdropNode = promptDiffBackdrop;
  const promptDiffModalNode = promptDiffModal;
  const optimizePromptButtonNode = optimizePromptButton;
  const getPromptOptimizeList = () => {
    const fn = namespace.normalizePromptOptimizeList;
    if (typeof fn === "function") return fn;
    const fallback = function () { return []; };
    return fallback;
  };

  function setPromptOptimizeButtonLoading(loading) {
    if (!optimizePromptButtonNode) return;
    optimizePromptButtonNode.disabled = Boolean(loading);
    optimizePromptButtonNode.textContent = loading ? "最適化中..." : "AIで最適化";
  }

  function renderPromptDiffList(container, items) {
    if (!(container instanceof HTMLElement)) return;
    container.innerHTML = "";
    getPromptOptimizeList().forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      container.appendChild(li);
    });
  }

  function handlePromptDiffEscape(event) {
    if (!event || event.key !== "Escape") return;
    if (typeof namespace.closePromptOptimizePreview === "function") {
      namespace.closePromptOptimizePreview();
      return;
    }
  }

  function setPromptDiffVisibility(visible) {
    if (promptDiffBackdropNode) {
      promptDiffBackdropNode.hidden = !visible;
      promptDiffBackdropNode.classList.toggle("hidden", !visible);
    }
    if (promptDiffModalNode) {
      promptDiffModalNode.hidden = !visible;
      promptDiffModalNode.classList.toggle("hidden", !visible);
    }
    if (visible && !promptDiffEscapeListenerBound.value) {
      document.addEventListener("keydown", handlePromptDiffEscape, true);
      promptDiffEscapeListenerBound.value = true;
      return;
    }
    if (!visible && promptDiffEscapeListenerBound.value) {
      document.removeEventListener("keydown", handlePromptDiffEscape, true);
      promptDiffEscapeListenerBound.value = false;
    }
  }

  function updatePromptMeta(text, statusText) {
    if (promptCountNode) {
      const length = String(text || "").length;
      promptCountNode.textContent = `${length} 文字`;
    }
    if (promptStatusNode && statusText) {
      promptStatusNode.textContent = statusText;
    }
  }

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

  register({
    setPromptOptimizeButtonLoading,
    renderPromptDiffList,
    setPromptDiffVisibility,
    updatePromptMeta,
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
