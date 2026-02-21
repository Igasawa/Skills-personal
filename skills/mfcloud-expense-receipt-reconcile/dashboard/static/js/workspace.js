(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const sendAiChatMessage = typeof Common.sendAiChatMessage === "function" ? Common.sendAiChatMessage : null;

  const STORAGE_LINKS_KEY = "mf-dashboard-workspace-links-v1";
  const STORAGE_PROMPT_LEGACY_KEY = "mf-dashboard-workspace-prompt-v1";
  const STORAGE_PROMPTS_KEY = "mf-dashboard-workspace-prompts-v1";
  const STORAGE_PROMPT_ACTIVE_KEY = "mf-dashboard-workspace-prompt-active-v1";
  const STORAGE_LINK_NOTES_KEY = "mf-dashboard-workspace-link-notes-v1";
  const STORAGE_LINK_PROFILES_KEY = "mf-dashboard-workspace-link-profiles-v1";
  const STORAGE_PINNED_LINKS_KEY = "mf-dashboard-workspace-pinned-links-v1";
  const STORAGE_PINNED_LINK_GROUPS_KEY = "mf-dashboard-workspace-pinned-link-groups-v1";
  const MAX_LINKS = 100;
  const MAX_PINNED_LINKS = 6;
  const MAX_PINNED_GROUPS = 8;
  const MAX_LINK_NOTE_CHARS = 4000;
  const WORKSPACE_PINNED_GROUP_LABEL_PREFIX = "\u56fa\u5b9a\u30ea\u30f3\u30af";
  const LINK_NOTE_SAVE_DEBOUNCE_MS = 300;
  const MAX_PROFILE_OWNER_CHARS = 80;
  const MAX_PROFILE_AGENT_CHARS = 32;
  const REVIEW_STALE_DAYS = 45;
  const PROFILE_SAVE_DEBOUNCE_MS = 300;
  const LINK_UNDO_TTL_MS = 8000;
  const PROMPT_KEY_MF_EXPENSE_REPORTS = "mf_expense_reports";
  const LINK_PROFILE_AGENT_LABELS = Object.freeze({
    codex: "Codex",
    chatgpt: "ChatGPT",
    claude: "Claude",
    gemini: "Gemini",
    other: "その他",
  });
  const WORKSPACE_STATE_ENDPOINT = "/api/workspace/state";
  const WORKSPACE_PROMPT_OPTIMIZE_ENDPOINT = "/api/workspace/prompt/optimize";
  const WORKSPACE_SYNC_DEBOUNCE_MS = 300;
  const PROMPT_OPTIMIZE_TIMEOUT_MS = 35000;
  const PROMPT_UNDO_TTL_MS = 10000;
  const GOAL_FALLBACK = "対象タスクを完遂できるように最適化する";
  const GOAL_INLINE_PATTERN = /^(?:目的|goal|ゴール|やりたいこと|狙い|task)\s*[:：]\s*(.+)$/i;
  const GOAL_HEADING_PATTERN = /^(?:目的|goal|ゴール|やりたいこと|狙い|task)\s*[:：]?$/i;
  const GOAL_LEADING_MARKERS_PATTERN = /^[\s\-*・\d.)]+/;
  let workspaceSyncTimer = null;
  let workspaceSyncInFlight = false;
  let workspaceStateRevision = 0;
  const LEGACY_DEFAULT_PROMPT = [
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
  const pinnedGroupsList = document.getElementById("workspace-pinned-groups");
  const pinnedGroupsEmpty = document.getElementById("workspace-pinned-groups-empty");
  const pinnedCount = document.getElementById("workspace-pinned-count");
  const linkUndo = document.getElementById("workspace-link-undo");
  const toastElement = document.getElementById("toast");
  const TOAST_CONFIRM_DURATION_MS = 10000;

  const promptEditor = document.getElementById("workspace-prompt-editor");
  const promptStatus = document.getElementById("workspace-prompt-status");
  const promptCount = document.getElementById("workspace-prompt-count");
  const savePromptButton = document.getElementById("workspace-save-prompt");
  const optimizePromptButton = document.getElementById("workspace-optimize-prompt");
  const copyHandoffButton = document.getElementById("workspace-copy-handoff");
  const promptActiveLabel = document.getElementById("workspace-prompt-active-label");
  const promptUndo = document.getElementById("workspace-prompt-undo");
  const promptDiffBackdrop = document.getElementById("workspace-prompt-diff-backdrop");
  const promptDiffModal = document.getElementById("workspace-prompt-diff-modal");
  const promptDiffGoal = document.getElementById("workspace-prompt-diff-goal");
  const promptDiffBefore = document.getElementById("workspace-prompt-diff-before");
  const promptDiffAfter = document.getElementById("workspace-prompt-diff-after");
  const promptDiffChangesWrap = document.getElementById("workspace-prompt-diff-changes-wrap");
  const promptDiffChanges = document.getElementById("workspace-prompt-diff-changes");
  const promptDiffConfirmWrap = document.getElementById("workspace-prompt-diff-confirm-wrap");
  const promptDiffConfirm = document.getElementById("workspace-prompt-diff-confirm");
  const promptDiffCancelButton = document.getElementById("workspace-prompt-diff-cancel");
  const promptDiffApplyButton = document.getElementById("workspace-prompt-diff-apply");
  let linkUndoTimer = null;
  let linkUndoAction = null;
  let promptUndoTimer = null;
  let promptUndoAction = null;
  let promptOptimizeRequestId = 0;
  let promptOptimizeInFlight = false;
  let promptOptimizePreview = null;
  let promptDiffEscapeListenerBound = false;
  let toastConfirmTimer = null;

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function normalizeText(value, maxLength = 200) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
  }

  function normalizePromptOptimizeList(value, maxItems = 12, maxChars = 220) {
    if (!Array.isArray(value)) return [];
    const out = [];
    value.forEach((row) => {
      const text = normalizeText(row, maxChars);
      if (!text) return;
      out.push(text);
    });
    return out.slice(0, Math.max(0, maxItems));
  }

  function cleanGoalCandidate(value) {
    const raw = normalizeText(value, 240);
    if (!raw) return "";
    return raw.replace(GOAL_LEADING_MARKERS_PATTERN, "").trim().slice(0, 240);
  }

  function extractGoalFromPromptText(text) {
    const lines = String(text || "")
      .replace(/\r\n/g, "\n")
      .split("\n")
      .map((line) => line.trim());
    const nonEmpty = lines.filter(Boolean);
    if (nonEmpty.length === 0) {
      return { goal: GOAL_FALLBACK, confidence: 0, method: "fallback", evidence: [] };
    }
    for (const line of nonEmpty) {
      const match = line.match(GOAL_INLINE_PATTERN);
      if (!match) continue;
      const goal = cleanGoalCandidate(match[1]);
      if (!goal) continue;
      return {
        goal,
        confidence: 0.95,
        method: "inline_label",
        evidence: [line.slice(0, 120)],
      };
    }
    for (let index = 0; index < nonEmpty.length; index += 1) {
      if (!GOAL_HEADING_PATTERN.test(nonEmpty[index])) continue;
      for (let inner = index + 1; inner < nonEmpty.length; inner += 1) {
        const goal = cleanGoalCandidate(nonEmpty[inner]);
        if (!goal) continue;
        return {
          goal,
          confidence: 0.82,
          method: "heading_followup",
          evidence: [nonEmpty[index].slice(0, 120), nonEmpty[inner].slice(0, 120)],
        };
      }
    }
    const fallback = cleanGoalCandidate(nonEmpty[0]) || GOAL_FALLBACK;
    return {
      goal: fallback,
      confidence: 0.55,
      method: "first_line",
      evidence: [nonEmpty[0].slice(0, 120)],
    };
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

  function normalizeProfileOwner(value) {
    return normalizeText(value, MAX_PROFILE_OWNER_CHARS);
  }

  function normalizeProfileAgent(value) {
    const candidate = String(value || "").trim().toLowerCase().slice(0, MAX_PROFILE_AGENT_CHARS);
    if (!candidate) return "";
    return Object.prototype.hasOwnProperty.call(LINK_PROFILE_AGENT_LABELS, candidate) ? candidate : "";
  }

  function normalizeReviewedOn(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return "";
    const date = new Date(`${text}T00:00:00`);
    if (Number.isNaN(date.getTime())) return "";
    return text;
  }

  function normalizeLinkProfile(value) {
    const row = isObject(value) ? value : {};
    return {
      owner: normalizeProfileOwner(row.owner),
      agent: normalizeProfileAgent(row.agent),
      reviewed_on: normalizeReviewedOn(row.reviewed_on),
    };
  }

  function isEmptyLinkProfile(profile) {
    return !String(profile.owner || "").trim() && !String(profile.agent || "").trim() && !String(profile.reviewed_on || "").trim();
  }

  function readLinkProfileMap() {
    try {
      const raw = window.localStorage.getItem(STORAGE_LINK_PROFILES_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!isObject(parsed)) return {};
      const out = {};
      Object.keys(parsed).forEach((k) => {
        const safeKey = String(k || "").trim();
        if (!isValidPromptKey(safeKey)) return;
        const normalized = normalizeLinkProfile(parsed[k]);
        if (isEmptyLinkProfile(normalized)) return;
        out[safeKey] = normalized;
      });
      return out;
    } catch {
      return {};
    }
  }

  function saveLinkProfileMap(map) {
    const rawMap = isObject(map) ? map : {};
    const safeMap = {};
    Object.keys(rawMap).forEach((k) => {
      const safeKey = String(k || "").trim();
      if (!isValidPromptKey(safeKey)) return;
      const normalized = normalizeLinkProfile(rawMap[safeKey]);
      if (isEmptyLinkProfile(normalized)) return;
      safeMap[safeKey] = normalized;
    });
    try {
      window.localStorage.setItem(STORAGE_LINK_PROFILES_KEY, JSON.stringify(safeMap));
      scheduleWorkspaceSync();
      return true;
    } catch {
      return false;
    }
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

  let linkProfileMapCache = null;
  function getLinkProfileMapCached() {
    if (linkProfileMapCache) return linkProfileMapCache;
    linkProfileMapCache = readLinkProfileMap();
    return linkProfileMapCache;
  }

  function getLinkProfileForKey(key) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return normalizeLinkProfile({});
    const map = getLinkProfileMapCached();
    return normalizeLinkProfile(map[safeKey]);
  }

  function saveLinkProfileForKey(key, profile) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return false;
    const map = getLinkProfileMapCached();
    const normalized = normalizeLinkProfile(profile);
    if (isEmptyLinkProfile(normalized)) {
      delete map[safeKey];
    } else {
      map[safeKey] = normalized;
    }
    return saveLinkProfileMap(map);
  }

  function collectLocalWorkspaceState() {
    return {
      links: readCustomLinks(),
      pinned_link_groups: readPinnedLinkGroups(),
      pinned_links: readPinnedLinks(),
      prompts: readPromptMap(),
      link_notes: readLinkNoteMap(),
      link_profiles: readLinkProfileMap(),
      active_prompt_key: readActivePromptKey() || PROMPT_KEY_MF_EXPENSE_REPORTS,
    };
  }

  function hasMeaningfulWorkspaceState(state) {
    if (!isObject(state)) return false;
    const links = Array.isArray(state.links) ? state.links : [];
    const pinnedGroups = Array.isArray(state.pinned_link_groups) ? state.pinned_link_groups : [];
    const pinnedLinks = Array.isArray(state.pinned_links) ? state.pinned_links : [];
    const prompts = isObject(state.prompts) ? state.prompts : {};
    const linkNotes = isObject(state.link_notes) ? state.link_notes : {};
    const linkProfiles = isObject(state.link_profiles) ? state.link_profiles : {};
    const pinnedLinkCount = Array.isArray(pinnedGroups)
      ? pinnedGroups.reduce((sum, row) => sum + (Array.isArray(row?.links) ? row.links.length : 0), 0)
      : 0;
    return (
      links.length > 0 ||
      pinnedLinkCount > 0 ||
      pinnedLinks.length > 0 ||
      Object.keys(prompts).length > 0 ||
      Object.keys(linkNotes).length > 0 ||
      Object.keys(linkProfiles).length > 0
    );
  }

  function applyWorkspaceStateToLocalStorage(state) {
    const links = Array.isArray(state?.links) ? state.links : [];
    const pinnedGroups = normalizePinnedLinkGroups(Array.isArray(state?.pinned_link_groups) ? state.pinned_link_groups : []);
    const legacyPinnedLinks = Array.isArray(state?.pinned_links) ? state.pinned_links : [];
    const mergedPinnedGroups =
      pinnedGroups.length > 0 ? pinnedGroups : migrateLegacyPinnedLinks(legacyPinnedLinks, pinnedGroups);
    const prompts = isObject(state?.prompts) ? state.prompts : {};
    const linkNotes = isObject(state?.link_notes) ? state.link_notes : {};
    const linkProfiles = isObject(state?.link_profiles) ? state.link_profiles : {};
    const activePromptKey = isValidPromptKey(state?.active_prompt_key)
      ? String(state.active_prompt_key)
      : PROMPT_KEY_MF_EXPENSE_REPORTS;
    const normalized = normalizeLinkPools(links, getAllPinnedLinksFromGroups(mergedPinnedGroups));
    try {
      window.localStorage.setItem(STORAGE_LINKS_KEY, JSON.stringify(normalized.links));
      window.localStorage.setItem(STORAGE_PINNED_LINK_GROUPS_KEY, JSON.stringify(mergedPinnedGroups));
      window.localStorage.setItem(STORAGE_PINNED_LINKS_KEY, JSON.stringify(normalized.pinned_links));
      window.localStorage.setItem(STORAGE_PROMPTS_KEY, JSON.stringify(prompts));
      window.localStorage.setItem(STORAGE_LINK_NOTES_KEY, JSON.stringify(linkNotes));
      window.localStorage.setItem(STORAGE_LINK_PROFILES_KEY, JSON.stringify(linkProfiles));
      window.localStorage.setItem(STORAGE_PROMPT_ACTIVE_KEY, activePromptKey);
      const revision = Number.parseInt(String(state?.revision ?? "0"), 10);
      workspaceStateRevision = Number.isFinite(revision) && revision >= 0 ? revision : 0;
      promptMapCache = null;
      linkNoteMapCache = null;
      linkProfileMapCache = null;
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
        pinned_link_groups: Array.isArray(data.pinned_link_groups) ? data.pinned_link_groups : [],
        pinned_links: Array.isArray(data.pinned_links) ? data.pinned_links : [],
        prompts: isObject(data.prompts) ? data.prompts : {},
        link_notes: isObject(data.link_notes) ? data.link_notes : {},
        link_profiles: isObject(data.link_profiles) ? data.link_profiles : {},
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
          pinned_link_groups: Array.isArray(data.pinned_link_groups) ? data.pinned_link_groups : [],
          pinned_links: Array.isArray(data.pinned_links) ? data.pinned_links : [],
          prompts: isObject(data.prompts) ? data.prompts : {},
          link_notes: isObject(data.link_notes) ? data.link_notes : {},
          link_profiles: isObject(data.link_profiles) ? data.link_profiles : {},
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
      const links = [...getAllPinnedLinksFromGroups(readPinnedLinkGroups()), ...readCustomLinks()];
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
      "",
      "参照:",
      "- レポートパス: {reports_path}",
      "- メモ: {notes}",
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

  function getActivePromptKey() {
    return activePromptKey;
  }

  function getActivePromptContext() {
    return isObject(activePromptContext) ? { ...activePromptContext } : {};
  }

  function getActivePromptState() {
    return { key: activePromptKey, context: getActivePromptContext() };
  }

  async function sendPromptForKey(key, context = {}) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return;

    const text =
      promptEditor && safeKey === activePromptKey
        ? String(promptEditor.value || "")
        : getPromptTextForKey(safeKey, context);
    if (!text.trim()) {
      showToast("プロンプトが空です。", "error");
      return;
    }
    if (!sendAiChatMessage) {
      showToast("AIチャット送信機能を初期化できませんでした。", "error");
      return;
    }
    const ok = await sendAiChatMessage(text);
    if (ok) showToast("プロンプトをAIチャットへ送信しました。", "success");
  }

  async function copyHandoffSetForKey(key, context = {}) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return;
    const label = resolvePromptLabel(safeKey, context);
    const url = resolvePromptUrl(safeKey, context);
    const purpose = getLinkNoteForKey(safeKey).trim();
    const profile = getLinkProfileForKey(safeKey);
    const promptText =
      promptEditor && safeKey === activePromptKey
        ? String(promptEditor.value || "")
        : getPromptTextForKey(safeKey, context);
    if (!promptText.trim()) {
      showToast("プロンプトが空です。", "error");
      return;
    }

    const lines = [
      "目的:",
      `対象リンク: ${label || "-"}`,
      `URL: ${url || "-"}`,
      `対象リンク: ${label || "-"}`,
      `対象リンク: ${label || "-"}`,
      `- 次のページ（${label}）で必要な作業を進める。`,
      `対象リンク: ${label || "-"}`,
      "",
      "目的:",
      promptText,
    ];
    const ok = await copyToClipboard(lines.join("\n"));
    if (ok) showToast("プロンプトをコピーしました。", "success");
    else showToast("プロンプトのコピーに失敗しました。", "error");
  }

  function activatePromptEditorForKey(key, context = {}) {
    if (!promptEditor) return;
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return;

    closePromptOptimizePreview({ keepStatus: true });
    clearPromptUndoNotice();

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

  function sanitizeLinkList(links, limit, allowDuplicateUrls = false) {
    if (!Array.isArray(links)) return [];
    const out = [];
    links.forEach((item) => {
      if (!isObject(item)) return;
      const url = normalizeUrl(item.url);
      if (!url) return;
      if (!allowDuplicateUrls) {
        const key = String(url).toLowerCase();
        const exists = out.some((row) => String(row.url || "").toLowerCase() === key);
        if (exists) return;
      }
      const fallback = new URL(url).hostname;
      const label = normalizeText(item.label || fallback, 80) || fallback;
      out.push({ label, url });
    });
    return out.slice(0, Math.max(0, Number(limit) || 0));
  }

  function normalizeLinkPools(links, pinnedLinks) {
    const safePinnedLinks = sanitizeLinkList(pinnedLinks, MAX_PINNED_LINKS * MAX_PINNED_GROUPS);
    const pinnedKeys = new Set(safePinnedLinks.map((item) => String(item.url || "").toLowerCase()));
    const safeLinks = sanitizeLinkList(links, MAX_LINKS, true).filter(
      (item) => !pinnedKeys.has(String(item.url || "").toLowerCase())
    );
    return { links: safeLinks, pinned_links: safePinnedLinks };
  }

  function generatePinnedGroupId() {
    return `pinned-group-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function generatePinnedGroupLabel(existingLabels = []) {
    const used = new Set(Array.isArray(existingLabels) ? existingLabels.map((value) => String(value || "")) : []);
    let index = 1;
    while (used.has(`${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}${index}`)) index += 1;
    return `${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}${index}`;
  }

  function normalizePinnedGroupLabel(value, existingLabels = []) {
    const raw = String(value || "").trim();
    const fallback = generatePinnedGroupLabel(existingLabels);
    let candidate = raw || fallback;
    if (!candidate) return fallback;
    let suffix = 2;
    const used = new Set(Array.isArray(existingLabels) ? existingLabels.map((v) => String(v || "")) : []);
    while (used.has(candidate)) {
      candidate = `${raw || fallback} (${suffix})`;
      suffix += 1;
    }
    return candidate;
  }

  function normalizePinnedLinkGroups(rows) {
    if (!Array.isArray(rows)) return [];
    const out = [];
    const usedLabels = [];
    const usedIds = new Set();
    rows.forEach((row) => {
      if (!isObject(row)) return;
      const label = normalizePinnedGroupLabel(row.label, usedLabels);
      const idCandidate = String(row.id || "").trim();
      const id = idCandidate && !usedIds.has(idCandidate) ? idCandidate : generatePinnedGroupId();
      usedIds.add(id);
      out.push({
        id,
        label,
        links: sanitizeLinkList(row.links, MAX_PINNED_LINKS),
        created_at: String(row.created_at || ""),
      });
      usedLabels.push(label);
    });
    if (out.length === 0) return [];
    const trimmed = out.slice(0, Math.max(0, MAX_PINNED_GROUPS));
    return trimmed;
  }

  function makePinnedGroup(label, links, createdAt = "") {
    const existingRows = readPinnedLinkGroups();
    const existingLabels = existingRows.map((row) => row.label);
    return {
      id: generatePinnedGroupId(),
      label: normalizePinnedGroupLabel(label || generatePinnedGroupLabel(existingLabels), existingLabels),
      links: sanitizeLinkList(links, MAX_PINNED_LINKS),
      created_at: String(createdAt || ""),
    };
  }

  function readLegacyPinnedLinks() {
    try {
      const raw = window.localStorage.getItem(STORAGE_PINNED_LINKS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return sanitizeLinkList(parsed, MAX_PINNED_LINKS);
    } catch {
      return [];
    }
  }

  function migrateLegacyPinnedLinks(pinnedLinks, baseGroups = []) {
    const base = normalizePinnedLinkGroups(baseGroups);
    if (base.length > 0) return base;
    const safePinnedLinks = Array.isArray(pinnedLinks) ? sanitizeLinkList(pinnedLinks, MAX_PINNED_LINKS) : [];
    if (safePinnedLinks.length === 0) return [];
    const fallback = normalizePinnedLinkGroups([{}])[0] || {
      id: generatePinnedGroupId(),
      label: `${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}1`,
      links: [],
      created_at: "",
    };
    const row = {
      id: generatePinnedGroupId(),
      label: `${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}1`,
      links: safePinnedLinks,
      created_at: "",
    };
    return [row];
  }

  function readPinnedLinkGroups() {
    try {
      const raw = window.localStorage.getItem(STORAGE_PINNED_LINK_GROUPS_KEY);
      if (!raw) {
        const migrated = migrateLegacyPinnedLinks(readLegacyPinnedLinks(), []);
        if (migrated.length > 0) {
          void savePinnedLinkGroups(migrated);
          return migrated;
        }
        return [];
      }
      const parsed = JSON.parse(raw);
      const normalized = normalizePinnedLinkGroups(parsed);
      if (normalized.length > 0) return normalized;
      const migrated = migrateLegacyPinnedLinks(readLegacyPinnedLinks(), normalized);
      if (migrated.length > 0) {
        void savePinnedLinkGroups(migrated);
        return migrated;
      }
      return [];
    } catch {
      return [];
    }
  }

  function readPinnedLinks() {
    const groups = readPinnedLinkGroups();
    return Array.isArray(groups[0]?.links) ? groups[0].links : [];
  }

  function readPinnedLinksAll() {
    return getAllPinnedLinksFromGroups(readPinnedLinkGroups());
  }

  function readPinnedLinksFromGroup(groupId) {
    const groups = readPinnedLinkGroups();
    const targetId = String(groupId || "").trim();
    const group = groups.find((row) => String(row.id || "") === targetId);
    return Array.isArray(group?.links) ? group.links : [];
  }

  function getPinnedGroupIndexById(groupId) {
    const groups = readPinnedLinkGroups();
    const targetId = String(groupId || "").trim();
    return groups.findIndex((row) => String(row.id || "") === targetId);
  }

  function ensurePinnedGroupExists() {
    const groups = readPinnedLinkGroups();
    if (groups.length > 0) return groups;
    const created = makePinnedGroup(`${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}1`, []);
    const saved = savePinnedLinkGroups([created]);
    return saved ? [created] : [];
  }

  function getAllPinnedLinksFromGroups(groups = null) {
    const list = Array.isArray(groups) ? groups : readPinnedLinkGroups();
    const flattened = [];
    list.forEach((row) => {
      if (!isObject(row)) return;
      if (!Array.isArray(row.links)) return;
      row.links.forEach((link) => {
        if (!isObject(link)) return;
        flattened.push(link);
      });
    });
    return sanitizeLinkList(flattened, MAX_PINNED_LINKS * MAX_PINNED_GROUPS);
  }

  function readRawCustomLinks() {
    try {
      const raw = window.localStorage.getItem(STORAGE_LINKS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return sanitizeLinkList(parsed, MAX_LINKS, true);
    } catch {
      return [];
    }
  }

  function readCustomLinks() {
    const raw = readRawCustomLinks();
    const allPinnedLinks = getAllPinnedLinksFromGroups(readPinnedLinkGroups());
    const normalized = normalizeLinkPools(raw, allPinnedLinks);
    return normalized.links;
  }

  function saveWorkspaceState(links, pinnedLinkGroups) {
    const nextGroups = normalizePinnedLinkGroups(pinnedLinkGroups);
    const nextLinks = sanitizeLinkList(links, MAX_LINKS, true);
    const normalized = normalizeLinkPools(nextLinks, getAllPinnedLinksFromGroups(nextGroups));
    try {
      window.localStorage.setItem(STORAGE_LINKS_KEY, JSON.stringify(normalized.links));
      window.localStorage.setItem(STORAGE_PINNED_LINK_GROUPS_KEY, JSON.stringify(nextGroups));
      window.localStorage.setItem(STORAGE_PINNED_LINKS_KEY, JSON.stringify(nextGroups[0]?.links || []));
      scheduleWorkspaceSync();
      return {
        links: normalized.links,
        pinned_link_groups: nextGroups,
        pinned_links: nextGroups[0]?.links || [],
      };
    } catch {
      return null;
    }
  }

  function savePinnedLinkGroups(pinnedLinkGroups) {
    return saveWorkspaceState(readRawCustomLinks(), pinnedLinkGroups);
  }

  function saveCustomLinks(links) {
    const saved = saveWorkspaceState(links, readPinnedLinkGroups());
    return saved;
  }

  function savePinnedLinks(pinnedLinks) {
    const groups = readPinnedLinkGroups();
    const nextGroups =
      groups.length > 0
        ? groups.slice()
        : [makePinnedGroup(`${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}1`, sanitizeLinkList([], MAX_PINNED_LINKS), "")];
    const nextLabelGroup = { ...nextGroups[0], links: sanitizeLinkList(pinnedLinks, MAX_PINNED_LINKS) };
    nextGroups[0] = nextLabelGroup;
    const saved = savePinnedLinkGroups(nextGroups);
    return saved;
  }

  function savePinnedLinksToGroup(groupId, pinnedLinks) {
    const groups = readPinnedLinkGroups();
    const index = groups.findIndex((row) => String(row.id || "") === String(groupId || ""));
    if (index < 0) return false;
    const nextGroups = groups.slice();
    nextGroups[index] = { ...nextGroups[index], links: sanitizeLinkList(pinnedLinks, MAX_PINNED_LINKS) };
    return saveWorkspaceState(readCustomLinks(), nextGroups);
  }

  function saveLinkPools(customLinks, pinnedLinks) {
    const ensured = ensurePinnedGroupExists();
    if (ensured.length === 0) return null;
    const nextGroups = ensured.slice();
    const first = nextGroups[0];
    nextGroups[0] = {
      ...first,
      links: sanitizeLinkList(Array.isArray(pinnedLinks) ? pinnedLinks : [], MAX_PINNED_LINKS),
    };
    return saveWorkspaceState(customLinks, nextGroups);
  }

  function deletePinnedGroup(groupId) {
    const groups = readPinnedLinkGroups();
    const sourceIndex = getPinnedGroupIndexById(groupId);
    if (sourceIndex < 0) return false;
    const next = groups.slice();
    next.splice(sourceIndex, 1);
    const saved = savePinnedLinkGroups(next);
    if (!saved) {
      showToast("固定リンクカードを削除できませんでした。", "error");
      return false;
    }
    renderPinnedLinkGroups();
    return true;
  }

  function reorderPinnedGroups(fromIndex, toIndex) {
    const groups = readPinnedLinkGroups();
    const maxIndex = groups.length - 1;
    const from = Number.isFinite(fromIndex) ? Math.trunc(fromIndex) : -1;
    const to = Number.isFinite(toIndex) ? Math.trunc(toIndex) : -1;
    if (from < 0 || to < 0 || from > maxIndex || to > maxIndex || from === to) return false;
    const next = groups.slice();
    const [moved] = next.splice(from, 1);
    const insertIndex = to;
    next.splice(insertIndex, 0, moved);
    const saved = savePinnedLinkGroups(next);
    if (!saved) {
      showToast("固定リンクカードの順序変更に失敗しました。", "error");
      return false;
    }
    renderPinnedLinkGroups();
    return true;
  }

  function reorderPinnedGroupLinks(groupId, fromIndex, toIndex) {
    const groups = readPinnedLinkGroups();
    const index = getPinnedGroupIndexById(groupId);
    if (index < 0) return false;
    const group = groups[index];
    const links = Array.isArray(group.links) ? sanitizeLinkList(group.links, MAX_PINNED_LINKS) : [];
    const maxIndex = links.length - 1;
    const from = Number.isFinite(fromIndex) ? Math.trunc(fromIndex) : -1;
    const to = Number.isFinite(toIndex) ? Math.trunc(toIndex) : -1;
    if (from < 0 || to < 0 || from > maxIndex || to > maxIndex || from === to) return false;
    const nextLinks = links.slice();
    const [moved] = nextLinks.splice(from, 1);
    const insertIndex = to;
    nextLinks.splice(insertIndex, 0, moved);
    const nextGroups = groups.slice();
    nextGroups[index] = { ...group, links: nextLinks };
    const saved = savePinnedLinkGroups(nextGroups);
    if (!saved) {
      showToast("固定リンクの順序変更に失敗しました。", "error");
      return false;
    }
    renderPinnedLinkGroups();
    return true;
  }

  function updatePinnedGroupLabel(groupId, nextLabel) {
    const groups = readPinnedLinkGroups();
    const index = getPinnedGroupIndexById(groupId);
    if (index < 0) return false;
    const next = groups.slice();
    const existing = groups.map((row) => String(row.label || ""));
    const label = normalizePinnedGroupLabel(
      nextLabel,
      existing.filter((_, rowIndex) => rowIndex !== index),
    );
    const current = String(next[index].label || "");
    if (label === current) return true;
    next[index] = { ...next[index], label };
    const saved = savePinnedLinkGroups(next);
    if (!saved) {
      showToast("固定リンクカード名の変更に失敗しました。", "error");
      return false;
    }
    renderPinnedLinkGroups();
    return true;
  }

  function createPinnedGroupNode(group, index, totalGroups = 0) {
    const safeIndex = Number.isFinite(Number(index)) ? Math.max(0, Math.trunc(index)) : 0;
    const safeTotalGroups = Number.isFinite(Number(totalGroups)) ? Math.max(0, Math.trunc(totalGroups)) : 0;
    const safeGroup = isObject(group) ? group : {};
    const groupId = String(safeGroup.id || "");
    const groupLabel = String(safeGroup.label || "").trim() || `${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}${safeIndex + 1}`;
    const safeLinks = sanitizeLinkList(safeGroup.links, MAX_PINNED_LINKS);

    const item = document.createElement("li");
    item.className = "workspace-pinned-group-item";
    item.dataset.groupIndex = String(safeIndex);
    item.dataset.groupId = groupId;

    const head = document.createElement("div");
    head.className = "workspace-pinned-group-head";

    const titleRow = document.createElement("div");
    titleRow.className = "workspace-pinned-group-title-row";

    const orderBadge = document.createElement("span");
    orderBadge.className = "workspace-link-order-badge";
    orderBadge.textContent = String(safeIndex + 1);
    titleRow.appendChild(orderBadge);

    const orderControls = document.createElement("div");
    orderControls.className = "workspace-pinned-group-order-controls";

    const moveUpButton = document.createElement("button");
    moveUpButton.type = "button";
    moveUpButton.className = "secondary workspace-order-button workspace-order-button-inline";
    moveUpButton.textContent = "↑";
    moveUpButton.setAttribute("aria-label", "固定リンクカードを上へ");
    moveUpButton.disabled = safeIndex <= 0;
    moveUpButton.addEventListener("click", () => {
      const moved = reorderPinnedGroups(safeIndex, safeIndex - 1);
      if (!moved) {
        showToast("固定リンクカードを上へ移動できませんでした。", "error");
      }
    });

    const moveDownButton = document.createElement("button");
    moveDownButton.type = "button";
    moveDownButton.className = "secondary workspace-order-button workspace-order-button-inline";
    moveDownButton.textContent = "↓";
    moveDownButton.setAttribute("aria-label", "固定リンクカードを下へ");
    moveDownButton.disabled = safeIndex >= Math.max(0, safeTotalGroups - 1);
    moveDownButton.addEventListener("click", () => {
      const moved = reorderPinnedGroups(safeIndex, safeIndex + 1);
      if (!moved) {
        showToast("固定リンクカードを下へ移動できませんでした。", "error");
      }
    });

    orderControls.appendChild(moveUpButton);
    orderControls.appendChild(moveDownButton);

    const titleInput = document.createElement("input");
    titleInput.type = "text";
    titleInput.className = "workspace-pinned-group-title";
    titleInput.value = groupLabel;
    titleInput.placeholder = `${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}${safeIndex + 1}`;
    titleInput.setAttribute("aria-label", "固定リンクカード名を編集");
    titleInput.addEventListener("change", () => {
      const changed = updatePinnedGroupLabel(groupId, String(titleInput.value || "").trim());
      if (!changed) {
        titleInput.value = String(groupLabel);
      }
    });
    titleInput.addEventListener("blur", () => {
      const changed = updatePinnedGroupLabel(groupId, String(titleInput.value || "").trim());
      if (!changed) {
        titleInput.value = String(groupLabel);
      }
    });

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "secondary";
    deleteButton.textContent = "削除";
    deleteButton.setAttribute("aria-label", "固定リンクカードを削除");
    deleteButton.addEventListener("click", () => {
      const targetLabel = String(groupLabel || `${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}${safeIndex + 1}`).trim();
      const confirmMessage = `"${targetLabel}"を削除しますか？`;
      showToastConfirmDialog(confirmMessage, {
        confirmText: "削除",
        cancelText: "キャンセル",
        type: "error",
        onConfirm: () => {
          const deleted = deletePinnedGroup(groupId);
          if (!deleted) return;
          showToast(`固定リンクカード「${targetLabel}」を削除しました。`, "success");
        },
      });
    });

    const dragHandle = document.createElement("button");
    dragHandle.type = "button";
    dragHandle.className = "secondary workspace-drag-handle";
    dragHandle.textContent = "並び替え";
    dragHandle.setAttribute("data-workspace-drag-handle", "");
    dragHandle.dataset.dragIndex = String(safeIndex);
    dragHandle.draggable = true;

    titleRow.appendChild(orderControls);
    titleRow.appendChild(titleInput);
    titleRow.appendChild(deleteButton);
    titleRow.appendChild(dragHandle);
    head.appendChild(titleRow);
    item.appendChild(head);

    const linksList = document.createElement("ul");
    linksList.className = "workspace-pinned-group-links workspace-link-list workspace-link-list-pinned";
    linksList.dataset.groupId = groupId;

    safeLinks.forEach((link, linkIndex) => {
      linksList.appendChild(createLinkNode(link, linkIndex, safeLinks, "pinned", {
        groupId,
        groupIndex: safeIndex,
      }));
    });

    item.appendChild(linksList);
    bindPinnedGroupLinksDragAndDrop(groupId, linksList);
    return item;
  }

  function bindPinnedGroupDragAndDrop() {
    if (!pinnedGroupsList) return;
    bindLinkListDragAndDrop(pinnedGroupsList, readPinnedLinkGroups, savePinnedLinkGroups, renderPinnedLinkGroups, {
      saveLabel: "固定リンクカードの順序を保存",
      itemSelector: ".workspace-pinned-group-item[data-group-index]",
      indexAttribute: "groupIndex",
      boundAttribute: "pinnedGroupsDragBound",
      itemHandleSelector: "[data-workspace-drag-handle][data-drag-index]",
    });
  }

  function bindPinnedGroupLinksDragAndDrop(groupId, linksList) {
    if (!(linksList instanceof HTMLElement)) return;
    bindLinkListDragAndDrop(linksList, () => readPinnedLinksFromGroup(groupId), (next) => savePinnedLinksToGroup(groupId, next), () => renderPinnedLinkGroups(), {
      saveLabel: "固定リンクカード内リンクの順序を保存",
      boundAttribute: "pinnedGroupLinksDragBound",
    });
  }

  function renderPinnedLinkGroups(pinnedLinkGroups = null) {
    if (!pinnedGroupsList || !pinnedGroupsEmpty) return;
    const groups = normalizePinnedLinkGroups(Array.isArray(pinnedLinkGroups) ? pinnedLinkGroups : readPinnedLinkGroups());
    pinnedGroupsList.innerHTML = "";
    let totalPinned = 0;
    groups.forEach((group, index) => {
      totalPinned += Array.isArray(group?.links) ? group.links.length : 0;
      const node = createPinnedGroupNode(group, index, groups.length);
      if (node) pinnedGroupsList.appendChild(node);
    });
    pinnedGroupsEmpty.classList.toggle("hidden", groups.length > 0);
    updatePinnedCountMeta(totalPinned, groups.length);
    bindPinnedGroupDragAndDrop();
  }

  function clonePinnedGroupsState(groups) {
    if (!Array.isArray(groups)) return [];
    return groups.map((group) => {
      return {
        id: String(group?.id || ""),
        label: String(group?.label || ""),
        links: Array.isArray(group?.links)
          ? group.links.map((link) => ({ label: String(link?.label || ""), url: String(link?.url || "") }))
          : [],
        created_at: String(group?.created_at || ""),
      };
    });
  }

  async function pickPinnedGroupForPromotion(groups, targetGroupId) {
    if (!Array.isArray(groups) || groups.length === 0) return null;
    const chosen = String(targetGroupId || "").trim();
    if (chosen) {
      const direct = groups.find((group) => String(group?.id || "") === chosen);
      if (direct) return direct;
      showToast("固定リンクカードが見つかりません。", "error");
      return null;
    }

    if (groups.length === 1) return groups[0];
    const groupOptions = groups
      .map((group, index) => {
        const id = String(group?.id || "").trim();
        const label = String(group?.label || "").trim() || `${WORKSPACE_PINNED_GROUP_LABEL_PREFIX}${index + 1}`;
        return { id, label };
      })
      .filter((row) => row.id);
    if (groupOptions.length <= 1) return groups[0] || null;

    const selected = await openPinnedGroupPicker(groupOptions);
    if (!selected) return null;
    const direct = groups.find((group) => String(group?.id || "") === selected);
    if (!direct) {
      showToast("選択した固定リンクカードが見つかりません。", "error");
      return null;
    }
    return direct;
  }

  function openPinnedGroupPicker(groupOptions) {
    const options = Array.isArray(groupOptions) ? groupOptions : [];
    const list = options.filter((row) => String(row?.id || "").trim());
    if (list.length === 0) return Promise.resolve(null);

    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "workspace-pinned-group-picker-overlay";

      const modal = document.createElement("div");
      modal.className = "workspace-pinned-group-picker";
      modal.role = "dialog";
      modal.setAttribute("aria-modal", "true");
      modal.setAttribute("aria-label", "固定リンクカードを選択");

      const title = document.createElement("h3");
      title.className = "workspace-pinned-group-picker-title";
      title.textContent = "固定リンクカードを選択";

      const select = document.createElement("select");
      select.className = "workspace-pinned-group-picker-select";
      list.forEach((row) => {
        const option = document.createElement("option");
        option.value = String(row.id);
        option.textContent = String(row.label || "").trim() || "(Fixed link)";
        select.appendChild(option);
      });

      const actions = document.createElement("div");
      actions.className = "workspace-pinned-group-picker-actions";

      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "secondary";
      cancelButton.textContent = "キャンセル";

      const confirmButton = document.createElement("button");
      confirmButton.type = "button";
      confirmButton.className = "primary";
      confirmButton.textContent = "決定";

      const closePicker = (value) => {
        if (overlay.parentElement) overlay.remove();
        document.removeEventListener("keydown", onKeyDown, true);
        resolve(value);
      };

      const onOverlayClick = (event) => {
        if (event.target === overlay) {
          closePicker(null);
        }
      };
      const onKeyDown = (event) => {
        if (event.key === "Escape") {
          closePicker(null);
        }
      };

      cancelButton.addEventListener("click", () => closePicker(null));
      confirmButton.addEventListener("click", () => closePicker(select.value || null));
      select.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          closePicker(select.value || null);
        }
      });

      overlay.addEventListener("click", onOverlayClick);

      actions.appendChild(cancelButton);
      actions.appendChild(confirmButton);
      modal.appendChild(title);
      modal.appendChild(select);
      modal.appendChild(actions);
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
      document.addEventListener("keydown", onKeyDown, true);
      select.focus();
    });
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

  function resolveAgentLabel(agent) {
    const key = normalizeProfileAgent(agent);
    return key ? LINK_PROFILE_AGENT_LABELS[key] : "未設定";
  }

  function daysSinceReviewedOn(reviewedOn) {
    const normalized = normalizeReviewedOn(reviewedOn);
    if (!normalized) return null;
    const reviewedDate = new Date(`${normalized}T00:00:00`);
    if (Number.isNaN(reviewedDate.getTime())) return null;
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const diff = Math.floor((today.getTime() - reviewedDate.getTime()) / (24 * 60 * 60 * 1000));
    return diff < 0 ? 0 : diff;
  }

  function buildReviewStatusState(profile) {
    const safeProfile = normalizeLinkProfile(profile);
    const ownerText = safeProfile.owner ? `${safeProfile.owner}` : "";
    const agentText = safeProfile.agent ? resolveAgentLabel(safeProfile.agent) : "";
    const ageDays = daysSinceReviewedOn(safeProfile.reviewed_on);
    const ageLabel =
      ageDays === null || Number.isNaN(ageDays) ? "" : `（最終見直しから ${ageDays} 日経過）`;

    if (!safeProfile.reviewed_on) {
      return {
        className: "is-missing",
        text: `${ownerText}${ownerText && agentText ? " / " : ""}${agentText}${ageLabel || " / 見直し日未設定"}`,
      };
    }

    if (ageDays !== null && ageDays > REVIEW_STALE_DAYS) {
      return {
        className: "is-stale",
        text: `${ownerText}${ownerText && agentText ? " / " : ""}${agentText} / 見直し日: ${safeProfile.reviewed_on}${ageLabel}`,
      };
    }

    return {
      className: "is-fresh",
      text: `${ownerText}${ownerText && agentText ? " / " : ""}${agentText} / 見直し日: ${safeProfile.reviewed_on}${ageLabel}`,
    };
  }

  function renderProfileStatusForKey(key, root = document) {
    const safeKey = String(key || "").trim();
    if (!isValidPromptKey(safeKey)) return;
    if (!root || typeof root.querySelectorAll !== "function") return;
    const profile = getLinkProfileForKey(safeKey);
    const status = buildReviewStatusState(profile);
    root.querySelectorAll("[data-workspace-link-review-status][data-profile-key]").forEach((node) => {
      if (!(node instanceof HTMLElement)) return;
      if (String(node.dataset.profileKey || "").trim() !== safeKey) return;
      node.textContent = status.text;
      node.classList.remove("is-fresh", "is-stale", "is-missing");
      node.classList.add(status.className);
    });
  }

  function bindLinkProfileOwnerInput(input) {
    if (!(input instanceof HTMLInputElement)) return;
    const key = String(input.dataset.profileKey || "").trim();
    if (!isValidPromptKey(key)) return;
    const profile = getLinkProfileForKey(key);
    input.value = profile.owner;
    if (input.dataset.profileBound === "1") {
      renderProfileStatusForKey(key);
      return;
    }
    input.dataset.profileBound = "1";
    let timer = null;
    input.addEventListener("input", () => {
      const owner = normalizeProfileOwner(input.value);
      if (owner !== input.value) input.value = owner;
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const latest = getLinkProfileForKey(key);
        void saveLinkProfileForKey(key, { ...latest, owner });
        renderProfileStatusForKey(key);
      }, PROFILE_SAVE_DEBOUNCE_MS);
    });
    renderProfileStatusForKey(key);
  }

  function bindLinkProfileAgentSelect(select) {
    if (!(select instanceof HTMLSelectElement)) return;
    const key = String(select.dataset.profileKey || "").trim();
    if (!isValidPromptKey(key)) return;
    const profile = getLinkProfileForKey(key);
    select.value = normalizeProfileAgent(profile.agent);
    if (select.dataset.profileBound === "1") {
      renderProfileStatusForKey(key);
      return;
    }
    select.dataset.profileBound = "1";
    select.addEventListener("change", () => {
      const latest = getLinkProfileForKey(key);
      const agent = normalizeProfileAgent(select.value);
      void saveLinkProfileForKey(key, { ...latest, agent });
      renderProfileStatusForKey(key);
    });
    renderProfileStatusForKey(key);
  }

  function bindLinkProfileReviewedOnInput(input) {
    if (!(input instanceof HTMLInputElement)) return;
    const key = String(input.dataset.profileKey || "").trim();
    if (!isValidPromptKey(key)) return;
    const profile = getLinkProfileForKey(key);
    input.value = normalizeReviewedOn(profile.reviewed_on);
    if (input.dataset.profileBound === "1") {
      renderProfileStatusForKey(key);
      return;
    }
    input.dataset.profileBound = "1";
    input.addEventListener("change", () => {
      const latest = getLinkProfileForKey(key);
      const reviewed_on = normalizeReviewedOn(input.value);
      void saveLinkProfileForKey(key, { ...latest, reviewed_on });
      renderProfileStatusForKey(key);
    });
    renderProfileStatusForKey(key);
  }

  function bindLinkProfileEditors(root = document) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-workspace-link-owner][data-profile-key]").forEach((input) => {
      bindLinkProfileOwnerInput(input);
    });
    root.querySelectorAll("[data-workspace-link-agent][data-profile-key]").forEach((select) => {
      bindLinkProfileAgentSelect(select);
    });
    root.querySelectorAll("[data-workspace-link-reviewed-on][data-profile-key]").forEach((input) => {
      bindLinkProfileReviewedOnInput(input);
    });
    root.querySelectorAll("[data-workspace-link-review-status][data-profile-key]").forEach((statusNode) => {
      if (!(statusNode instanceof HTMLElement)) return;
      const key = String(statusNode.dataset.profileKey || "").trim();
      if (!isValidPromptKey(key)) return;
      renderProfileStatusForKey(key, root);
    });
  }

  function bindWorkspaceMetadataToggle(root = document) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-workspace-link-profile-toggle]").forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) return;
      if (button.dataset.workspaceLinkMetadataToggleBound === "1") return;
      button.dataset.workspaceLinkMetadataToggleBound = "1";

      const details = button.closest(".workspace-link-details");
      const profileSection = details ? details.querySelector(".workspace-link-profile-section") : null;
      if (!(profileSection instanceof HTMLElement)) return;

      const profileKeyNode = profileSection.querySelector(
        "[data-workspace-link-owner][data-profile-key], [data-workspace-link-agent][data-profile-key], [data-workspace-link-reviewed-on][data-profile-key], [data-workspace-link-review-status][data-profile-key]",
      );
      const profileKey = profileKeyNode ? String(profileKeyNode.dataset.profileKey || "").trim() : "";
      const profile = getLinkProfileForKey(profileKey);
      const hasMetadata = Boolean(profile.owner) || Boolean(profile.agent) || Boolean(profile.reviewed_on);

      profileSection.hidden = !hasMetadata;
      button.textContent = hasMetadata ? "情報を隠す" : "情報を表示";

      button.addEventListener("click", () => {
        const nextHidden = !profileSection.hidden;
        profileSection.hidden = nextHidden;
        button.textContent = nextHidden ? "情報を表示" : "情報を隠す";
        if (!nextHidden) {
          const firstInput = profileSection.querySelector(
            "[data-workspace-link-owner], [data-workspace-link-agent], [data-workspace-link-reviewed-on]",
          );
          if (firstInput instanceof HTMLElement && typeof firstInput.focus === "function") {
            firstInput.focus();
          }
        }
      });
    });
  }

  function clearLinkUndoNotice() {
    linkUndoAction = null;
    if (linkUndoTimer) {
      window.clearTimeout(linkUndoTimer);
      linkUndoTimer = null;
    }
    if (!linkUndo) return;
    linkUndo.classList.add("hidden");
    linkUndo.innerHTML = "";
  }

  function clearToast() {
    if (toastConfirmTimer) {
      window.clearTimeout(toastConfirmTimer);
      toastConfirmTimer = null;
    }
    if (window.__toastTimer) {
      window.clearTimeout(window.__toastTimer);
      window.__toastTimer = null;
    }
    if (!toastElement) return;
    toastElement.classList.remove("show", "success", "error", "toast-confirm");
    toastElement.textContent = "";
  }

  function hideToast() {
    if (!toastElement) return;
    if (toastConfirmTimer) {
      window.clearTimeout(toastConfirmTimer);
      toastConfirmTimer = null;
    }
    if (window.__toastTimer) {
      window.clearTimeout(window.__toastTimer);
      window.__toastTimer = null;
    }
    toastElement.classList.remove("show", "toast-confirm");
    toastElement.textContent = "";
  }

  function showToastConfirmDialog(message, {
    confirmText = "OK",
    cancelText = "キャンセル",
    onConfirm = null,
    onCancel = null,
    type = "",
    duration = TOAST_CONFIRM_DURATION_MS,
  } = {}) {
    const normalizedMessage = String(message || "").trim();
    if (!toastElement || !normalizedMessage || typeof onConfirm !== "function") return false;
    const safeDuration = Number.isFinite(Number(duration)) ? Math.max(2500, Math.floor(Number(duration))) : TOAST_CONFIRM_DURATION_MS;

    clearToast();
    toastElement.classList.remove("success", "error", "toast-confirm");
    if (type === "success") toastElement.classList.add("success");
    if (type === "error") toastElement.classList.add("error");
    toastElement.classList.add("toast-confirm");

    const messageText = document.createElement("div");
    messageText.className = "toast-message";
    messageText.textContent = normalizedMessage;

    const actions = document.createElement("div");
    actions.className = "toast-actions";

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "secondary toast-action-button";
    cancelButton.textContent = String(cancelText || "キャンセル");

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "primary toast-action-button";
    confirmButton.textContent = String(confirmText || "OK");

    cancelButton.addEventListener("click", () => {
      hideToast();
      if (typeof onCancel === "function") onCancel();
    });
    confirmButton.addEventListener("click", () => {
      hideToast();
      onConfirm();
    });

    actions.appendChild(cancelButton);
    actions.appendChild(confirmButton);
    toastElement.appendChild(messageText);
    toastElement.appendChild(actions);
    requestAnimationFrame(() => toastElement.classList.add("show"));

    toastConfirmTimer = window.setTimeout(() => {
      hideToast();
      if (typeof onCancel === "function") onCancel();
    }, safeDuration);
    return true;
  }

  function showLinkUndoNotice(message, onUndo) {
    if (!linkUndo) return;
    clearLinkUndoNotice();
    linkUndoAction = typeof onUndo === "function" ? onUndo : null;
    const text = document.createElement("span");
    text.textContent = String(message || "").trim() || "元に戻せます。";

    const undoButton = document.createElement("button");
    undoButton.type = "button";
    undoButton.className = "secondary workspace-link-undo-button";
    undoButton.textContent = "元に戻す";
    undoButton.addEventListener("click", () => {
      const action = linkUndoAction;
      clearLinkUndoNotice();
      if (typeof action === "function") action();
    });

    linkUndo.appendChild(text);
    linkUndo.appendChild(undoButton);
    linkUndo.classList.remove("hidden");

    linkUndoTimer = window.setTimeout(() => {
      clearLinkUndoNotice();
    }, LINK_UNDO_TTL_MS);
  }

  function clearPromptUndoNotice() {
    promptUndoAction = null;
    if (promptUndoTimer) {
      window.clearTimeout(promptUndoTimer);
      promptUndoTimer = null;
    }
    if (!promptUndo) return;
    promptUndo.classList.add("hidden");
    promptUndo.innerHTML = "";
  }

  function showPromptUndoNotice(message, onUndo) {
    if (!promptUndo) return;
    clearPromptUndoNotice();
    promptUndoAction = typeof onUndo === "function" ? onUndo : null;
    const text = document.createElement("span");
    text.textContent = String(message || "").trim() || "元に戻せます。";

    const undoButton = document.createElement("button");
    undoButton.type = "button";
    undoButton.className = "secondary workspace-link-undo-button";
    undoButton.textContent = "元に戻す";
    undoButton.addEventListener("click", () => {
      const action = promptUndoAction;
      clearPromptUndoNotice();
      if (typeof action === "function") action();
    });

    promptUndo.appendChild(text);
    promptUndo.appendChild(undoButton);
    promptUndo.classList.remove("hidden");

    promptUndoTimer = window.setTimeout(() => {
      clearPromptUndoNotice();
    }, PROMPT_UNDO_TTL_MS);
  }

  function setPromptOptimizeButtonLoading(loading) {
    if (!optimizePromptButton) return;
    optimizePromptButton.disabled = Boolean(loading);
    optimizePromptButton.textContent = loading ? "最適化中..." : "AIで最適化";
  }

  function renderPromptDiffList(container, items) {
    if (!(container instanceof HTMLElement)) return;
    container.innerHTML = "";
    normalizePromptOptimizeList(items).forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      container.appendChild(li);
    });
  }

  function handlePromptDiffEscape(event) {
    if (!event || event.key !== "Escape") return;
    if (promptOptimizePreview) {
      event.preventDefault();
      closePromptOptimizePreview();
    }
  }

  function setPromptDiffVisibility(visible) {
    if (promptDiffBackdrop) {
      promptDiffBackdrop.hidden = !visible;
      promptDiffBackdrop.classList.toggle("hidden", !visible);
    }
    if (promptDiffModal) {
      promptDiffModal.hidden = !visible;
      promptDiffModal.classList.toggle("hidden", !visible);
    }
    if (visible && !promptDiffEscapeListenerBound) {
      document.addEventListener("keydown", handlePromptDiffEscape, true);
      promptDiffEscapeListenerBound = true;
      return;
    }
    if (!visible && promptDiffEscapeListenerBound) {
      document.removeEventListener("keydown", handlePromptDiffEscape, true);
      promptDiffEscapeListenerBound = false;
    }
  }

  function closePromptOptimizePreview(options = {}) {
    const keepStatus = Boolean(options.keepStatus);
    promptOptimizePreview = null;
    setPromptDiffVisibility(false);
    if (!keepStatus && promptEditor) {
      updatePromptMeta(promptEditor.value, "自動保存待機中。");
    }
  }

  function openPromptOptimizePreview(preview) {
    if (!isObject(preview)) return;
    promptOptimizePreview = preview;
    if (promptDiffGoal) {
      const goalText = normalizeText(preview.goal || GOAL_FALLBACK, 240);
      promptDiffGoal.textContent = `抽出した目的: ${goalText}`;
    }
    if (promptDiffBefore) {
      promptDiffBefore.textContent = String(preview.baseText || "");
    }
    if (promptDiffAfter) {
      promptDiffAfter.textContent = String(preview.optimizedText || "");
    }

    const changeItems = normalizePromptOptimizeList(preview.changes);
    if (promptDiffChangesWrap) {
      promptDiffChangesWrap.classList.toggle("hidden", changeItems.length <= 0);
    }
    renderPromptDiffList(promptDiffChanges, changeItems);

    const needsConfirmation = normalizePromptOptimizeList(preview.needsConfirmation);
    if (promptDiffConfirmWrap) {
      promptDiffConfirmWrap.classList.toggle("hidden", needsConfirmation.length <= 0);
    }
    renderPromptDiffList(promptDiffConfirm, needsConfirmation);

    setPromptDiffVisibility(true);
    if (promptDiffApplyButton) promptDiffApplyButton.focus();
  }

  async function requestPromptOptimization(payload) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), PROMPT_OPTIMIZE_TIMEOUT_MS);
    try {
      const res = await fetch(WORKSPACE_PROMPT_OPTIMIZE_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(String(body?.detail || `status=${res.status}`));
      }
      if (!isObject(body)) {
        throw new Error("AI response is invalid.");
      }
      return body;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function applyPromptOptimizePreview() {
    if (!promptEditor || !isObject(promptOptimizePreview)) return false;
    const preview = promptOptimizePreview;
    if (String(preview.key || "") !== String(activePromptKey || "")) {
      showToast("編集中の対象が変わったため、最適化結果を適用できません。", "error");
      closePromptOptimizePreview();
      return false;
    }

    const beforeText = String(promptEditor.value || "");
    const optimizedText = String(preview.optimizedText || "");
    if (!optimizedText.trim()) {
      showToast("最適化結果が空です。", "error");
      return false;
    }

    promptEditor.value = optimizedText;
    const saved = savePromptTextForKey(activePromptKey, optimizedText);
    if (!saved) {
      promptEditor.value = beforeText;
      updatePromptMeta(beforeText, "保存できませんでした（ストレージ利用不可）。");
      showToast("最適化結果を保存できませんでした。", "error");
      return false;
    }

    updatePromptMeta(optimizedText, "最適化を適用しました。");
    closePromptOptimizePreview({ keepStatus: true });
    showToast("最適化を適用しました。", "success");

    const snapshot = {
      key: activePromptKey,
      context: { ...activePromptContext },
      text: beforeText,
    };
    showPromptUndoNotice("最適化の適用を取り消せます。", () => {
      const safeKey = String(snapshot.key || "").trim();
      if (!isValidPromptKey(safeKey)) return;
      if (safeKey !== activePromptKey) {
        savePromptTextForKey(activePromptKey, String(promptEditor.value || ""));
        setActivePrompt(safeKey, isObject(snapshot.context) ? snapshot.context : {});
      }
      promptEditor.value = String(snapshot.text || "");
      const ok = savePromptTextForKey(safeKey, promptEditor.value);
      if (ok) {
        updatePromptMeta(promptEditor.value, "1つ前の状態に戻しました。");
        showToast("1つ前の状態に戻しました。", "success");
      } else {
        updatePromptMeta(promptEditor.value, "保存できませんでした（ストレージ利用不可）。");
        showToast("元に戻せませんでした。", "error");
      }
    });
    return true;
  }

  async function optimizeActivePrompt() {
    if (!promptEditor || promptOptimizeInFlight) return;
    const baseText = String(promptEditor.value || "");
    if (!baseText.trim()) {
      showToast("最適化するプロンプトが空です。", "error");
      return;
    }

    const goalHint = extractGoalFromPromptText(baseText);
    const requestId = promptOptimizeRequestId + 1;
    promptOptimizeRequestId = requestId;
    promptOptimizeInFlight = true;
    setPromptOptimizeButtonLoading(true);
    updatePromptMeta(baseText, "AI最適化を実行中...");

    try {
      const response = await requestPromptOptimization({
        text: baseText,
        goal: goalHint.goal || GOAL_FALLBACK,
        locale: "ja-JP",
        stylePreset: "goal-first",
      });
      if (requestId !== promptOptimizeRequestId) return;
      const optimizedText = String(response.optimizedPrompt || "");
      if (!optimizedText.trim()) {
        throw new Error("最適化結果が空です。");
      }
      if (optimizedText === baseText) {
        updatePromptMeta(baseText, "変更はありませんでした。");
        showToast("変更はありませんでした。", "success");
        return;
      }
      openPromptOptimizePreview({
        requestId,
        key: activePromptKey,
        context: { ...activePromptContext },
        goal: String(response.goal || goalHint.goal || GOAL_FALLBACK),
        baseText,
        optimizedText,
        changes: normalizePromptOptimizeList(response.changes),
        assumptions: normalizePromptOptimizeList(response.assumptions),
        risks: normalizePromptOptimizeList(response.risks),
        needsConfirmation: normalizePromptOptimizeList([
          ...normalizePromptOptimizeList(response.needsConfirmation),
          ...normalizePromptOptimizeList(response.risks),
        ]),
      });
      updatePromptMeta(baseText, "最適化結果を確認してください。");
    } catch (error) {
      const message = String(error && error.message ? error.message : "最適化に失敗しました。");
      updatePromptMeta(baseText, "最適化に失敗しました。");
      showToast(message, "error");
    } finally {
      if (requestId === promptOptimizeRequestId) {
        promptOptimizeInFlight = false;
        setPromptOptimizeButtonLoading(false);
      }
    }
  }

  function updatePinnedCountMeta(total, totalGroups = 1) {
    if (!pinnedCount) return;
    const safeTotal = Number.isFinite(total) ? Math.max(0, total) : 0;
    const normalizedGroups = Number.isFinite(totalGroups) ? Math.max(0, Math.trunc(totalGroups)) : 1;
    const maxPinned = MAX_PINNED_LINKS * Math.max(1, normalizedGroups);
    pinnedCount.textContent = `固定リンク（追加分）: ${safeTotal} / ${MAX_PINNED_LINKS}`;
    pinnedCount.classList.toggle("is-limit", safeTotal >= maxPinned);
  }

  function renderLinkLists(links, pinnedLinkGroups = null) {
    const groups = Array.isArray(pinnedLinkGroups) ? normalizePinnedLinkGroups(pinnedLinkGroups) : readPinnedLinkGroups();
    const normalized = normalizeLinkPools(links, getAllPinnedLinksFromGroups(groups));
    renderCustomLinks(normalized.links);
    renderPinnedLinkGroups(groups);
    renderPromptFronts();
  }

  async function promoteCustomLinkToGroup(url, options = {}) {
    const normalizedUrl = normalizeUrl(url);
    if (!normalizedUrl) return;

    const groups = readPinnedLinkGroups();
    if (groups.length === 0) {
      showToast("固定リンクカードがありません。", "error");
      return;
    }

    const current = normalizeLinkPools(readCustomLinks(), getAllPinnedLinksFromGroups(groups));
    const fromIndex = current.links.findIndex((item) => String(item.url || "").toLowerCase() === String(normalizedUrl).toLowerCase());
    if (fromIndex < 0) {
      showToast("対象リンクが見つかりません。", "error");
      return;
    }

    const target = await pickPinnedGroupForPromotion(groups, options.targetGroupId);
    if (!target) return;

    const targetIndex = getPinnedGroupIndexById(target.id);
    if (targetIndex < 0) return;
    const targetLinks = sanitizeLinkList(Array.isArray(groups[targetIndex]?.links) ? groups[targetIndex].links : [], MAX_PINNED_LINKS);
    if (targetLinks.length >= MAX_PINNED_LINKS) {
      showToast(`固定リンクの上限（${MAX_PINNED_LINKS}件）に達しました。`, "error");
      return;
    }

    const snapshot = {
      links: current.links.map((item) => ({ ...item })),
      pinned_link_groups: clonePinnedGroupsState(groups),
    };

    const moved = { ...current.links[fromIndex] };
    const nextLinks = current.links.slice();
    nextLinks.splice(fromIndex, 1);

    const nextGroups = groups.slice();
    nextGroups[targetIndex] = {
      ...nextGroups[targetIndex],
      links: sanitizeLinkList([moved, ...targetLinks], MAX_PINNED_LINKS),
    };

    const saved = saveWorkspaceState(nextLinks, nextGroups);
    if (!saved) {
      showToast("固定リンクへの追加に失敗しました。", "error");
      return;
    }

    renderLinkLists(saved.links, saved.pinned_link_groups);
    showToast("選択した固定リンクカードに固定しました。", "success");

    showLinkUndoNotice("固定リンク追加を取り消しますか？", () => {
      const restored = saveWorkspaceState(snapshot.links, snapshot.pinned_link_groups);
      if (!restored) {
        showToast("固定化の取り消しに失敗しました。", "error");
        return;
      }
      renderLinkLists(restored.links, restored.pinned_link_groups);
      showToast("取り消しました。", "success");
    });
  }

  function demotePinnedLinkByUrl(url, options = {}) {
    const groups = readPinnedLinkGroups();
    if (groups.length === 0) return false;

    const normalizedUrl = normalizeUrl(url);
    if (!normalizedUrl) return false;
    if (options.targetGroupId) {
      return demoteGroupLink(options.targetGroupId, normalizedUrl, options);
    }

    if (groups.length === 1) {
      return demoteGroupLink(groups[0].id, normalizedUrl, options);
    }

    const index = groups.findIndex((group) =>
      Array.isArray(group.links) && group.links.some((item) => String(item.url || "").toLowerCase() === String(normalizedUrl).toLowerCase()),
    );
    if (index < 0) return false;
    return demoteGroupLink(groups[index].id, normalizedUrl, options);
  }

  function demoteGroupLink(groupId, url, options = {}) {
    const normalizedUrl = normalizeUrl(url);
    if (!normalizedUrl) return false;

    const groups = readPinnedLinkGroups();
    const targetIndex = getPinnedGroupIndexById(groupId);
    if (targetIndex < 0) return false;

    const showFeedback = options.showFeedback !== false;
    const showUndo = options.showUndo !== false;
    const current = normalizeLinkPools(readCustomLinks(), getAllPinnedLinksFromGroups(groups));
    const targetLinks = sanitizeLinkList(Array.isArray(groups[targetIndex]?.links) ? groups[targetIndex].links : [], MAX_PINNED_LINKS);

    const sourceIndexCandidate = Number.isFinite(Number(options.sourceIndex)) ? Math.trunc(Number(options.sourceIndex)) : -1;
    const sourceIndex = sourceIndexCandidate >= 0
      ? sourceIndexCandidate
      : targetLinks.findIndex((item) => String(item.url || "").toLowerCase() === String(normalizedUrl).toLowerCase());
    if (sourceIndex < 0) return false;

    const snapshot = {
      links: current.links.map((item) => ({ ...item })),
      pinned_link_groups: clonePinnedGroupsState(groups),
    };

    const nextTargetLinks = targetLinks.slice();
    const [moved] = nextTargetLinks.splice(sourceIndex, 1);
    if (!moved) return false;

    const nextGroups = groups.slice();
    nextGroups[targetIndex] = {
      ...nextGroups[targetIndex],
      links: sanitizeLinkList(nextTargetLinks, MAX_PINNED_LINKS),
    };

    const nextLinks = sanitizeLinkList([{ ...moved }, ...current.links], MAX_LINKS);
    const saved = saveWorkspaceState(nextLinks, nextGroups);
    if (!saved) {
      if (showFeedback) showToast("固定解除に失敗しました。", "error");
      return false;
    }

    renderLinkLists(saved.links, saved.pinned_link_groups);
    if (showFeedback) showToast("固定を解除しました。", "success");

    if (!showUndo) return true;

    clearLinkUndoNotice();
    showLinkUndoNotice("固定解除を取り消しますか？", () => {
      const restored = saveWorkspaceState(snapshot.links, snapshot.pinned_link_groups);
      if (!restored) {
        showToast("固定解除の取り消しに失敗しました。", "error");
        return;
      }
      renderLinkLists(restored.links, restored.pinned_link_groups);
      showToast("取り消しました。", "success");
    });
    return true;
  }

  function bindLinkListDragAndDrop(listElement, readLinks, saveLinks, renderLinks, options = {}) {
    if (!(listElement instanceof HTMLElement)) return;
    const boundAttribute = String(options.boundAttribute || "dragBound");
    if (listElement.dataset[boundAttribute] === "1") return;
    listElement.dataset[boundAttribute] = "1";
    const saveLabel = String(options.saveLabel || "").trim() || "順序を保存";
    const itemSelector = String(options.itemSelector || ".workspace-link-item[data-link-index]").trim();
    const itemHandleSelector = String(options.itemHandleSelector || "[data-workspace-drag-handle][data-drag-index]").trim();
    const indexAttribute = String(options.indexAttribute || "linkIndex").trim();
    const draggingClass = String(options.draggingClass || "is-dragging").trim();
    const dropClass = String(options.dropClass || "is-drop-target").trim();
    let draggingIndex = -1;

    const clearDragClasses = () => {
      listElement.querySelectorAll(`.${draggingClass}`).forEach((node) => {
        node.classList.remove(draggingClass);
      });
      listElement.querySelectorAll(`.${dropClass}`).forEach((node) => {
        node.classList.remove(dropClass);
      });
    };

    const toIndexFromNode = (item) => {
      if (!(item instanceof HTMLElement)) return -1;
      const raw = item.dataset[indexAttribute] || "";
      const parsed = Number.parseInt(raw, 10);
      return Number.isFinite(parsed) && parsed >= 0 ? parsed : -1;
    };

    listElement.addEventListener("dragstart", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const handle = target ? target.closest(itemHandleSelector) : null;
      if (!(handle instanceof HTMLElement)) return;
      const indexRaw = handle.dataset.dragIndex || "";
      const nextIndex = Number.parseInt(indexRaw, 10);
      if (!Number.isFinite(nextIndex) || nextIndex < 0) return;

      draggingIndex = nextIndex;
      const item = handle.closest(itemSelector);
      if (item instanceof HTMLElement) item.classList.add(draggingClass);

      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        try {
          event.dataTransfer.setData("text/plain", `${nextIndex}`);
        } catch {
          // no-op
        }
      }
    });

    listElement.addEventListener("dragover", (event) => {
      if (!Number.isFinite(draggingIndex) || draggingIndex < 0) return;
      const target = event.target instanceof Element ? event.target : null;
      const item = target ? target.closest(itemSelector) : null;
      if (!(item instanceof HTMLElement)) return;
      const targetIndex = toIndexFromNode(item);
      if (targetIndex < 0 || targetIndex === draggingIndex) return;
      event.preventDefault();
      clearDragClasses();
      item.classList.add(dropClass);
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    });

    listElement.addEventListener("drop", (event) => {
      if (!Number.isFinite(draggingIndex) || draggingIndex < 0) return;
      const target = event.target instanceof Element ? event.target : null;
      const item = target ? target.closest(itemSelector) : null;
      if (!(item instanceof HTMLElement)) return;
      const targetIndex = toIndexFromNode(item);
      if (!Number.isFinite(targetIndex) || targetIndex < 0) {
        clearDragClasses();
        draggingIndex = -1;
        return;
      }
      if (targetIndex === draggingIndex) {
        clearDragClasses();
        draggingIndex = -1;
        return;
      }
      event.preventDefault();

      const current = typeof readLinks === "function" ? readLinks() : [];
      if (!Array.isArray(current) || current.length === 0) {
        clearDragClasses();
        draggingIndex = -1;
        return;
      }
      if (draggingIndex >= current.length || targetIndex >= current.length) {
        clearDragClasses();
        draggingIndex = -1;
        return;
      }

      const next = current.slice();
      const [moved] = next.splice(draggingIndex, 1);
      const insertIndex = targetIndex;
      next.splice(insertIndex, 0, moved);

      const saved = typeof saveLinks === "function" ? saveLinks(next) : false;
      if (!saved) {
        clearDragClasses();
        draggingIndex = -1;
        showToast(`${saveLabel}`, "error");
        return;
      }
      if (typeof renderLinks === "function") {
        renderLinks(next);
      }
      showToast(`${saveLabel}`, "success");
      clearDragClasses();
      draggingIndex = -1;
    });

    listElement.addEventListener("dragend", () => {
      clearDragClasses();
      draggingIndex = -1;
    });
  }

  function bindCustomLinkDragAndDrop() {
    bindLinkListDragAndDrop(customLinksList, readCustomLinks, saveCustomLinks, renderCustomLinks, {
      saveLabel: "追加リンクの順序を変更",
    });
  }

  function createLinkNode(link, index, links, section = "custom", options = {}) {
    const isPinnedSection = section === "pinned";
    const pinnedGroupId = isPinnedSection ? String(options.groupId || "").trim() : "";
    const item = document.createElement("li");
    item.className = `workspace-link-item${isPinnedSection ? " workspace-pinned-item" : ""}`;
    item.dataset.linkUrl = String(link.url || "");
    item.dataset.linkIndex = String(Number.isFinite(Number(index)) ? Number(index) : 0);

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
    openLink.setAttribute("aria-label", `${link.label} - ${link.url}`);
    openLink.textContent = link.label;

    const titleRow = document.createElement("div");
    titleRow.className = "workspace-link-title-row";

    const orderBadge = document.createElement("span");
    orderBadge.className = "workspace-link-order-badge";
    orderBadge.textContent = String(Number(index) + 1);
    titleRow.appendChild(orderBadge);

    const orderControls = document.createElement("div");
    orderControls.className = "workspace-link-order-controls";

    const moveUpButton = document.createElement("button");
    moveUpButton.type = "button";
    moveUpButton.className = "secondary workspace-order-button workspace-order-button-inline";
    moveUpButton.textContent = "↑";
    moveUpButton.setAttribute("aria-label", "上へ");
    moveUpButton.disabled = Number(index) <= 0;
    moveUpButton.addEventListener("click", () => {
      const current = isPinnedSection ? readPinnedLinksFromGroup(pinnedGroupId) : readCustomLinks();
      const currentIndex = Number.isFinite(Number(index)) ? Number(index) : -1;
      if (currentIndex <= 0 || currentIndex >= current.length) return;
      const next = current.slice();
      const [moved] = next.splice(currentIndex, 1);
      next.splice(currentIndex - 1, 0, moved);
      const saved = isPinnedSection ? savePinnedLinksToGroup(pinnedGroupId, next) : saveCustomLinks(next);
      if (!saved) {
        showToast(isPinnedSection ? "固定リンクの順序変更に失敗しました。" : "追加リンクの順序変更に失敗しました。", "error");
        return;
      }
      if (isPinnedSection) renderLinkLists(saved.links, saved.pinned_link_groups);
      else renderCustomLinks(next);
      showToast(isPinnedSection ? "固定リンクの順序を変更しました。" : "追加リンクの順序を変更しました。", "success");
    });

    const moveDownButton = document.createElement("button");
    moveDownButton.type = "button";
    moveDownButton.className = "secondary workspace-order-button workspace-order-button-inline";
    moveDownButton.textContent = "↓";
    moveDownButton.setAttribute("aria-label", "下へ");
    moveDownButton.disabled = Number(index) >= Math.max(0, (Array.isArray(links) ? links.length : 0) - 1);
    moveDownButton.addEventListener("click", () => {
      const current = isPinnedSection ? readPinnedLinksFromGroup(pinnedGroupId) : readCustomLinks();
      const currentIndex = Number.isFinite(Number(index)) ? Number(index) : -1;
      if (currentIndex < 0 || currentIndex >= current.length - 1) return;
      const next = current.slice();
      const [moved] = next.splice(currentIndex, 1);
      next.splice(currentIndex + 1, 0, moved);
      const saved = isPinnedSection ? savePinnedLinksToGroup(pinnedGroupId, next) : saveCustomLinks(next);
      if (!saved) {
        showToast(isPinnedSection ? "固定リンクの順序変更に失敗しました。" : "追加リンクの順序変更に失敗しました。", "error");
        return;
      }
      if (isPinnedSection) renderLinkLists(saved.links, saved.pinned_link_groups);
      else renderCustomLinks(next);
      showToast(isPinnedSection ? "固定リンクの順序を変更しました。" : "追加リンクの順序を変更しました。", "success");
    });

    orderControls.appendChild(moveUpButton);
    orderControls.appendChild(moveDownButton);
    titleRow.appendChild(orderControls);

    titleRow.appendChild(openLink);
    if (!isPinnedSection) {
      const duplicateButton = document.createElement("button");
      duplicateButton.type = "button";
      duplicateButton.className = "workspace-link-duplicate secondary";
      duplicateButton.textContent = "+";
      duplicateButton.setAttribute("aria-label", `${link.label} を複製`);
      duplicateButton.addEventListener("click", () => {
        const current = readCustomLinks();
        if (current.length >= MAX_LINKS) {
          showToast(`リンク数上限（${MAX_LINKS}件）に達しているため "${link.label}" を複製できません。`, "error");
          return;
        }
        const sourceIndex = Number.isFinite(Number(index)) ? Number(index) : -1;
        if (sourceIndex < 0 || sourceIndex >= current.length) return;
        const cloned = {
          ...current[sourceIndex],
          label: String(current[sourceIndex].label || ""),
          url: String(current[sourceIndex].url || ""),
        };
        const next = current.slice();
        next.splice(sourceIndex + 1, 0, cloned);
        const saved = saveCustomLinks(next);
        if (!saved) {
          showToast("追加リンクを複製できませんでした。", "error");
          return;
        }
        clearLinkUndoNotice();
        renderCustomLinks(next);
        showToast("リンクを複製しました。", "success");
      });
      titleRow.appendChild(duplicateButton);
    }
    head.appendChild(titleRow);

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
    noteEditor.placeholder = "このリンクの目的を記録";
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
    copyPromptButton.textContent = "プロンプトを送信";
    copyPromptButton.addEventListener("click", () => {
      void sendPromptForKey(promptKey, link);
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
    editLinkButton.textContent = "リンク名を編集";
    editLinkButton.addEventListener("click", () => {
      const nextLabelRaw = window.prompt("リンク名を変更しますか:", String(link.label || ""));
      if (nextLabelRaw === null) return;
      const fallbackLabel = formatUrlHost(link.url) || String(link.url || "");
      const nextLabel = normalizeText(nextLabelRaw, 80) || fallbackLabel;
      if (!nextLabel) {
        showToast("リンク名を入力してください。", "error");
        return;
      }

      const next = links.slice();
      next[index] = { label: nextLabel, url: String(link.url || "") };
      const linksSaved = isPinnedSection ? savePinnedLinksToGroup(pinnedGroupId, next) : saveCustomLinks(next);
      if (!linksSaved) {
        showToast("リンク名の更新に失敗しました。", "error");
        return;
      }

      if (activePromptKey === promptKey) {
        setActivePrompt(promptKey, { label: nextLabel, url: String(link.url || "") });
        if (promptEditor) updatePromptMeta(String(promptEditor.value || ""), "リンク名を更新しました。");
      }

      if (isPinnedSection) renderLinkLists(linksSaved.links, linksSaved.pinned_link_groups);
      else renderCustomLinks(next);
      showToast("リンク名を更新しました。", "success");
    });

    actions.appendChild(copyUrlButton);
    actions.appendChild(copyPromptButton);
    actions.appendChild(editPromptButton);
    actions.appendChild(editLinkButton);

    if (isPinnedSection) {
      const unpinButton = document.createElement("button");
      unpinButton.type = "button";
      unpinButton.className = "secondary workspace-unpin-link";
      unpinButton.textContent = "固定解除";
      unpinButton.addEventListener("click", () => {
        void demotePinnedLinkByUrl(link.url, { targetGroupId: pinnedGroupId, sourceIndex: index });
      });
      actions.appendChild(unpinButton);

      const dragHandle = document.createElement("button");
      dragHandle.type = "button";
      dragHandle.className = "secondary workspace-drag-handle";
      dragHandle.textContent = "並び替え";
      dragHandle.setAttribute("data-workspace-drag-handle", "");
      dragHandle.dataset.dragIndex = String(index);
      dragHandle.draggable = true;
      actions.appendChild(dragHandle);
    } else {
      const pinButton = document.createElement("button");
      pinButton.type = "button";
      pinButton.className = "secondary workspace-pin-link";
      pinButton.textContent = "固定化";
      pinButton.addEventListener("click", () => {
        void promoteCustomLinkToGroup(link.url);
      });
      actions.appendChild(pinButton);

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "step-reset";
      removeButton.textContent = "削除";
      removeButton.addEventListener("click", () => {
        const currentIndex = Number.isFinite(Number(index)) ? Number(index) : -1;
        const targetLabel = String(link.label || formatUrlHost(link.url) || "this link");
        showToastConfirmDialog(`"${targetLabel}"を削除しますか？`, {
          confirmText: "削除",
          cancelText: "キャンセル",
          type: "error",
          onConfirm: () => {
            const next = links.slice();
            const deleteIndex = Number.isFinite(Number(currentIndex)) ? Number(currentIndex) : -1;
            if (deleteIndex < 0 || deleteIndex >= next.length) {
              showToast("リンクの削除に失敗しました。", "error");
              return;
            }
            next.splice(deleteIndex, 1);
            const saved = saveCustomLinks(next);
            if (!saved) {
              showToast("リンクの削除に失敗しました。", "error");
              return;
            }
            clearLinkUndoNotice();
            renderCustomLinks(next);
            showToast("リンクを削除しました。", "success");
          },
        });
      });
      actions.appendChild(removeButton);

      const dragHandle = document.createElement("button");
      dragHandle.type = "button";
      dragHandle.className = "secondary workspace-drag-handle";
      dragHandle.textContent = "並び替え";
      dragHandle.setAttribute("data-workspace-drag-handle", "");
      dragHandle.dataset.dragIndex = String(index);
      dragHandle.draggable = true;
      actions.appendChild(dragHandle);
    }

    details.appendChild(actions);
    item.appendChild(main);
    item.appendChild(details);
    attachLinkDetailsToggle(item, urlToggleButton, false);
    return item;
  }

  function renderCustomLinks(links) {
    if (!customLinksList || !customLinksEmpty) return;
    customLinksList.innerHTML = "";
    const safeLinks = sanitizeLinkList(links, MAX_LINKS, true);
    safeLinks.forEach((link, index) => {
      customLinksList.appendChild(createLinkNode(link, index, safeLinks, "custom"));
    });
    customLinksEmpty.classList.toggle("hidden", safeLinks.length > 0);
    bindCustomLinkDragAndDrop();
  }

  function renderPinnedLinks(links) {
    const groups = readPinnedLinkGroups();
    const safeLinks = sanitizeLinkList(links, MAX_PINNED_LINKS);
    if (!groups.length) return;
    const nextGroups = groups.slice();
    nextGroups[0] = {
      ...nextGroups[0],
      links: safeLinks,
    };
    renderPinnedLinkGroups(nextGroups);
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
        void sendPromptForKey(key, resolvePromptContextFromButton(button));
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
    const pinnedLinkGroups = readPinnedLinkGroups();
    renderLinkLists(links, pinnedLinkGroups);
    bindStaticCopyButtons();
    bindLinkNoteEditors(document);
    bindLinkProfileEditors(document);
    bindWorkspaceMetadataToggle(document);
    if (linkForm && linkLabelInput && linkUrlInput) {
      linkForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const url = normalizeUrl(linkUrlInput.value);
        if (!url) {
          showToast("追加リンクを複製できませんでした。", "error");
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
          showToast("追加リンクを複製できませんでした。", "error");
          return;
        }
        const next = [{ label, url }, ...current].slice(0, MAX_LINKS);
        const saved = saveCustomLinks(next);
        if (!saved) {
          showToast("追加リンクを複製できませんでした。", "error");
          return;
        }
        if (!saveLinkNoteForKey(buildCustomPromptKey(url), purpose)) {
          showToast("追加リンクを複製できませんでした。", "error");
        }
        clearLinkUndoNotice();
        renderLinkLists(next, readPinnedLinkGroups());
        linkForm.reset();
        if (linkPurposeInput) linkPurposeInput.value = "";
        linkLabelInput.focus();
        showToast("リンクを複製しました。", "success");
      });
    }

      if (clearLinksButton) {
        clearLinksButton.addEventListener("click", () => {
          const currentLinks = readCustomLinks();
          if (currentLinks.length <= 0) {
            showToast("削除対象の追加リンクがありません。", "error");
            return;
          }
          showToastConfirmDialog("追加リンクを全て削除しますか？", {
            confirmText: "削除",
            cancelText: "キャンセル",
            type: "error",
            onConfirm: () => {
              const currentPinned = readPinnedLinkGroups();
              const saved = saveWorkspaceState([], currentPinned);
              if (!saved) {
                showToast("追加リンクの全削除に失敗しました。", "error");
                return;
              }
              clearLinkUndoNotice();
              renderLinkLists(saved.links, saved.pinned_link_groups);
              showToast("追加リンクを全削除しました。", "success");
            },
          });
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
    setPromptOptimizeButtonLoading(false);
    setPromptDiffVisibility(false);

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
        void copyHandoffSetForKey(activePromptKey, activePromptContext);
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
        if (!isObject(promptOptimizePreview)) return;
        const needsConfirmation = normalizePromptOptimizeList(promptOptimizePreview.needsConfirmation);
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

  const workspaceStateApi = {
    bootstrapWorkspaceState,
    readRawCustomLinks,
    readCustomLinks,
    readLinkNoteMap,
    readLinkProfileMap,
    readPromptMap,
    readActivePromptKey,
    savePromptMap,
    savePromptTextForKey,
    getPromptTextForKey,
    storeActivePromptKey,
    saveWorkspaceState,
    scheduleWorkspaceSync,
    collectLocalWorkspaceState,
    fetchWorkspaceStateFromServer,
    pushWorkspaceStateToServer,
    applyWorkspaceStateToLocalStorage,
    hasMeaningfulWorkspaceState,
    getLinkNoteForKey,
    getLinkProfileForKey,
    saveLinkNoteForKey,
    saveLinkProfileForKey,
  };

  const workspaceSyncApi = {
    bootstrapWorkspaceState,
    scheduleWorkspaceSync,
    readPromptMap,
    saveWorkspaceState,
    pushWorkspaceStateToServer,
    fetchWorkspaceStateFromServer,
    collectLocalWorkspaceState,
  };

  const workspaceLinksApi = {
    initializeLinks,
    renderLinkLists,
    renderPinnedLinkGroups,
    readPinnedLinkGroups,
    readPinnedLinksAll,
    saveCustomLinks,
    savePinnedLinkGroups,
    renderPinnedLinks,
    clearLinkUndoNotice,
    clearToast,
    showToastConfirmDialog,
    getAllPinnedLinksFromGroups,
    buildCustomPromptKey,
    readCustomLinks,
    readPinnedLinksFromGroup,
    readRawCustomLinks,
    getPinnedGroupIndexById,
    readPinnedLinks,
    getAllPinnedLinksFromGroups,
    createPinnedGroup,
    savePinnedLinksToGroup,
    promoteCustomLinkToGroup,
    demotePinnedLinkByUrl,
    demoteGroupLink,
    bindStaticCopyButtons,
    bindCustomLinkDragAndDrop,
    bindLinkListDragAndDrop,
    bindLinkNoteEditors,
    bindWorkspaceMetadataToggle,
    bindLinkProfileEditors,
    renderCustomLinks,
    renderPromptFronts,
    clearPromptUndoNotice,
    showLinkUndoNotice,
    updatePinnedCountMeta,
  };

  const workspacePromptApi = {
    initializePrompt,
    activatePromptEditorForKey,
    optimizeActivePrompt,
    getActivePromptKey,
    getActivePromptContext,
    getActivePromptState,
    copyHandoffSetForKey,
    resolvePromptContextFromButton,
    resolvePromptContextFromFront,
    renderPromptFronts,
    setActivePrompt,
    getPromptMapCached,
    closePromptOptimizePreview,
    getPromptTextForKey,
    sendPromptForKey,
    copyToClipboard,
    showPromptUndoNotice,
    applyPromptOptimizePreview,
    requestPromptOptimization,
    setPromptOptimizeButtonLoading,
    updatePromptMeta,
    buildDefaultPromptForKey,
    hasStoredPromptForKey,
    activePromptKey,
    activePromptContext,
    resolvePromptLabel,
    resolvePromptUrl,
    normalizePromptOptimizeList,
    getPromptOptimizePreview: () => (isObject(promptOptimizePreview) ? promptOptimizePreview : null),
  };

  const workspaceRenderApi = {
    renderPromptFrontElement,
    renderPromptFronts,
    renderLinkLists,
    renderPinnedLinkGroups,
    renderPinnedLinks,
    updatePromptMeta,
    setPromptOptimizeButtonLoading,
    setPromptDiffVisibility,
    renderPromptDiffList,
    createLinkNode,
    createPinnedGroupNode,
    renderCustomLinks,
    openPromptOptimizePreview,
    buildPromptPreview,
    renderProfileStatusForKey,
  };

  const dashboardWorkspace = window.DashboardWorkspace || {};
  dashboardWorkspace.state = Object.assign(dashboardWorkspace.state || {}, workspaceStateApi);
  dashboardWorkspace.links = Object.assign(dashboardWorkspace.links || {}, workspaceLinksApi);
  dashboardWorkspace.prompt = Object.assign(dashboardWorkspace.prompt || {}, workspacePromptApi);
  dashboardWorkspace.render = Object.assign(dashboardWorkspace.render || {}, workspaceRenderApi);
  dashboardWorkspace.sync = Object.assign(dashboardWorkspace.sync || {}, workspaceSyncApi);
  dashboardWorkspace.core = Object.assign(dashboardWorkspace.core || {}, {
    state: dashboardWorkspace.state,
    links: dashboardWorkspace.links,
    prompt: dashboardWorkspace.prompt,
    sync: dashboardWorkspace.sync,
    render: dashboardWorkspace.render,
  });
  window.DashboardWorkspace = dashboardWorkspace;

  window.DashboardWorkspaceState = dashboardWorkspace.state;
  window.DashboardWorkspaceLinks = dashboardWorkspace.links;
  window.DashboardWorkspacePrompt = dashboardWorkspace.prompt;
  window.DashboardWorkspaceSync = dashboardWorkspace.sync;
  window.DashboardWorkspaceRender = dashboardWorkspace.render;
})();
