(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});

  const STORAGE_LINKS_KEY = "mf-dashboard-workspace-links-v1";
  const STORAGE_PROMPT_KEY = "mf-dashboard-workspace-prompt-v1";
  const MAX_LINKS = 100;
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

    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "secondary workspace-copy-url";
    copyButton.textContent = "URLをコピー";
    copyButton.addEventListener("click", async () => {
      const ok = await copyToClipboard(link.url);
      if (ok) showToast("URLをコピーしました。", "success");
      else showToast("URLのコピーに失敗しました。", "error");
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

    actions.appendChild(copyButton);
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

  function readPromptDraft() {
    try {
      const raw = window.localStorage.getItem(STORAGE_PROMPT_KEY);
      if (!raw) return DEFAULT_PROMPT;
      const text = String(raw);
      if (text === LEGACY_DEFAULT_PROMPT) return DEFAULT_PROMPT;
      return text;
    } catch {
      return DEFAULT_PROMPT;
    }
  }

  function savePromptDraft(text) {
    try {
      window.localStorage.setItem(STORAGE_PROMPT_KEY, String(text || ""));
      updatePromptMeta(text, "保存しました。");
    } catch {
      updatePromptMeta(text, "保存できませんでした（ストレージ利用不可）。");
    }
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
    promptEditor.value = readPromptDraft();
    updatePromptMeta(promptEditor.value, "自動保存待機中。");

    let saveTimer = null;
    promptEditor.addEventListener("input", () => {
      updatePromptMeta(promptEditor.value, "編集中...");
      if (saveTimer) window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(() => {
        savePromptDraft(promptEditor.value);
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
        promptEditor.value = DEFAULT_PROMPT;
        savePromptDraft(promptEditor.value);
        updatePromptMeta(promptEditor.value, "テンプレートを復元しました。");
        showToast("テンプレートを復元しました。", "success");
      });
    }
  }

  initializeLinks();
  initializePrompt();
})();
