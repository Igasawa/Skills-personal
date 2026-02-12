(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});

  const STORAGE_LINKS_KEY = "mf-dashboard-workspace-links-v1";
  const STORAGE_PROMPT_LEGACY_KEY = "mf-dashboard-workspace-prompt-v1";
  const STORAGE_PROMPTS_KEY = "mf-dashboard-workspace-prompts-v1";
  const STORAGE_PROMPT_ACTIVE_KEY = "mf-dashboard-workspace-prompt-active-v1";
  const STORAGE_LINK_NOTES_KEY = "mf-dashboard-workspace-link-notes-v1";
  const MAX_LINKS = 100;
  const MAX_LINK_NOTE_CHARS = 4000;
  const LINK_NOTE_SAVE_DEBOUNCE_MS = 300;
  const PROMPT_KEY_MF_EXPENSE_REPORTS = "mf_expense_reports";
  const WORKSPACE_STATE_ENDPOINT = "/api/workspace/state";
  const WORKSPACE_SYNC_DEBOUNCE_MS = 300;
  let workspaceSyncTimer = null;
  let workspaceSyncInFlight = false;
  let workspaceStateRevision = 0;
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
  const linkPurposeInput = document.getElementById("workspace-link-purpose");
  const clearLinksButton = document.getElementById("workspace-clear-links");
  const customLinksList = document.getElementById("workspace-custom-links");
  const customLinksEmpty = document.getElementById("workspace-custom-links-empty");

  const promptEditor = document.getElementById("workspace-prompt-editor");
  const promptStatus = document.getElementById("workspace-prompt-status");
  const promptCount = document.getElementById("workspace-prompt-count");
  const savePromptButton = document.getElementById("workspace-save-prompt");
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

  function formatUrlHost(value) {
    const url = normalizeUrl(value);
    if (!url) return "";
    try {
      return new URL(url).host || url;
    } catch {
      return url;
    }
  }

  function setLinkDetailsExpanded(item, button, expanded) {
    if (!(item instanceof HTMLElement) || !(button instanceof HTMLElement)) return;
    item.dataset.detailsExpanded = expanded ? "1" : "0";
    button.setAttribute("aria-expanded", expanded ? "true" : "false");
    button.textContent = expanded ? "閉じる" : "詳細";
  }

  function attachLinkDetailsToggle(item, button, defaultExpanded = false) {
    if (!(item instanceof HTMLElement) || !(button instanceof HTMLElement)) return;
    if (button.dataset.detailsBound === "1") return;
    button.dataset.detailsBound = "1";
    setLinkDetailsExpanded(item, button, Boolean(defaultExpanded));
    button.addEventListener("click", () => {
      const next = item.dataset.detailsExpanded !== "1";
      setLinkDetailsExpanded(item, button, next);
    });
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

  function normalizeLinkNoteText(value) {
    return String(value ?? "").slice(0, MAX_LINK_NOTE_CHARS);
  }

  function readLinkNoteMap() {
    try {
      const raw = window.localStorage.getItem(STORAGE_LINK_NOTES_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!isObject(parsed)) return {};
      const out = {};
      Object.keys(parsed).forEach((k) => {
        const safeKey = String(k || "").trim();
        if (!isValidPromptKey(safeKey)) return;
        out[safeKey] = normalizeLinkNoteText(parsed[k]);
      });
      return out;
    } catch {
      return {};
    }
  }

  function saveLinkNoteMap(map) {
    const safeMap = isObject(map) ? map : {};
    try {
      window.localStorage.setItem(STORAGE_LINK_NOTES_KEY, JSON.stringify(safeMap));
      scheduleWorkspaceSync();
      return true;
    } catch {
      return false;
    }
  }

  let linkNoteMapCache = null;
  function getLinkNoteMapCached() {
    if (linkNoteMapCache) return linkNoteMapCache;
    linkNoteMapCache = readLinkNoteMap();
    return linkNoteMapCache;
  }

  function getLinkNoteForKey(key) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return "";
    const map = getLinkNoteMapCached();
    return normalizeLinkNoteText(map[safeKey] || "");
  }

  function saveLinkNoteForKey(key, text) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return false;
    const map = getLinkNoteMapCached();
    map[safeKey] = normalizeLinkNoteText(text);
    return saveLinkNoteMap(map);
  }

  function collectLocalWorkspaceState() {
    return {
      links: readCustomLinks(),
      prompts: readPromptMap(),
      link_notes: readLinkNoteMap(),
      active_prompt_key: readActivePromptKey() || PROMPT_KEY_MF_EXPENSE_REPORTS,
    };
  }

  function hasMeaningfulWorkspaceState(state) {
    if (!isObject(state)) return false;
    const links = Array.isArray(state.links) ? state.links : [];
    const prompts = isObject(state.prompts) ? state.prompts : {};
    const linkNotes = isObject(state.link_notes) ? state.link_notes : {};
    return links.length > 0 || Object.keys(prompts).length > 0 || Object.keys(linkNotes).length > 0;
  }

  function applyWorkspaceStateToLocalStorage(state) {
    const links = Array.isArray(state?.links) ? state.links : [];
    const prompts = isObject(state?.prompts) ? state.prompts : {};
    const linkNotes = isObject(state?.link_notes) ? state.link_notes : {};
    const activePromptKey = isValidPromptKey(state?.active_prompt_key)
      ? String(state.active_prompt_key)
      : PROMPT_KEY_MF_EXPENSE_REPORTS;
    try {
      window.localStorage.setItem(STORAGE_LINKS_KEY, JSON.stringify(links));
      window.localStorage.setItem(STORAGE_PROMPTS_KEY, JSON.stringify(prompts));
      window.localStorage.setItem(STORAGE_LINK_NOTES_KEY, JSON.stringify(linkNotes));
      window.localStorage.setItem(STORAGE_PROMPT_ACTIVE_KEY, activePromptKey);
      const revision = Number.parseInt(String(state?.revision ?? "0"), 10);
      workspaceStateRevision = Number.isFinite(revision) && revision >= 0 ? revision : 0;
      promptMapCache = null;
      linkNoteMapCache = null;
    } catch {
      // ignore
    }
  }

  async function fetchWorkspaceStateFromServer() {
    try {
      const res = await fetch(WORKSPACE_STATE_ENDPOINT, { cache: "no-store" });
      if (!res.ok) return null;
      const data = await res.json().catch(() => null);
      if (!isObject(data)) return null;
      return {
        links: Array.isArray(data.links) ? data.links : [],
        prompts: isObject(data.prompts) ? data.prompts : {},
        link_notes: isObject(data.link_notes) ? data.link_notes : {},
        active_prompt_key: isValidPromptKey(data.active_prompt_key)
          ? String(data.active_prompt_key)
          : PROMPT_KEY_MF_EXPENSE_REPORTS,
        revision: (() => {
          const parsed = Number.parseInt(String(data.revision ?? "0"), 10);
          return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
        })(),
      };
    } catch {
      return null;
    }
  }

  async function pushWorkspaceStateToServer(snapshot = null) {
    const payload = isObject(snapshot) ? snapshot : collectLocalWorkspaceState();
    const body = { ...payload, base_revision: workspaceStateRevision };
    if (workspaceSyncInFlight) return false;
    workspaceSyncInFlight = true;
    try {
      const res = await fetch(WORKSPACE_STATE_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) return false;
      const data = await res.json().catch(() => null);
      if (isObject(data)) {
        applyWorkspaceStateToLocalStorage({
          links: Array.isArray(data.links) ? data.links : [],
          prompts: isObject(data.prompts) ? data.prompts : {},
          link_notes: isObject(data.link_notes) ? data.link_notes : {},
          active_prompt_key: isValidPromptKey(data.active_prompt_key)
            ? String(data.active_prompt_key)
            : PROMPT_KEY_MF_EXPENSE_REPORTS,
          revision: (() => {
            const parsed = Number.parseInt(String(data.revision ?? "0"), 10);
            return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
          })(),
        });
      }
      return true;
    } catch {
      return false;
    } finally {
      workspaceSyncInFlight = false;
    }
  }

  function scheduleWorkspaceSync() {
    if (workspaceSyncTimer) window.clearTimeout(workspaceSyncTimer);
    workspaceSyncTimer = window.setTimeout(() => {
      workspaceSyncTimer = null;
      void pushWorkspaceStateToServer();
    }, WORKSPACE_SYNC_DEBOUNCE_MS);
  }

  async function bootstrapWorkspaceState() {
    const localState = collectLocalWorkspaceState();
    const remoteState = await fetchWorkspaceStateFromServer();
    if (remoteState && Number.isFinite(Number(remoteState.revision))) {
      workspaceStateRevision = Number.parseInt(String(remoteState.revision), 10) || 0;
    }
    if (remoteState && hasMeaningfulWorkspaceState(remoteState)) {
      applyWorkspaceStateToLocalStorage(remoteState);
      return;
    }
    if (remoteState && hasMeaningfulWorkspaceState(localState)) {
      await pushWorkspaceStateToServer(localState);
    }
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
      scheduleWorkspaceSync();
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
      scheduleWorkspaceSync();
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
    const saved = savePromptMap(map);
    if (saved) renderPromptFrontByKey(safeKey);
    return saved;
  }

  function hasStoredPromptForKey(key) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return false;
    const map = getPromptMapCached();
    const value = normalizeStoredPromptText(map[safeKey], safeKey);
    return Boolean(value && value.trim());
  }

  function buildPromptPreview(text) {
    const lines = String(text || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length === 0) return "プロンプト先頭: 未登録です。";
    return `プロンプト先頭: ${lines[0]}`;
  }

  function resolvePromptContextFromFront(node) {
    const element = node instanceof HTMLElement ? node : null;
    if (!element) return {};
    const context = {};
    const label = normalizeText(element.dataset.promptLabel || "", 80);
    if (label) context.label = label;
    const url = normalizeUrl(element.dataset.promptUrl || "");
    if (url) context.url = url;
    return context;
  }

  function renderPromptFrontElement(node) {
    const element = node instanceof HTMLElement ? node : null;
    if (!element) return;
    const key = String(element.dataset.promptKey || "").trim();
    if (!isValidPromptKey(key)) return;
    const context = resolvePromptContextFromFront(element);
    const stored = hasStoredPromptForKey(key);
    const promptText =
      promptEditor && key === activePromptKey ? String(promptEditor.value || "") : getPromptTextForKey(key, context);
    const preview = buildPromptPreview(promptText);

    element.innerHTML = "";

    const badge = document.createElement("span");
    badge.className = `workspace-prompt-front-badge ${stored ? "is-registered" : "is-template"}`;
    badge.textContent = stored ? "専用プロンプト" : "テンプレート";

    const previewNode = document.createElement("p");
    previewNode.className = "workspace-prompt-front-preview";
    previewNode.textContent = preview;

    element.appendChild(badge);
    element.appendChild(previewNode);
  }

  function renderPromptFrontByKey(key) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return;
    document.querySelectorAll("[data-prompt-front][data-prompt-key]").forEach((node) => {
      if (!(node instanceof HTMLElement)) return;
      if (String(node.dataset.promptKey || "").trim() !== safeKey) return;
      renderPromptFrontElement(node);
    });
  }

  function renderPromptFronts() {
    document.querySelectorAll("[data-prompt-front][data-prompt-key]").forEach((node) => {
      renderPromptFrontElement(node);
    });
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
    renderPromptFrontByKey(activePromptKey);
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
      scheduleWorkspaceSync();
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

  function bindLinkNoteEditor(editor) {
    if (!(editor instanceof HTMLTextAreaElement)) return;
    const key = String(editor.dataset.noteKey || "").trim();
    if (!isValidPromptKey(key)) return;

    editor.value = getLinkNoteForKey(key);
    if (editor.dataset.noteBound === "1") return;
    editor.dataset.noteBound = "1";

    let saveTimer = null;
    editor.addEventListener("input", () => {
      const next = normalizeLinkNoteText(editor.value || "");
      if (next !== editor.value) editor.value = next;
      if (saveTimer) window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(() => {
        void saveLinkNoteForKey(key, next);
      }, LINK_NOTE_SAVE_DEBOUNCE_MS);
    });
  }

  function bindLinkNoteEditors(root = document) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-workspace-link-note][data-note-key]").forEach((editor) => {
      bindLinkNoteEditor(editor);
    });
  }

  function createLinkNode(link, index, links) {
    const item = document.createElement("li");
    item.className = "workspace-link-item";

    const main = document.createElement("div");
    main.className = "workspace-link-main";
    main.dataset.fullUrl = String(link.url || "");

    const head = document.createElement("div");
    head.className = "workspace-link-head";

    const openLink = document.createElement("a");
    openLink.className = "secondary workspace-link-open";
    openLink.setAttribute("data-workspace-link-open", "");
    openLink.href = link.url;
    openLink.target = "_blank";
    openLink.rel = "noopener noreferrer";
    openLink.title = link.url;
    openLink.setAttribute("aria-label", `${link.label} を開く（${link.url}）`);
    openLink.textContent = link.label;

    const urlToggleButton = document.createElement("button");
    urlToggleButton.type = "button";
    urlToggleButton.className = "workspace-url-toggle";
    urlToggleButton.setAttribute("data-workspace-url-toggle", "");
    urlToggleButton.setAttribute("aria-label", "詳細を表示");
    urlToggleButton.textContent = "詳細";

    const domainAnchor = document.createElement("a");
    domainAnchor.className = "workspace-link-domain";
    domainAnchor.href = link.url;
    domainAnchor.target = "_blank";
    domainAnchor.rel = "noopener noreferrer";
    domainAnchor.title = link.url;
    domainAnchor.textContent = formatUrlHost(link.url) || link.url;
    const promptKey = buildCustomPromptKey(link.url);

    const promptFront = document.createElement("div");
    promptFront.className = "workspace-prompt-front";
    promptFront.setAttribute("data-prompt-front", "");
    promptFront.dataset.promptKey = promptKey;
    promptFront.dataset.promptLabel = String(link.label || "");
    promptFront.dataset.promptUrl = String(link.url || "");
    renderPromptFrontElement(promptFront);

    head.appendChild(openLink);
    head.appendChild(urlToggleButton);
    main.appendChild(head);

    const details = document.createElement("div");
    details.className = "workspace-link-details";
    details.setAttribute("data-workspace-link-details", "");
    details.appendChild(domainAnchor);
    details.appendChild(promptFront);

    const noteWrap = document.createElement("label");
    noteWrap.className = "workspace-link-note";
    const noteLabel = document.createElement("span");
    noteLabel.className = "workspace-link-note-label";
    noteLabel.textContent = "目的";
    const noteEditor = document.createElement("textarea");
    noteEditor.className = "workspace-link-note-editor";
    noteEditor.rows = 3;
    noteEditor.maxLength = MAX_LINK_NOTE_CHARS;
    noteEditor.placeholder = "このリンクを使う目的";
    noteEditor.setAttribute("data-workspace-link-note", "");
    noteEditor.dataset.noteKey = promptKey;
    noteWrap.appendChild(noteLabel);
    noteWrap.appendChild(noteEditor);
    details.appendChild(noteWrap);
    bindLinkNoteEditor(noteEditor);

    const actions = document.createElement("div");
    actions.className = "workspace-link-actions";

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

    const editLinkButton = document.createElement("button");
    editLinkButton.type = "button";
    editLinkButton.className = "secondary workspace-edit-link";
    editLinkButton.textContent = "名称/目的を編集";
    editLinkButton.addEventListener("click", () => {
      const currentPurpose = getLinkNoteForKey(promptKey);
      const nextLabelRaw = window.prompt("リンク名を編集してください。", String(link.label || ""));
      if (nextLabelRaw === null) return;
      const fallbackLabel = formatUrlHost(link.url) || String(link.url || "");
      const nextLabel = normalizeText(nextLabelRaw, 80) || fallbackLabel;
      if (!nextLabel) {
        showToast("リンク名を入力してください。", "error");
        return;
      }

      const nextPurposeRaw = window.prompt("目的を編集してください（空欄可）。", String(currentPurpose || ""));
      if (nextPurposeRaw === null) return;
      const nextPurpose = normalizeLinkNoteText(nextPurposeRaw);

      const next = links.slice();
      next[index] = { label: nextLabel, url: String(link.url || "") };
      const linksSaved = saveCustomLinks(next);
      const purposeSaved = saveLinkNoteForKey(promptKey, nextPurpose);
      if (!linksSaved || !purposeSaved) {
        showToast("リンク名/目的を更新できませんでした。", "error");
        return;
      }

      if (activePromptKey === promptKey) {
        setActivePrompt(promptKey, { label: nextLabel, url: String(link.url || "") });
        if (promptEditor) updatePromptMeta(String(promptEditor.value || ""), "更新しました。");
      }

      renderCustomLinks(next);
      showToast("リンク名/目的を更新しました。", "success");
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
    actions.appendChild(editLinkButton);
    actions.appendChild(removeButton);
    details.appendChild(actions);

    item.appendChild(main);
    item.appendChild(details);
    attachLinkDetailsToggle(item, urlToggleButton, false);
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
    renderPromptFronts();
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

    const labelNode = container.querySelector(".workspace-link-open");
    const urlContainer = container.querySelector(".workspace-link-main");
    const context = {};

    const label = labelNode ? normalizeText(labelNode.textContent, 80) : "";
    if (label) context.label = label;

    const urlRaw = urlContainer instanceof HTMLElement ? String(urlContainer.dataset.fullUrl || "") : "";
    const url = normalizeUrl(urlRaw);
    if (url) context.url = url;

    return context;
  }

  function bindStaticCopyButtons() {
    document.querySelectorAll(".workspace-link-list-static [data-workspace-url-toggle]").forEach((button) => {
      const item = button.closest(".workspace-link-item");
      if (!item) return;
      attachLinkDetailsToggle(item, button, false);
    });

    document.querySelectorAll(".workspace-link-list-static .workspace-copy-url[data-copy-url]").forEach((button) => {
      button.addEventListener("click", async () => {
        const value = button.getAttribute("data-copy-url") || "";
        const ok = await copyToClipboard(value);
        if (ok) showToast("URLをコピーしました。", "success");
        else showToast("URLのコピーに失敗しました。", "error");
      });
    });

    document.querySelectorAll(".workspace-link-list-static .workspace-copy-prompt[data-prompt-key]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-prompt-key") || "";
        void copyPromptForKey(key, resolvePromptContextFromButton(button));
      });
    });

    document.querySelectorAll(".workspace-link-list-static .workspace-edit-prompt[data-prompt-key]").forEach((button) => {
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
    bindLinkNoteEditors(document);

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
        const purpose = normalizeLinkNoteText(linkPurposeInput ? linkPurposeInput.value : "");

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
        if (!saveLinkNoteForKey(buildCustomPromptKey(url), purpose)) {
          showToast("リンクは保存しましたが、目的の保存に失敗しました。", "error");
        }
        renderCustomLinks(next);
        linkForm.reset();
        if (linkPurposeInput) linkPurposeInput.value = "";
        linkLabelInput.focus();
        showToast("追加リンクを保存しました。", "success");
      });
    }

    if (clearLinksButton) {
      clearLinksButton.addEventListener("click", () => {
        const saved = saveCustomLinks([]);
        if (!saved) {
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
    renderPromptFronts();

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

    if (savePromptButton) {
      savePromptButton.addEventListener("click", () => {
        const text = promptEditor.value || "";
        const ok = savePromptTextForKey(activePromptKey, text);
        if (ok) {
          updatePromptMeta(text, "登録しました。");
          showToast("プロンプトを登録しました。", "success");
          return;
        }
        updatePromptMeta(text, "保存できませんでした（ストレージ利用不可）。");
        showToast("プロンプトを登録できませんでした。", "error");
      });
    }
  }

  async function bootstrap() {
    await bootstrapWorkspaceState();
    initializeLinks();
    initializePrompt();
  }

  void bootstrap();
})();
