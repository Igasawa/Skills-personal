(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});

  const STORAGE_LINKS_KEY = "mf-dashboard-workspace-links-v1";
  const STORAGE_PROMPT_LEGACY_KEY = "mf-dashboard-workspace-prompt-v1";
  const STORAGE_PROMPTS_KEY = "mf-dashboard-workspace-prompts-v1";
  const STORAGE_PROMPT_ACTIVE_KEY = "mf-dashboard-workspace-prompt-active-v1";
  const MAX_LINKS = 100;
  const PROMPT_KEY_MF_EXPENSE_REPORTS = "mf_expense_reports";
  const LEGACY_DEFAULT_PROMPT = [
    "Goal:",
    "- Complete monthly MF expense submission safely and quickly.",
    "",
    "Month:",
    "- {month}",
    "",
    "Required URL:",
    "- https://expense.moneyforward.com/expense_reports",
    "",
    "Do next:",
    "1. Review current status and pending tasks.",
    "2. Import missing receipts and apply exclusions only when needed.",
    "3. Run reconciliation and summarize the result.",
    "",
    "Output format:",
    "- Actions taken",
    "- Summary (done/blocked)",
    "- Next action",
    "",
    "References:",
    "- Reports path: {reports_path}",
    "- Notes: {notes}",
  ].join("\n");
  const DEFAULT_PROMPT = [
    "目的:",
    "- MF経費の月次処理を安全かつ迅速に完了する。",
    "",
    "対象月:",
    "- {month}",
    "",
    "必須URL:",
    "- https://expense.moneyforward.com/expense_reports",
    "",
    "実施手順:",
    "1. 現在の進捗と未完了タスクを確認する。",
    "2. 不足領収書を取り込み、必要な除外のみを適用する。",
    "3. 照合処理を実行し、結果を要約する。",
    "",
    "出力フォーマット:",
    "- 実施内容",
    "- 結果要約（完了/保留）",
    "- 次アクション",
    "",
    "参照:",
    "- レポートパス: {reports_path}",
    "- メモ: {notes}",
  ].join("\n");

  const linkForm = document.getElementById("workspace-link-form");
  const linkLabelInput = document.getElementById("workspace-link-label");
  const linkUrlInput = document.getElementById("workspace-link-url");
  const clearLinksButton = document.getElementById("workspace-clear-links");
  const customLinksList = document.getElementById("workspace-custom-links");
  const customLinksEmpty = document.getElementById("workspace-custom-links-empty");

  const promptEditor = document.getElementById("workspace-prompt-editor");
  const promptStatus = document.getElementById("workspace-prompt-status");
  const promptCount = document.getElementById("workspace-prompt-count");
  const copyPromptButton = document.getElementById("workspace-copy-prompt");
  const resetPromptButton = document.getElementById("workspace-reset-prompt");
  const promptActiveLabel = document.getElementById("workspace-prompt-active-label");

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function normalizeText(value, maxLength = 200) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
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

  function buildCustomPromptKey(url) {
    return `custom:${encodeURIComponent(String(url || ""))}`;
  }

  function parseCustomPromptKey(key) {
    const text = String(key || "");
    if (!text.startsWith("custom:")) return null;
    const encoded = text.slice("custom:".length);
    try {
      return decodeURIComponent(encoded);
    } catch {
      return null;
    }
  }

  function isValidPromptKey(key) {
    const text = String(key || "").trim();
    if (!text) return false;
    if (text === PROMPT_KEY_MF_EXPENSE_REPORTS) return true;
    return text.startsWith("custom:");
  }

  function readPromptMap() {
    try {
      const raw = window.localStorage.getItem(STORAGE_PROMPTS_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!isObject(parsed)) return {};

      const out = {};
      Object.keys(parsed).forEach((k) => {
        const v = parsed[k];
        if (typeof v === "string") out[k] = v;
      });
      return out;
    } catch {
      return {};
    }
  }

  function savePromptMap(map) {
    const safeMap = isObject(map) ? map : {};
    try {
      window.localStorage.setItem(STORAGE_PROMPTS_KEY, JSON.stringify(safeMap));
      return true;
    } catch {
      return false;
    }
  }

  function migrateLegacyPromptDraft(map) {
    const safeMap = isObject(map) ? map : {};
    if (Object.keys(safeMap).length > 0) return safeMap;
    try {
      const legacy = window.localStorage.getItem(STORAGE_PROMPT_LEGACY_KEY);
      if (legacy) {
        safeMap[PROMPT_KEY_MF_EXPENSE_REPORTS] = String(legacy);
        savePromptMap(safeMap);
      }
    } catch {
      // ignore
    }
    return safeMap;
  }

  let promptMapCache = null;
  function getPromptMapCached() {
    if (promptMapCache) return promptMapCache;
    promptMapCache = migrateLegacyPromptDraft(readPromptMap());
    return promptMapCache;
  }

  function readActivePromptKey() {
    try {
      const raw = window.localStorage.getItem(STORAGE_PROMPT_ACTIVE_KEY);
      const key = String(raw || "").trim();
      return isValidPromptKey(key) ? key : "";
    } catch {
      return "";
    }
  }

  function storeActivePromptKey(key) {
    if (!isValidPromptKey(key)) return;
    try {
      window.localStorage.setItem(STORAGE_PROMPT_ACTIVE_KEY, String(key));
    } catch {
      // ignore
    }
  }

  function resolvePromptUrl(key, context = {}) {
    if (context && typeof context.url === "string" && context.url) return String(context.url);
    const text = String(key || "");
    if (text === PROMPT_KEY_MF_EXPENSE_REPORTS) return "https://expense.moneyforward.com/expense_reports";
    const decoded = parseCustomPromptKey(text);
    return decoded || "";
  }

  function resolvePromptLabel(key, context = {}) {
    if (context && typeof context.label === "string" && context.label.trim()) return String(context.label).trim();
    const text = String(key || "");
    if (text === PROMPT_KEY_MF_EXPENSE_REPORTS) return "MF経費精算ページ";
    const url = resolvePromptUrl(text, context);
    if (url) {
      const links = readCustomLinks();
      const hit = links.find((item) => item && item.url === url);
      if (hit && hit.label) return String(hit.label);
      try {
        return new URL(url).hostname;
      } catch {
        return url;
      }
    }
    return "-";
  }

  function buildDefaultPromptForKey(key, context = {}) {
    const text = String(key || "");
    if (text === PROMPT_KEY_MF_EXPENSE_REPORTS) return DEFAULT_PROMPT;

    const label = resolvePromptLabel(text, context);
    const url = resolvePromptUrl(text, context);
    if (!url) return DEFAULT_PROMPT;

    return [
      "目的:",
      `- 次のページ（${label}）で必要な作業を進める。`,
      "",
      "URL:",
      `- ${url}`,
      "",
      "依頼:",
      "- このページで確認すべき項目と、次にやることを箇条書きで提案して。",
      "",
      "出力フォーマット:",
      "- 現状",
      "- 次アクション",
      "- 注意点",
    ].join("\n");
  }

  function normalizeStoredPromptText(text, key, context = {}) {
    const raw = String(text ?? "");
    if (!raw) return "";
    if (raw === LEGACY_DEFAULT_PROMPT) return buildDefaultPromptForKey(key, context);
    return raw;
  }

  function getPromptTextForKey(key, context = {}) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return DEFAULT_PROMPT;
    const map = getPromptMapCached();
    const stored = normalizeStoredPromptText(map[safeKey], safeKey, context);
    if (stored && stored.trim()) return stored;
    return buildDefaultPromptForKey(safeKey, context);
  }

  function savePromptTextForKey(key, text) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return false;
    const map = getPromptMapCached();
    map[safeKey] = String(text ?? "");
    return savePromptMap(map);
  }

  let activePromptKey = PROMPT_KEY_MF_EXPENSE_REPORTS;
  let activePromptContext = {};

  function updateActivePromptLabel() {
    if (!promptActiveLabel) return;
    promptActiveLabel.textContent = resolvePromptLabel(activePromptKey, activePromptContext);
  }

  function setActivePrompt(key, context = {}) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return;
    activePromptKey = safeKey;
    activePromptContext = isObject(context) ? context : {};
    storeActivePromptKey(activePromptKey);
    updateActivePromptLabel();
  }

  async function copyPromptForKey(key, context = {}) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return;

    // Prefer the current editor content when it's the active prompt, so users
    // don't get an older auto-saved version due to debounce timing.
    const text =
      promptEditor && safeKey === activePromptKey
        ? String(promptEditor.value || "")
        : getPromptTextForKey(safeKey, context);
    if (!text.trim()) {
      showToast("プロンプトが空です。", "error");
      return;
    }
    const ok = await copyToClipboard(text);
    if (ok) showToast("プロンプトをコピーしました。", "success");
    else showToast("プロンプトのコピーに失敗しました。", "error");
  }

  function activatePromptEditorForKey(key, context = {}) {
    if (!promptEditor) return;
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return;

    // Best-effort: persist current draft before switching keys.
    savePromptTextForKey(activePromptKey, String(promptEditor.value || ""));

    setActivePrompt(safeKey, context);
    const text = getPromptTextForKey(activePromptKey, activePromptContext);
    promptEditor.value = text;
    updatePromptMeta(text, "読み込みました。");
    try {
      promptEditor.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch {
      // ignore
    }
    promptEditor.focus();
  }

  function readCustomLinks() {
    try {
      const raw = window.localStorage.getItem(STORAGE_LINKS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map((item) => {
          if (!isObject(item)) return null;
          const url = normalizeUrl(item.url);
          if (!url) return null;
          const fallback = new URL(url).hostname;
          const label = normalizeText(item.label || fallback, 80) || fallback;
          return { label, url };
        })
        .filter(Boolean)
        .slice(0, MAX_LINKS);
    } catch {
      return [];
    }
  }

  function saveCustomLinks(links) {
    const safeLinks = Array.isArray(links)
      ? links
          .map((item) => {
            if (!isObject(item)) return null;
            const url = normalizeUrl(item.url);
            if (!url) return null;
            const fallback = new URL(url).hostname;
            const label = normalizeText(item.label || fallback, 80) || fallback;
            return { label, url };
          })
          .filter(Boolean)
          .slice(0, MAX_LINKS)
      : [];
    try {
      window.localStorage.setItem(STORAGE_LINKS_KEY, JSON.stringify(safeLinks));
      return true;
    } catch {
      return false;
    }
  }

  async function copyToClipboard(text) {
    const value = String(text || "");
    if (!value) return false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
        return true;
      }
    } catch {
      // Fall through to legacy copy path.
    }
    try {
      const helper = document.createElement("textarea");
      helper.value = value;
      helper.setAttribute("readonly", "readonly");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      helper.setSelectionRange(0, helper.value.length);
      const copied = document.execCommand("copy");
      helper.remove();
      return Boolean(copied);
    } catch {
      return false;
    }
  }

  function createLinkNode(link, index, links) {
    const item = document.createElement("li");
    item.className = "workspace-link-item";

    const main = document.createElement("div");
    main.className = "workspace-link-main";

    const label = document.createElement("span");
    label.className = "workspace-link-label";
    label.textContent = link.label;

    const urlAnchor = document.createElement("a");
    urlAnchor.className = "workspace-link-url";
    urlAnchor.href = link.url;
    urlAnchor.target = "_blank";
    urlAnchor.rel = "noopener noreferrer";
    urlAnchor.textContent = link.url;

    main.appendChild(label);
    main.appendChild(urlAnchor);

    const actions = document.createElement("div");
    actions.className = "workspace-link-actions";

    const promptKey = buildCustomPromptKey(link.url);

    const copyUrlButton = document.createElement("button");
    copyUrlButton.type = "button";
    copyUrlButton.className = "secondary workspace-copy-url";
    copyUrlButton.textContent = "URLをコピー";
    copyUrlButton.addEventListener("click", async () => {
      const ok = await copyToClipboard(link.url);
      if (ok) showToast("URLをコピーしました。", "success");
      else showToast("URLのコピーに失敗しました。", "error");
    });

    const copyPromptButton = document.createElement("button");
    copyPromptButton.type = "button";
    copyPromptButton.className = "secondary workspace-copy-prompt";
    copyPromptButton.textContent = "プロンプトをコピー";
    copyPromptButton.addEventListener("click", () => {
      void copyPromptForKey(promptKey, link);
    });

    const editPromptButton = document.createElement("button");
    editPromptButton.type = "button";
    editPromptButton.className = "secondary workspace-edit-prompt";
    editPromptButton.textContent = "編集";
    editPromptButton.addEventListener("click", () => {
      activatePromptEditorForKey(promptKey, link);
    });

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "step-reset";
    removeButton.textContent = "削除";
    removeButton.addEventListener("click", () => {
      const next = links.slice();
      next.splice(index, 1);
      const saved = saveCustomLinks(next);
      if (!saved) {
        showToast("追加リンクを保存できませんでした。", "error");
        return;
      }
      renderCustomLinks(next);
      showToast("追加リンクを削除しました。", "success");
    });

    actions.appendChild(copyUrlButton);
    actions.appendChild(copyPromptButton);
    actions.appendChild(editPromptButton);
    actions.appendChild(removeButton);

    item.appendChild(main);
    item.appendChild(actions);
    return item;
  }

  function renderCustomLinks(links) {
    if (!customLinksList || !customLinksEmpty) return;
    customLinksList.innerHTML = "";
    const safeLinks = Array.isArray(links) ? links : [];
    safeLinks.forEach((link, index) => {
      customLinksList.appendChild(createLinkNode(link, index, safeLinks));
    });
    customLinksEmpty.classList.toggle("hidden", safeLinks.length > 0);
  }

  function updatePromptMeta(text, statusText) {
    if (promptCount) {
      const length = String(text || "").length;
      promptCount.textContent = `${length} 文字`;
    }
    if (promptStatus && statusText) {
      promptStatus.textContent = statusText;
    }
  }

  function resolvePromptContextFromButton(button) {
    const element = button instanceof Element ? button : null;
    const container = element ? element.closest(".workspace-link-item") : null;
    if (!container) return {};

    const labelNode = container.querySelector(".workspace-link-label");
    const urlNode = container.querySelector(".workspace-link-url");
    const context = {};

    const label = labelNode ? normalizeText(labelNode.textContent, 80) : "";
    if (label) context.label = label;

    const urlRaw = urlNode
      ? urlNode.getAttribute("href") || urlNode.textContent || ""
      : "";
    const url = normalizeUrl(urlRaw);
    if (url) context.url = url;

    return context;
  }

  function bindStaticCopyButtons() {
    document.querySelectorAll(".workspace-copy-url[data-copy-url]").forEach((button) => {
      button.addEventListener("click", async () => {
        const value = button.getAttribute("data-copy-url") || "";
        const ok = await copyToClipboard(value);
        if (ok) showToast("URLをコピーしました。", "success");
        else showToast("URLのコピーに失敗しました。", "error");
      });
    });

    document.querySelectorAll(".workspace-copy-prompt[data-prompt-key]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-prompt-key") || "";
        void copyPromptForKey(key, resolvePromptContextFromButton(button));
      });
    });

    document.querySelectorAll(".workspace-edit-prompt[data-prompt-key]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-prompt-key") || "";
        activatePromptEditorForKey(key, resolvePromptContextFromButton(button));
      });
    });
  }

  function initializeLinks() {
    const links = readCustomLinks();
    renderCustomLinks(links);
    bindStaticCopyButtons();

    if (linkForm && linkLabelInput && linkUrlInput) {
      linkForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const url = normalizeUrl(linkUrlInput.value);
        if (!url) {
          showToast("有効な http(s) URL を入力してください。", "error");
          linkUrlInput.focus();
          return;
        }
        const fallback = new URL(url).hostname;
        const label = normalizeText(linkLabelInput.value, 80) || fallback;

        const current = readCustomLinks();
        const duplicate = current.some((item) => String(item.url).toLowerCase() === String(url).toLowerCase());
        if (duplicate) {
          showToast("そのURLはすでに追加されています。", "error");
          return;
        }
        const next = [{ label, url }, ...current].slice(0, MAX_LINKS);
        const saved = saveCustomLinks(next);
        if (!saved) {
          showToast("追加リンクを保存できませんでした。", "error");
          return;
        }
        renderCustomLinks(next);
        linkForm.reset();
        linkLabelInput.focus();
        showToast("追加リンクを保存しました。", "success");
      });
    }

    if (clearLinksButton) {
      clearLinksButton.addEventListener("click", () => {
        try {
          window.localStorage.removeItem(STORAGE_LINKS_KEY);
        } catch {
          showToast("追加リンクを削除できませんでした。", "error");
          return;
        }
        renderCustomLinks([]);
        showToast("追加リンクを全削除しました。", "success");
      });
    }
  }

  function initializePrompt() {
    if (!promptEditor) return;

    const initialKey = readActivePromptKey() || PROMPT_KEY_MF_EXPENSE_REPORTS;
    setActivePrompt(initialKey);

    const initialText = getPromptTextForKey(activePromptKey, activePromptContext);
    promptEditor.value = initialText;
    updatePromptMeta(initialText, "自動保存待機中。");

    let saveTimer = null;
    promptEditor.addEventListener("input", () => {
      updatePromptMeta(promptEditor.value, "編集中...");
      if (saveTimer) window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(() => {
        const ok = savePromptTextForKey(activePromptKey, promptEditor.value);
        if (ok) updatePromptMeta(promptEditor.value, "保存しました。");
        else updatePromptMeta(promptEditor.value, "保存できませんでした（ストレージ利用不可）。");
      }, 250);
    });

    if (copyPromptButton) {
      copyPromptButton.addEventListener("click", async () => {
        const text = promptEditor.value || "";
        if (!text.trim()) {
          showToast("プロンプトが空です。", "error");
          return;
        }
        const ok = await copyToClipboard(text);
        if (ok) showToast("プロンプトをコピーしました。", "success");
        else showToast("プロンプトのコピーに失敗しました。", "error");
      });
    }

    if (resetPromptButton) {
      resetPromptButton.addEventListener("click", () => {
        const template = buildDefaultPromptForKey(activePromptKey, activePromptContext);
        promptEditor.value = template;
        const ok = savePromptTextForKey(activePromptKey, template);
        if (ok) updatePromptMeta(template, "テンプレートを復元しました。");
        else updatePromptMeta(template, "保存できませんでした（ストレージ利用不可）。");
        showToast("テンプレートを復元しました。", "success");
      });
    }
  }

  initializeLinks();
  initializePrompt();
})();
