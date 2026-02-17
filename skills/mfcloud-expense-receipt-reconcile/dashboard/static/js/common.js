(function () {
  // UI文言方針: toFriendlyMessage は利用者向けに日本語文言を返す。
  const toastEl = document.getElementById("toast");
  const THEME_STORAGE_KEY = "dashboard-theme";
  const THEME_LIGHT = "light";
  const THEME_DARK = "dark";
  const THEME_SYSTEM = "system";
  const THEME_VALUES = new Set([THEME_LIGHT, THEME_DARK]);
  const THEME_SELECTION_VALUES = new Set([THEME_LIGHT, THEME_DARK, THEME_SYSTEM]);
const DEFAULT_DASHBOARD_SIDEBAR_LINKS = Object.freeze([
    { href: "/", label: "ワークフロー", tab: "wizard" },
    { href: "/expense-workflow-copy", label: "ワークフロー（複製）", tab: "wizard-copy" },
    { href: "/kil-review", label: "KIL Review", tab: "kil-review" },
    { href: "/errors", label: "エラー", tab: "errors" },
    { href: "/workspace", label: "ワークスペース", tab: "workspace" },
  ]);
  let currentThemeSelection = THEME_SYSTEM;

  function showToast(message, type = "info") {
    if (!toastEl || !message) return;
    toastEl.textContent = message;
    toastEl.classList.remove("success", "error", "show");
    if (type === "success") toastEl.classList.add("success");
    if (type === "error") toastEl.classList.add("error");
    requestAnimationFrame(() => toastEl.classList.add("show"));
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2400);
  }

  function bindCopyButtons(root = document) {
    root.querySelectorAll(".copy-button").forEach((button) => {
      button.addEventListener("click", async () => {
        const targetId = button.dataset.copyTarget;
        const target = targetId ? document.getElementById(targetId) : null;
        const text = target ? target.textContent : "";
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
          button.textContent = "コピーしました";
          setTimeout(() => {
            button.textContent = "コピー";
          }, 1200);
        } catch {
          alert("クリップボードにコピーできませんでした。");
        }
      });
    });
  }

  function toFriendlyMessage(detail) {
    const text = String(detail || "");
    if (text.includes("Another run is already in progress")) return "すでに実行中の処理があります。完了してから再度お試しください。";
    if (text.includes("Template base timestamp is required for edit mode.")) return "編集時はベース更新日時が必要です。";
    if (text.includes("Template name is required.")) return "テンプレート名を入力してください。";
    if (text.includes("MF Cloud expense list URL is required.")) return "ソースURLを入力してください。";
    if (text.includes("Invalid year/month")) return "年月が正しくありません。";
    if (text.includes("MF Cloud expense list URL is required")) return "ソースURLを入力してください。";
    if (text.includes("Invalid year/month") || text.includes("Month must be")) return "年月の形式が正しくありません。YYYY-MM で確認してください。";
    if (text.includes("Missing amazon/orders.jsonl")) return "Amazonの注文データがありません。先にAmazonの領収書取得を実行してください。";
    if (text.includes("Missing mfcloud/expenses.jsonl")) return "MFクラウドの抽出データがありません。先にMF抽出を実行してください。";
    if (text.includes("Invalid mode")) return "実行モードが不正です。";
    if (text.includes("Workflow order violation")) return "実行順序が正しくありません。画面の次ステップ案内に従ってください。";
    if (text.includes("Run not found")) return "対象月の実行成果物がありません。先に領収書取得を実行してください。";
    if (text.includes("AMAZON_COVERAGE_THRESHOLD_NOT_MET")) return "Amazon取得率が基準(80%)未満のため失敗しました。再取得してください。";
    if (text.includes("menu_not_found")) return "Amazonの「領収書等」メニューが見つかりませんでした。画面表示を確認して再実行してください。";
    if (text.includes("link_not_resolved")) return "領収書リンクを解決できませんでした。注文カードの「領収書等」を確認してください。";
    if (text.includes("document_validation_failed")) return "領収書文書ページの検証に失敗しました。取得対象ページを確認してください。";
    if (text.includes("save_failed")) return "PDF保存に失敗しました。再実行してください。";
    if (text.includes("Cannot find package 'playwright'") || text.includes("ERR_MODULE_NOT_FOUND")) {
      return "Playwright依存が見つかりませんでした。初回起動の準備を行ってから再実行してください。";
    }
    if (text.includes("Failed to install Node dependencies")) {
      return "Node依存のセットアップに失敗しました。ネットワーク接続と npm の設定を確認してください。";
    }
    if (text.includes("Provider auto-download is disabled")) {
      return "手順3の自動取得は無効です。各サービスで手動取得した領収書を共通フォルダに置いてから「共通フォルダから取り込み」を実行してください。";
    }
    if (text === "Not Found") {
      return "APIエンドポイントが見つかりません。ダッシュボードを再起動して再試行してください。";
    }
    return text || "実行に失敗しました。ログを確認してください。";
  }

  function normalizeSearchText(text) {
    return String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function getSystemTheme() {
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      return THEME_DARK;
    }
    return THEME_LIGHT;
  }

  function readStoredTheme() {
    try {
      const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (storedTheme && THEME_SELECTION_VALUES.has(storedTheme)) return storedTheme;
    } catch {
      // localStorage blocked: ignore and fall back to system.
    }
    return THEME_SYSTEM;
  }

  function storeTheme(theme) {
    if (!THEME_SELECTION_VALUES.has(theme)) return;
    try {
      if (theme === THEME_SYSTEM) {
        window.localStorage.removeItem(THEME_STORAGE_KEY);
      } else {
        window.localStorage.setItem(THEME_STORAGE_KEY, theme);
      }
    } catch {
      // localStorage blocked: ignore.
    }
  }

  function applyTheme(theme) {
    currentThemeSelection = THEME_SELECTION_VALUES.has(theme) ? theme : THEME_SYSTEM;
    const resolvedTheme = currentThemeSelection === THEME_SYSTEM ? getSystemTheme() : currentThemeSelection;
    document.documentElement.setAttribute("data-theme", resolvedTheme);
    document.documentElement.setAttribute("data-theme-selection", currentThemeSelection);
    return resolvedTheme;
  }

  function updateThemeToggleState(activeThemeSelection) {
    document.querySelectorAll(".theme-toggle-button[data-theme-option]").forEach((button) => {
      const isActive = button.dataset.themeOption === activeThemeSelection;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
  }

  function buildThemeToggle() {
    const container = document.createElement("div");
    container.className = "theme-toggle";
    container.setAttribute("role", "group");
    container.setAttribute("aria-label", "表示テーマ");

    const options = [
      { theme: THEME_LIGHT, label: "ライト" },
      { theme: THEME_DARK, label: "ダーク" },
      { theme: THEME_SYSTEM, label: "システム" },
    ];

    options.forEach(({ theme, label }) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "theme-toggle-button";
      button.dataset.themeOption = theme;
      button.textContent = label;
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => {
        applyTheme(theme);
        storeTheme(theme);
        updateThemeToggleState(currentThemeSelection);
      });
      container.appendChild(button);
    });
    return container;
  }

  function mountThemeToggle() {
    const sidebar = document.querySelector(".dashboard-sidebar");
    if (!sidebar || sidebar.querySelector(".theme-toggle")) return;

    const section = document.createElement("div");
    section.className = "dashboard-sidebar-section";

    const heading = document.createElement("div");
    heading.className = "dashboard-sidebar-section-title";
    heading.textContent = "表示テーマ";
    section.appendChild(heading);

    section.appendChild(buildThemeToggle());
    sidebar.appendChild(section);
    updateThemeToggleState(currentThemeSelection);
  }

  function getSidebarConfig() {
    const page = document.querySelector(".page");
    if (!page) return DEFAULT_DASHBOARD_SIDEBAR_LINKS;
    const raw = page.dataset.sidebarLinks;
    if (!raw) return DEFAULT_DASHBOARD_SIDEBAR_LINKS;
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    } catch (_error) {
      // Keep defaults when custom links are missing or malformed.
    }
    return DEFAULT_DASHBOARD_SIDEBAR_LINKS;
  }

  function getActiveDashboardTab(pathname) {
    const normalized = (pathname || "").replace(/\/+$/, "");
    if (!normalized || normalized === "/") return "wizard";
    if (normalized === "/expense-workflow-copy") return "wizard-copy";
    if (normalized === "/status") return "status";
    if (normalized === "/kil-review") return "kil-review";
    if (normalized === "/errors") return "errors";
    if (normalized === "/workspace") return "workspace";
    if (normalized.startsWith("/runs/")) return "status";
    if (normalized.startsWith("/files/")) return "status";
    return "wizard";
  }

  function buildDashboardSidebar() {
    const page = document.querySelector(".page");
    const activeTab = page?.dataset?.activeTab || getActiveDashboardTab(window.location.pathname);
    const links = getSidebarConfig();

    const sidebar = document.createElement("aside");
    sidebar.className = "dashboard-sidebar";
    sidebar.setAttribute("aria-label", "ワークフロー");

    const nav = document.createElement("nav");
    nav.className = "dashboard-sidebar-nav";
    const title = document.createElement("div");
    title.className = "dashboard-sidebar-title";
    title.textContent = "ワークフロー";
    sidebar.appendChild(title);

    links.forEach((linkConfig) => {
      const item = document.createElement("a");
      item.href = linkConfig.href;
      item.className = "dashboard-sidebar-link";
      item.textContent = linkConfig.label;
      if (linkConfig.tab === activeTab) {
        item.classList.add("is-active");
        item.setAttribute("aria-current", "page");
      }
      nav.appendChild(item);
    });
    sidebar.appendChild(nav);
    return sidebar;
  }

  function mountDashboardSidebar() {
    const page = document.querySelector(".page");
    if (!page || page.querySelector(".dashboard-shell")) return;
    if (!page.children.length) return;

    const sidebar = buildDashboardSidebar();
    const mainContent = document.createElement("div");
    mainContent.className = "dashboard-main-content";

    while (page.firstChild) {
      mainContent.appendChild(page.firstChild);
    }

    const shell = document.createElement("div");
    shell.className = "dashboard-shell";
    shell.appendChild(sidebar);
    shell.appendChild(mainContent);
    page.appendChild(shell);
  }

  function bindSystemThemeSync() {
    if (!window.matchMedia) return;
    const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (currentThemeSelection !== THEME_SYSTEM) return;
      applyTheme(THEME_SYSTEM);
      updateThemeToggleState(currentThemeSelection);
    };
    if (typeof darkQuery.addEventListener === "function") {
      darkQuery.addEventListener("change", onChange);
      return;
    }
    if (typeof darkQuery.addListener === "function") {
      darkQuery.addListener(onChange);
    }
  }

  function initThemeToggle() {
    applyTheme(readStoredTheme());
    bindSystemThemeSync();
  }

  initThemeToggle();
  mountDashboardSidebar();
  mountThemeToggle();

  window.DashboardCommon = {
    applyTheme,
    bindCopyButtons,
    initThemeToggle,
    normalizeSearchText,
    showToast,
    storeTheme,
    toFriendlyMessage,
    updateThemeToggleState,
  };
})();
