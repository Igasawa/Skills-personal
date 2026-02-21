(function () {
  const PROMPT_KEY_MF_EXPENSE_REPORTS = "mf_expense_reports";
  const dashboard = window.DashboardWorkspace || {};
  const source = (dashboard.core && dashboard.core.prompt) || {};
  const fallback = window.DashboardWorkspacePrompt || {};
  const namespace = dashboard.prompt || source || fallback || {};
  if (!dashboard.prompt) {
    dashboard.prompt = namespace;
  }

  Object.assign(namespace, fallback, source, dashboard.prompt || {});
  const stateNamespace = (dashboard.core && dashboard.core.state) || dashboard.state || {};
  const linksNamespace = (dashboard.core && dashboard.core.links) || dashboard.links || {};
  const renderNamespace = (dashboard.core && dashboard.core.render) || dashboard.render || {};
  const promptEditor = document.getElementById("workspace-prompt-editor");
  const promptStatus = document.getElementById("workspace-prompt-status");
  const promptCount = document.getElementById("workspace-prompt-count");
  const savePromptButton = document.getElementById("workspace-save-prompt");
  const optimizePromptButton = document.getElementById("workspace-optimize-prompt");
  const copyHandoffButton = document.getElementById("workspace-copy-handoff");
  const promptDiffCancelButton = document.getElementById("workspace-prompt-diff-cancel");
  const promptDiffBackdrop = document.getElementById("workspace-prompt-diff-backdrop");
  const promptDiffApplyButton = document.getElementById("workspace-prompt-diff-apply");
  const common = window.DashboardCommon || {};
  const showToast = common.showToast || (() => {});

  const register = function (updates) {
    Object.keys(updates || {}).forEach((key) => {
      if (typeof updates[key] === "undefined") return;
      namespace[key] = updates[key];
    });
  };

  function callNs(ns, name, args, fallback) {
    const fn = ns && ns[name];
    if (typeof fn === "function") return fn.apply(ns, args || []);
    return typeof fallback === "function" ? fallback() : fallback;
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function resolveStateFunction(name, fallback) {
    return function () {
      const fallbackValue = typeof fallback === "function" ? fallback : function () {};
      return callNs(stateNamespace, name, Array.from(arguments), fallbackValue);
    };
  }

  function resolvePromptFunction(name, fallback) {
    return function () {
      const fallbackValue = typeof fallback === "function" ? fallback : function () {};
      return callNs(namespace, name, Array.from(arguments), fallbackValue);
    };
  }

  function resolveLinksFunction(name, fallback) {
    return function () {
      const fallbackValue = typeof fallback === "function" ? fallback : function () {};
      return callNs(linksNamespace, name, Array.from(arguments), fallbackValue);
    };
  }

  function resolveRenderFunction(name, fallback) {
    return function () {
      const fallbackValue = typeof fallback === "function" ? fallback : function () {};
      return callNs(renderNamespace, name, Array.from(arguments), fallbackValue);
    };
  }

  function initializePrompt() {
    if (!promptEditor) return;

    const readActivePromptKey = resolveStateFunction("readActivePromptKey", function () { return ""; });
    const setActivePrompt = resolvePromptFunction("setActivePrompt", function () {});
    const getActivePromptState = resolvePromptFunction("getActivePromptState", function () {
      const key = readActivePromptKey() || PROMPT_KEY_MF_EXPENSE_REPORTS;
      return { key, context: {} };
    });
    const getPromptTextForKey = resolvePromptFunction("getPromptTextForKey", function () { return ""; });
    const updatePromptMeta = resolvePromptFunction("updatePromptMeta", function () {});
    const renderPromptFronts = resolvePromptFunction("renderPromptFronts", function () {});
    const setPromptOptimizeButtonLoading = resolveRenderFunction("setPromptOptimizeButtonLoading", function () {});
    const setPromptDiffVisibility = resolveRenderFunction("setPromptDiffVisibility", function () {});
    const savePromptTextForKey = resolveStateFunction("savePromptTextForKey", function () { return false; });
    const optimizeActivePrompt = resolvePromptFunction("optimizeActivePrompt", function () {});
    const copyHandoffSetForKey = resolvePromptFunction("copyHandoffSetForKey", function () {});
    const getPromptOptimizePreview = resolvePromptFunction("getPromptOptimizePreview", function () { return null; });
    const closePromptOptimizePreview = resolvePromptFunction("closePromptOptimizePreview", function () {});
    const applyPromptOptimizePreview = resolvePromptFunction("applyPromptOptimizePreview", function () { return false; });
    const normalizePromptOptimizeList = resolvePromptFunction(
      "normalizePromptOptimizeList",
      function () { return []; }
    );
    const showToastConfirmDialog = resolveLinksFunction("showToastConfirmDialog", function (message, options) {
      showToast(String(message || ""), "warning");
      if (options && typeof options.onConfirm === "function") {
        options.onConfirm();
      }
    });
    const getCurrentPromptState = () => {
      const state = getActivePromptState();
      const key = String(state && state.key ? state.key : readActivePromptKey() || PROMPT_KEY_MF_EXPENSE_REPORTS);
      const context = isObject(state && state.context) ? state.context : {};
      return { key, context };
    };

    const initialKey = readActivePromptKey() || PROMPT_KEY_MF_EXPENSE_REPORTS;
    setActivePrompt(initialKey);

    const initialState = getCurrentPromptState();
    const initialText = getPromptTextForKey(initialState.key, initialState.context);
    promptEditor.value = initialText;
    updatePromptMeta(initialText, "自動保存待機中。");
    renderPromptFronts();
    setPromptOptimizeButtonLoading(false);
    setPromptDiffVisibility(false);

    let saveTimer = null;
    promptEditor.addEventListener("input", () => {
      updatePromptMeta(promptEditor.value, "編集中...");
      if (saveTimer) window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(() => {
        const current = getCurrentPromptState();
        const ok = savePromptTextForKey(current.key, promptEditor.value);
        if (ok) updatePromptMeta(promptEditor.value, "保存しました。");
        else updatePromptMeta(promptEditor.value, "保存できませんでした（ストレージ利用不可）。");
      }, 250);
    });

    if (savePromptButton) {
      savePromptButton.addEventListener("click", () => {
        const text = promptEditor.value || "";
        const current = getCurrentPromptState();
        const ok = savePromptTextForKey(current.key, text);
        if (ok) {
          updatePromptMeta(text, "登録しました。");
          showToast("プロンプトを登録しました。", "success");
          return;
        }
        updatePromptMeta(text, "保存できませんでした（ストレージ利用不可）。");
        showToast("元に戻せませんでした。", "error");
      });
    }

    if (optimizePromptButton) {
      optimizePromptButton.addEventListener("click", () => {
        void optimizeActivePrompt();
      });
    }

    if (copyHandoffButton) {
      copyHandoffButton.addEventListener("click", () => {
        const current = getCurrentPromptState();
        void copyHandoffSetForKey(current.key, current.context);
      });
    }

    if (promptDiffCancelButton) {
      promptDiffCancelButton.addEventListener("click", () => {
        closePromptOptimizePreview();
      });
    }

    if (promptDiffBackdrop) {
      promptDiffBackdrop.addEventListener("click", () => {
        closePromptOptimizePreview();
      });
    }

    if (promptDiffApplyButton) {
      promptDiffApplyButton.addEventListener("click", () => {
        const preview = getPromptOptimizePreview();
        if (!isObject(preview)) return;
        const needsConfirmation = normalizePromptOptimizeList(preview.needsConfirmation);
        if (needsConfirmation.length > 0) {
          showToastConfirmDialog("確認項目があります。最適化結果を適用しますか？", {
            confirmText: "適用する",
            cancelText: "キャンセル",
            type: "error",
            onConfirm: () => {
              applyPromptOptimizePreview();
            },
          });
          return;
        }
        applyPromptOptimizePreview();
      });
    }
  }

  register({
    initializePrompt,
    activatePromptEditorForKey: namespace.activatePromptEditorForKey || function () {},
    optimizeActivePrompt: namespace.optimizeActivePrompt || function () {},
    copyHandoffSetForKey: namespace.copyHandoffSetForKey || function () {},
    resolvePromptContextFromButton: namespace.resolvePromptContextFromButton || function () { return {}; },
    resolvePromptContextFromFront: namespace.resolvePromptContextFromFront || function () { return {}; },
    renderPromptFronts: namespace.renderPromptFronts || function () {},
    setActivePrompt: namespace.setActivePrompt || function () {},
    getPromptMapCached: namespace.getPromptMapCached || function () { return {}; },
    closePromptOptimizePreview: namespace.closePromptOptimizePreview || function () {},
    getPromptTextForKey: namespace.getPromptTextForKey || function () { return ""; },
    sendPromptForKey: namespace.sendPromptForKey || function () {},
    copyToClipboard: namespace.copyToClipboard || function () {},
    showPromptUndoNotice: namespace.showPromptUndoNotice || function () {},
    applyPromptOptimizePreview: namespace.applyPromptOptimizePreview || function () { return false; },
    requestPromptOptimization: namespace.requestPromptOptimization || function () { return Promise.resolve(null); },
    setPromptOptimizeButtonLoading: namespace.setPromptOptimizeButtonLoading || function () {},
    updatePromptMeta: namespace.updatePromptMeta || function () {},
    buildDefaultPromptForKey: namespace.buildDefaultPromptForKey || function () { return ""; },
    hasStoredPromptForKey: namespace.hasStoredPromptForKey || function () { return false; },
    resolvePromptLabel: namespace.resolvePromptLabel || function () { return "-"; },
    resolvePromptUrl: namespace.resolvePromptUrl || function () { return ""; },
    normalizePromptOptimizeList: namespace.normalizePromptOptimizeList || function () { return []; },
    getActivePromptState: namespace.getActivePromptState || function () {
      return {
        key: namespace.activePromptKey || PROMPT_KEY_MF_EXPENSE_REPORTS,
        context: namespace.activePromptContext || {},
      };
    },
    getActivePromptKey: namespace.getActivePromptKey || function () {
      return namespace.activePromptKey || PROMPT_KEY_MF_EXPENSE_REPORTS;
    },
    getActivePromptContext: namespace.getActivePromptContext || function () {
      return namespace.activePromptContext || {};
    },
    activePromptKey: namespace.activePromptKey || PROMPT_KEY_MF_EXPENSE_REPORTS,
    activePromptContext: namespace.activePromptContext || {},
  });

  dashboard.prompt = namespace;
  dashboard.core = Object.assign(dashboard.core || {}, {
    prompt: namespace,
  });
  window.DashboardWorkspacePrompt = namespace;
  window.DashboardWorkspace = dashboard;
})();
