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
    { href: "/workspace", label: "HOME", tab: "workspace", section: "home" },
    { href: "/", label: "WorkFlow", tab: "wizard", section: "workflow" },
    { href: "/expense-workflow-copy", label: "WF作成テンプレート", tab: "wizard-copy", section: "admin" },
    { href: "/errors", label: "\u7ba1\u7406\u30bb\u30f3\u30bf\u30fc", tab: "errors", section: "admin" },
    { href: "/pptx-polish", label: "PowerPoint整形", tab: "pptx-polish", section: "admin" },
  ]);
  const AI_CHAT_STORAGE_KEY = "dashboard-ai-chat-v1";
  const AI_CHAT_MAX_MESSAGES = 40;
  const AI_CHAT_STATUS_ENDPOINT = "/api/ai/chat/status";
  const AI_CHAT_ENDPOINT = "/api/ai/chat";
  const SIDEBAR_STATE_STORAGE_KEY = "dashboard-sidebar-state";
  const SIDEBAR_MODE_STORAGE_KEY = "dashboard-sidebar-mode";
  const SIDEBAR_WIDTH_STORAGE_KEY = "dashboard-sidebar-width";
  const SIDEBAR_MODE_AUTO = "auto";
  const SIDEBAR_MODE_FIXED = "fixed";
  const SIDEBAR_STATE_EXPANDED = "expanded";
  const SIDEBAR_STATE_COLLAPSED = "collapsed";
  const SIDEBAR_STATE_HIDDEN = "hidden";
  const SIDEBAR_MODE_VALUES = new Set([SIDEBAR_MODE_AUTO, SIDEBAR_MODE_FIXED]);
  const SIDEBAR_STATE_VALUES = new Set([SIDEBAR_STATE_EXPANDED, SIDEBAR_STATE_COLLAPSED, SIDEBAR_STATE_HIDDEN]);
  const SIDEBAR_WIDTH_MIN = 240;
  const SIDEBAR_WIDTH_MAX = 360;
  const SIDEBAR_BREAKPOINT_DESKTOP = 1280;
  const SIDEBAR_BREAKPOINT_TABLET = 960;
  let currentThemeSelection = THEME_SYSTEM;
  let inMemoryAiChatMessages = [];
  let aiChatUi = null;

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
    if (text.includes("Template create/copy is disabled. Use edit mode only.")) return "テンプレートの新規作成・複製は無効です。既存テンプレートの更新のみ可能です。";
    if (text.includes("Template id is required. Creating new templates is disabled.")) return "新規テンプレート作成は無効です。既存テンプレートを選択してください。";
    if (text.includes("Template not found.")) return "対象テンプレートが見つかりません。画面を再読み込みして選び直してください。";
    if (text.includes("Template name is required.")) return "ワークフロー名を入力してください。";
    if (text.includes("Workflow page name is required.")) return "ワークフロー名を入力してください。";
    if (text.includes("Workflow page name already exists.")) return "同名のワークフローが既に存在します。";
    if (text.includes("Workflow page limit reached.")) return "ワークフローの上限に達しました。不要なページを整理してください。";
    if (text.includes("Workflow page was updated by another action.")) return "ページ設定が他の操作で更新されました。再読み込みしてやり直してください。";
    if (text.includes("Workflow page not found.")) return "対象のワークフローページが見つかりません。";
    if (text.includes("No updates.")) return "変更内容がありません。";
    if (text.includes("Invalid workflow page id.")) return "ワークフローページIDが不正です。";
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

  function normalizeSidebarWidth(value) {
    const width = Number(value);
    if (!Number.isFinite(width)) return null;
    const rounded = Math.round(width);
    return Math.max(SIDEBAR_WIDTH_MIN, Math.min(SIDEBAR_WIDTH_MAX, rounded));
  }

  function readStoredSidebarMode() {
    try {
      const mode = String(window.localStorage.getItem(SIDEBAR_MODE_STORAGE_KEY) || "").trim().toLowerCase();
      if (SIDEBAR_MODE_VALUES.has(mode)) return mode;
    } catch (_error) {
      // localStorage unavailable.
    }
    return SIDEBAR_MODE_AUTO;
  }

  function storeSidebarMode(mode) {
    if (!SIDEBAR_MODE_VALUES.has(mode)) return;
    try {
      window.localStorage.setItem(SIDEBAR_MODE_STORAGE_KEY, mode);
    } catch (_error) {
      // localStorage unavailable.
    }
  }

  function readStoredSidebarState() {
    try {
      const state = String(window.localStorage.getItem(SIDEBAR_STATE_STORAGE_KEY) || "").trim().toLowerCase();
      if (SIDEBAR_STATE_VALUES.has(state)) return state;
    } catch (_error) {
      // localStorage unavailable.
    }
    return SIDEBAR_STATE_EXPANDED;
  }

  function storeSidebarState(state) {
    if (!SIDEBAR_STATE_VALUES.has(state)) return;
    try {
      window.localStorage.setItem(SIDEBAR_STATE_STORAGE_KEY, state);
    } catch (_error) {
      // localStorage unavailable.
    }
  }

  function readStoredSidebarWidth() {
    try {
      const raw = window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY);
      return normalizeSidebarWidth(raw);
    } catch (_error) {
      // localStorage unavailable.
    }
    return null;
  }

  function storeSidebarWidth(width) {
    const normalized = normalizeSidebarWidth(width);
    if (normalized === null) return;
    try {
      window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(normalized));
    } catch (_error) {
      // localStorage unavailable.
    }
  }

  function getSidebarViewportKind() {
    const width = Number(window.innerWidth || 0);
    if (width >= SIDEBAR_BREAKPOINT_DESKTOP) return "desktop";
    if (width >= SIDEBAR_BREAKPOINT_TABLET) return "tablet";
    return "mobile";
  }

  function getDefaultSidebarState(viewportKind) {
    if (viewportKind === "desktop") return SIDEBAR_STATE_EXPANDED;
    if (viewportKind === "tablet") return SIDEBAR_STATE_COLLAPSED;
    return SIDEBAR_STATE_HIDDEN;
  }

  function normalizeSidebarStateForViewport(state, viewportKind) {
    const safeState = SIDEBAR_STATE_VALUES.has(state) ? state : getDefaultSidebarState(viewportKind);
    if (viewportKind === "mobile" && safeState === SIDEBAR_STATE_COLLAPSED) {
      return SIDEBAR_STATE_HIDDEN;
    }
    return safeState;
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
    if (normalized === "/workflow-pages/archived") return "errors";
    if (normalized === "/pptx-polish") return "pptx-polish";
    if (normalized === "/status") return "status";
    if (normalized === "/kil-review") return "errors";
    if (normalized === "/errors") return "errors";
    if (normalized === "/workspace") return "workspace";
    if (normalized.startsWith("/runs/")) return "status";
    if (normalized.startsWith("/files/")) return "status";
    return "wizard";
  }

  function splitSidebarLinks(links) {
    const homeLinks = [];
    const workflowLinks = [];
    const adminLinks = [];

    links.forEach((linkConfig) => {
      const section = String(linkConfig?.section || "").toLowerCase();
      if (section === "home") {
        homeLinks.push(linkConfig);
        return;
      }
      if (section === "admin") {
        adminLinks.push(linkConfig);
        return;
      }
      workflowLinks.push(linkConfig);
    });

    return { homeLinks, workflowLinks, adminLinks };
  }

  function buildSidebarNav(links, activeTab) {
    const normalizePath = (value) => {
      const text = String(value || "").trim();
      if (!text) return "/";
      const normalized = text.replace(/\/+$/, "");
      return normalized || "/";
    };
    const currentPath = normalizePath(window.location.pathname);
    const hasExactActive = links.some((linkConfig) => {
      try {
        const url = new URL(String(linkConfig?.href || ""), window.location.origin);
        return normalizePath(url.pathname) === currentPath;
      } catch {
        return false;
      }
    });
    const nav = document.createElement("nav");
    nav.className = "dashboard-sidebar-nav";

    links.forEach((linkConfig) => {
      const item = document.createElement("a");
      item.href = linkConfig.href;
      item.className = "dashboard-sidebar-link";
      const labelText = String(linkConfig.label || "");
      item.textContent = labelText;
      item.title = labelText;
      item.dataset.shortLabel = labelText.replace(/\s+/g, "").slice(0, 2) || "\u2022";
      let isActive = linkConfig.tab === activeTab;
      try {
        const url = new URL(String(linkConfig?.href || ""), window.location.origin);
        const samePath = normalizePath(url.pathname) === currentPath;
        isActive = hasExactActive ? samePath : isActive;
      } catch {
        // Keep fallback tab match.
      }
      if (isActive) {
        item.classList.add("is-active");
        item.setAttribute("aria-current", "page");
      }
      nav.appendChild(item);
    });

    return nav;
  }

  function buildSidebarSection(titleText, links, activeTab, options = {}) {
    if (!Array.isArray(links) || links.length === 0) return null;
    const section = document.createElement("div");
    section.className = "dashboard-sidebar-section";

    const heading = document.createElement("div");
    heading.className = "dashboard-sidebar-section-title";
    heading.textContent = titleText;
    section.appendChild(heading);
    const nav = buildSidebarNav(links, activeTab);
    if (options.searchable && links.length >= 4) {
      const searchInput = document.createElement("input");
      searchInput.type = "search";
      searchInput.className = "dashboard-sidebar-search";
      searchInput.placeholder = "ワークフロー検索";
      searchInput.setAttribute("aria-label", "ワークフロー検索");
      searchInput.addEventListener("input", () => {
        const query = normalizeSearchText(searchInput.value);
        nav.querySelectorAll(".dashboard-sidebar-link").forEach((link) => {
          const text = normalizeSearchText(link.textContent || "");
          const visible = !query || text.includes(query);
          link.hidden = !visible;
        });
      });
      section.appendChild(searchInput);
    }
    section.appendChild(nav);
    return section;
  }

  function buildSidebarModeSection() {
    const section = document.createElement("div");
    section.className = "dashboard-sidebar-section dashboard-sidebar-settings";

    const heading = document.createElement("div");
    heading.className = "dashboard-sidebar-section-title";
    heading.textContent = "表示モード";
    section.appendChild(heading);

    const group = document.createElement("div");
    group.className = "dashboard-sidebar-mode-group";
    section.appendChild(group);

    const options = [
      { value: SIDEBAR_MODE_AUTO, label: "自動" },
      { value: SIDEBAR_MODE_FIXED, label: "固定" },
    ];
    options.forEach(({ value, label }) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dashboard-sidebar-mode-button";
      button.dataset.sidebarMode = value;
      button.textContent = label;
      button.setAttribute("aria-pressed", "false");
      group.appendChild(button);
    });
    return section;
  }

  function buildDashboardSidebar() {
    const page = document.querySelector(".page");
    const activeTab = page?.dataset?.activeTab || getActiveDashboardTab(window.location.pathname);
    const links = getSidebarConfig();
    const { homeLinks, workflowLinks, adminLinks } = splitSidebarLinks(links);

    const sidebar = document.createElement("aside");
    sidebar.className = "dashboard-sidebar";
    sidebar.id = "dashboard-sidebar-panel";
    sidebar.setAttribute("tabindex", "-1");
    sidebar.setAttribute("aria-label", "ワークフロー");

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "dashboard-sidebar-close";
    closeButton.dataset.sidebarClose = "1";
    closeButton.setAttribute("aria-label", "サイドバーを閉じる");
    closeButton.textContent = "\u00d7";
    sidebar.appendChild(closeButton);

    const title = document.createElement("div");
    title.className = "dashboard-sidebar-title";
    title.textContent = "ホーム";
    sidebar.appendChild(title);
    sidebar.appendChild(buildSidebarNav(homeLinks, activeTab));

    const workflowSection = buildSidebarSection("ワークフロー系", workflowLinks, activeTab, { searchable: true });
    if (workflowSection) {
      sidebar.appendChild(workflowSection);
    }

    const adminSection = buildSidebarSection("管理系", adminLinks, activeTab);
    if (adminSection) {
      sidebar.appendChild(adminSection);
    }
    sidebar.appendChild(buildSidebarModeSection());

    const resizer = document.createElement("div");
    resizer.className = "dashboard-sidebar-resizer";
    resizer.dataset.sidebarResizer = "1";
    resizer.setAttribute("role", "separator");
    resizer.setAttribute("aria-orientation", "vertical");
    resizer.setAttribute("aria-label", "サイドバー幅を調整");
    resizer.tabIndex = 0;
    sidebar.appendChild(resizer);

    return sidebar;
  }

  function mountDashboardSidebar() {
    const page = document.querySelector(".page");
    if (!page || page.querySelector(".dashboard-shell")) return null;
    if (!page.children.length) return null;

    const sidebar = buildDashboardSidebar();
    const mainContent = document.createElement("div");
    mainContent.className = "dashboard-main-content";

    const shellActions = document.createElement("div");
    shellActions.className = "dashboard-shell-actions";

    const sidebarToggle = document.createElement("button");
    sidebarToggle.type = "button";
    sidebarToggle.className = "dashboard-sidebar-toggle";
    sidebarToggle.dataset.sidebarToggle = "1";
    sidebarToggle.setAttribute("aria-controls", sidebar.id);
    sidebarToggle.setAttribute("aria-expanded", "false");
    sidebarToggle.setAttribute("aria-label", "サイドバー切替");
    sidebarToggle.textContent = "サイドバー";
    shellActions.appendChild(sidebarToggle);
    mainContent.appendChild(shellActions);

    while (page.firstChild) {
      mainContent.appendChild(page.firstChild);
    }

    const shell = document.createElement("div");
    shell.className = "dashboard-shell";
    shell.appendChild(sidebar);
    shell.appendChild(mainContent);
    page.appendChild(shell);

    const backdrop = document.createElement("button");
    backdrop.type = "button";
    backdrop.className = "dashboard-sidebar-backdrop";
    backdrop.dataset.sidebarBackdrop = "1";
    backdrop.setAttribute("aria-label", "サイドバーを閉じる");
    backdrop.hidden = true;
    page.appendChild(backdrop);

    return {
      page,
      shell,
      sidebar,
      mainContent,
      sidebarToggle,
      backdrop,
    };
  }

  function initSidebarLayout(sidebarLayout) {
    if (!sidebarLayout || !sidebarLayout.shell || !sidebarLayout.sidebar) return;
    const { page, shell, sidebar, sidebarToggle, backdrop } = sidebarLayout;
    const closeButton = sidebar.querySelector("[data-sidebar-close]");
    const resizer = sidebar.querySelector("[data-sidebar-resizer]");
    const modeButtons = Array.from(sidebar.querySelectorAll("[data-sidebar-mode]"));

    let mode = readStoredSidebarMode();
    let state = readStoredSidebarState();
    let lastViewportKind = getSidebarViewportKind();
    let lastFocusedElement = null;
    let resizeSession = null;
    let resizePending = false;

    const storedWidth = readStoredSidebarWidth();
    if (storedWidth !== null) {
      page.style.setProperty("--sidebar-width-expanded", `${storedWidth}px`);
    }

    function updateModeButtons() {
      modeButtons.forEach((button) => {
        const isActive = button.dataset.sidebarMode === mode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
      });
    }

    function getCurrentExpandedWidth() {
      const inlineValue = normalizeSidebarWidth(page.style.getPropertyValue("--sidebar-width-expanded"));
      if (inlineValue !== null) return inlineValue;
      const computed = getComputedStyle(page).getPropertyValue("--sidebar-width-expanded");
      const computedValue = normalizeSidebarWidth(parseFloat(computed));
      if (computedValue !== null) return computedValue;
      const measured = normalizeSidebarWidth(sidebar.getBoundingClientRect().width);
      return measured !== null ? measured : SIDEBAR_WIDTH_MIN;
    }

    function setExpandedWidth(nextWidth, persist = false) {
      const normalized = normalizeSidebarWidth(nextWidth);
      if (normalized === null) return;
      page.style.setProperty("--sidebar-width-expanded", `${normalized}px`);
      if (persist) {
        storeSidebarWidth(normalized);
      }
    }

    function updateSidebarToggleLabel(viewportKind, isOpen) {
      if (viewportKind === "mobile") {
        sidebarToggle.textContent = isOpen ? "メニューを閉じる" : "メニューを開く";
        return;
      }
      if (viewportKind === "tablet") {
        sidebarToggle.textContent = isOpen ? "メニューを折りたたむ" : "メニューを展開";
        return;
      }
      if (state === SIDEBAR_STATE_COLLAPSED) {
        sidebarToggle.textContent = "サイドバーを展開";
        return;
      }
      if (state === SIDEBAR_STATE_HIDDEN) {
        sidebarToggle.textContent = "サイドバーを表示";
        return;
      }
      sidebarToggle.textContent = "サイドバーを折りたたむ";
    }

    function applySidebarLayout(options = {}) {
      const { persist = false, focusSidebar = false, resetForAuto = false } = options;
      const viewportKind = getSidebarViewportKind();
      if (mode === SIDEBAR_MODE_AUTO) {
        if (resetForAuto) {
          state = getDefaultSidebarState(viewportKind);
        } else {
          state = normalizeSidebarStateForViewport(state, viewportKind);
        }
      } else {
        state = normalizeSidebarStateForViewport(state, viewportKind);
      }

      const overlayMode = viewportKind === "mobile" || (viewportKind === "tablet" && state === SIDEBAR_STATE_EXPANDED);
      const isOpen = viewportKind === "mobile"
        ? state !== SIDEBAR_STATE_HIDDEN
        : viewportKind === "tablet"
          ? state === SIDEBAR_STATE_EXPANDED
          : state !== SIDEBAR_STATE_HIDDEN;
      const isCollapsed = !overlayMode && state === SIDEBAR_STATE_COLLAPSED;
      const isHidden = !overlayMode && state === SIDEBAR_STATE_HIDDEN;

      shell.classList.toggle("is-sidebar-overlay", overlayMode);
      shell.classList.toggle("is-sidebar-open", overlayMode && isOpen);
      shell.classList.toggle("is-sidebar-collapsed", isCollapsed);
      shell.classList.toggle("is-sidebar-hidden", isHidden);

      const backdropVisible = overlayMode && isOpen;
      backdrop.classList.toggle("is-visible", backdropVisible);
      backdrop.hidden = !backdropVisible;

      const ariaExpanded = state === SIDEBAR_STATE_EXPANDED;
      sidebarToggle.setAttribute("aria-expanded", String(ariaExpanded));
      sidebarToggle.dataset.sidebarState = state;
      page.dataset.sidebarState = state;
      page.dataset.sidebarMode = mode;
      updateSidebarToggleLabel(viewportKind, isOpen);
      updateModeButtons();

      if (persist && mode === SIDEBAR_MODE_FIXED) {
        storeSidebarState(state);
      }

      if (focusSidebar && overlayMode && isOpen) {
        const firstFocusable = sidebar.querySelector(
          "a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled])"
        );
        if (firstFocusable && typeof firstFocusable.focus === "function") {
          firstFocusable.focus();
        } else {
          sidebar.focus();
        }
      }
    }

    function closeOverlay(options = {}) {
      const { restoreFocus = true } = options;
      const viewportKind = getSidebarViewportKind();
      if (viewportKind === "mobile") {
        state = SIDEBAR_STATE_HIDDEN;
      } else if (viewportKind === "tablet") {
        state = SIDEBAR_STATE_COLLAPSED;
      } else if (state === SIDEBAR_STATE_HIDDEN) {
        return;
      }
      applySidebarLayout({ persist: true });
      if (restoreFocus && lastFocusedElement && typeof lastFocusedElement.focus === "function") {
        lastFocusedElement.focus();
      }
    }

    function toggleSidebar() {
      const viewportKind = getSidebarViewportKind();
      const wasExpanded = state === SIDEBAR_STATE_EXPANDED;
      if (!wasExpanded) {
        lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      }

      if (viewportKind === "desktop") {
        if (state === SIDEBAR_STATE_EXPANDED) {
          state = SIDEBAR_STATE_COLLAPSED;
        } else if (state === SIDEBAR_STATE_COLLAPSED) {
          state = SIDEBAR_STATE_HIDDEN;
        } else {
          state = SIDEBAR_STATE_EXPANDED;
        }
      } else if (viewportKind === "tablet") {
        state = state === SIDEBAR_STATE_EXPANDED ? SIDEBAR_STATE_COLLAPSED : SIDEBAR_STATE_EXPANDED;
      } else {
        state = state === SIDEBAR_STATE_HIDDEN ? SIDEBAR_STATE_EXPANDED : SIDEBAR_STATE_HIDDEN;
      }
      applySidebarLayout({ persist: true, focusSidebar: !wasExpanded, resetForAuto: false });
    }

    function canResizeSidebar() {
      return getSidebarViewportKind() === "desktop" && state === SIDEBAR_STATE_EXPANDED;
    }

    function stopSidebarResize() {
      if (!resizeSession) return;
      const finalWidth = resizeSession.width;
      resizeSession = null;
      window.removeEventListener("pointermove", onSidebarResizeMove);
      window.removeEventListener("pointerup", onSidebarResizeEnd);
      window.removeEventListener("pointercancel", onSidebarResizeEnd);
      if (finalWidth !== null) {
        setExpandedWidth(finalWidth, true);
      }
    }

    function onSidebarResizeMove(event) {
      if (!resizeSession) return;
      const nextWidth = resizeSession.startWidth + (event.clientX - resizeSession.startX);
      resizeSession.width = normalizeSidebarWidth(nextWidth);
      if (resizeSession.width !== null) {
        setExpandedWidth(resizeSession.width);
      }
    }

    function onSidebarResizeEnd() {
      stopSidebarResize();
    }

    if (resizer) {
      resizer.addEventListener("pointerdown", (event) => {
        if (!canResizeSidebar()) return;
        if (event.button !== 0) return;
        event.preventDefault();
        resizeSession = {
          startX: event.clientX,
          startWidth: getCurrentExpandedWidth(),
          width: null,
        };
        window.addEventListener("pointermove", onSidebarResizeMove);
        window.addEventListener("pointerup", onSidebarResizeEnd);
        window.addEventListener("pointercancel", onSidebarResizeEnd);
      });

      resizer.addEventListener("keydown", (event) => {
        if (!canResizeSidebar()) return;
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const delta = event.key === "ArrowRight" ? 12 : -12;
        const nextWidth = getCurrentExpandedWidth() + delta;
        setExpandedWidth(nextWidth, true);
      });
    }

    sidebarToggle.addEventListener("click", () => {
      toggleSidebar();
    });

    modeButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const nextMode = button.dataset.sidebarMode;
        if (!SIDEBAR_MODE_VALUES.has(nextMode)) return;
        mode = nextMode;
        storeSidebarMode(mode);
        if (mode === SIDEBAR_MODE_AUTO) {
          state = getDefaultSidebarState(getSidebarViewportKind());
        }
        applySidebarLayout({ persist: true, resetForAuto: true });
      });
    });

    if (closeButton) {
      closeButton.addEventListener("click", () => {
        closeOverlay();
      });
    }

    backdrop.addEventListener("click", () => {
      closeOverlay();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!shell.classList.contains("is-sidebar-overlay")) return;
      if (!shell.classList.contains("is-sidebar-open")) return;
      event.preventDefault();
      closeOverlay();
    });

    window.addEventListener("resize", () => {
      if (resizePending) return;
      resizePending = true;
      window.requestAnimationFrame(() => {
        resizePending = false;
        const nextViewportKind = getSidebarViewportKind();
        const shouldResetAuto = nextViewportKind !== lastViewportKind;
        lastViewportKind = nextViewportKind;
        applySidebarLayout({ resetForAuto: shouldResetAuto });
      });
    });

    applySidebarLayout({ resetForAuto: true });
    lastViewportKind = getSidebarViewportKind();
  }

  function sanitizeAiChatMessage(value) {
    const row = value && typeof value === "object" ? value : {};
    const role = String(row.role || "").trim().toLowerCase();
    if (role !== "user" && role !== "assistant") return null;
    const content = String(row.content || "").trim();
    if (!content) return null;
    return { role, content: content.slice(0, 4000) };
  }

  function normalizeAiChatMessages(value) {
    if (!Array.isArray(value)) return [];
    const out = [];
    value.forEach((row) => {
      const normalized = sanitizeAiChatMessage(row);
      if (!normalized) return;
      out.push(normalized);
    });
    if (out.length > AI_CHAT_MAX_MESSAGES) {
      return out.slice(out.length - AI_CHAT_MAX_MESSAGES);
    }
    return out;
  }

  function readAiChatMessages() {
    try {
      const raw = window.localStorage.getItem(AI_CHAT_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        const normalized = normalizeAiChatMessages(parsed);
        inMemoryAiChatMessages = normalized;
        if (!Array.isArray(parsed) || parsed.length !== normalized.length) {
          try {
            window.localStorage.setItem(AI_CHAT_STORAGE_KEY, JSON.stringify(normalized));
          } catch (_error) {
            // localStorage unavailable: keep in-memory state.
          }
        }
        return normalized;
      }
    } catch (_error) {
      try {
        window.localStorage.removeItem(AI_CHAT_STORAGE_KEY);
      } catch (_removeError) {
        // localStorage unavailable: fall back to in-memory buffer.
      }
    }
    return normalizeAiChatMessages(inMemoryAiChatMessages);
  }

  function writeAiChatMessages(messages) {
    const normalized = normalizeAiChatMessages(messages);
    inMemoryAiChatMessages = normalized;
    try {
      window.localStorage.setItem(AI_CHAT_STORAGE_KEY, JSON.stringify(normalized));
    } catch (_error) {
      // localStorage unavailable: keep in-memory state.
    }
    return normalized;
  }

  function pushAiChatMessage(messages, role, content) {
    const merged = [...normalizeAiChatMessages(messages), { role, content }];
    return writeAiChatMessages(merged);
  }

  function buildAiChatSidebar() {
    const root = document.createElement("aside");
    root.className = "dashboard-ai-chat";
    root.setAttribute("aria-label", "AIチャット");

    const head = document.createElement("div");
    head.className = "dashboard-ai-chat-head";
    root.appendChild(head);

    const title = document.createElement("div");
    title.className = "dashboard-ai-chat-title";
    title.textContent = "AIチャット";
    head.appendChild(title);

    const status = document.createElement("div");
    status.className = "dashboard-ai-chat-status";
    status.textContent = "初期化中...";
    status.dataset.state = "loading";
    head.appendChild(status);

    const log = document.createElement("div");
    log.className = "dashboard-ai-chat-log";
    log.setAttribute("aria-live", "polite");
    root.appendChild(log);

    const form = document.createElement("form");
    form.className = "dashboard-ai-chat-form";
    root.appendChild(form);

    const input = document.createElement("textarea");
    input.className = "dashboard-ai-chat-input";
    input.rows = 4;
    input.maxLength = 4000;
    input.placeholder = "メッセージを入力（例: /skill list）";
    form.appendChild(input);

    const actions = document.createElement("div");
    actions.className = "dashboard-ai-chat-actions";
    form.appendChild(actions);

    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.className = "secondary dashboard-ai-chat-clear";
    clearButton.textContent = "履歴クリア";
    actions.appendChild(clearButton);

    const sendButton = document.createElement("button");
    sendButton.type = "submit";
    sendButton.className = "primary dashboard-ai-chat-send";
    sendButton.textContent = "送信";
    actions.appendChild(sendButton);

    return {
      root,
      status,
      log,
      form,
      input,
      clearButton,
      sendButton,
      ready: false,
      pending: false,
      messages: readAiChatMessages(),
    };
  }

  function setAiChatStatus(ui, text, state = "info") {
    if (!ui || !ui.status) return;
    ui.status.textContent = String(text || "");
    ui.status.dataset.state = state;
  }

  function renderAiChatMessages(ui) {
    if (!ui || !ui.log) return;
    ui.log.innerHTML = "";
    if (!ui.messages.length) {
      const empty = document.createElement("div");
      empty.className = "dashboard-ai-chat-empty";
      empty.textContent = "履歴はまだありません。";
      ui.log.appendChild(empty);
      return;
    }
    ui.messages.forEach((row) => {
      const item = document.createElement("div");
      item.className = `dashboard-ai-chat-item is-${row.role}`;

      const bubble = document.createElement("div");
      bubble.className = "dashboard-ai-chat-bubble";
      bubble.textContent = String(row.content || "");
      item.appendChild(bubble);
      ui.log.appendChild(item);
    });
    ui.log.scrollTop = ui.log.scrollHeight;
  }

  function setAiChatFormEnabled(ui, enabled) {
    const active = Boolean(enabled);
    ui.input.disabled = !active;
    ui.sendButton.disabled = !active;
  }

  async function fetchAiChatStatus() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 9000);
    try {
      const res = await fetch(AI_CHAT_STATUS_ENDPOINT, {
        method: "GET",
        cache: "no-store",
        signal: controller.signal,
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        return { ready: false, reason: String(payload?.detail || `status=${res.status}`) };
      }
      return payload && typeof payload === "object" ? payload : { ready: false, reason: "invalid payload" };
    } catch (error) {
      return { ready: false, reason: String(error || "status request failed") };
    } finally {
      clearTimeout(timeout);
    }
  }

  function collectAiChatPageContext() {
    const page = document.querySelector(".page");
    const context = {
      path: String(window.location.pathname || "").slice(0, 200),
      active_tab: String(page?.dataset?.activeTab || "").slice(0, 200),
      title: String(document.title || "").slice(0, 200),
    };
    return context;
  }

  async function sendAiChat(ui, externalText = null) {
    if (!ui || ui.pending) return false;
    const hasExternalText = typeof externalText === "string";
    const text = hasExternalText ? String(externalText || "").trim() : String(ui.input.value || "").trim();
    if (!text) return false;
    if (!ui.ready) {
      showToast("AI APIが利用できません。設定を確認してください。", "error");
      return false;
    }

    ui.pending = true;
    ui.messages = pushAiChatMessage(ui.messages, "user", text);
    if (!hasExternalText) ui.input.value = "";
    renderAiChatMessages(ui);
    setAiChatStatus(ui, "回答を生成中...", "loading");
    setAiChatFormEnabled(ui, false);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
      const res = await fetch(AI_CHAT_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: ui.messages,
          page_context: collectAiChatPageContext(),
        }),
        signal: controller.signal,
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(String(payload?.detail || `status=${res.status}`));
      }
      const reply = sanitizeAiChatMessage(payload?.reply || {});
      if (!reply || reply.role !== "assistant") {
        throw new Error("AI response is invalid.");
      }
      ui.messages = pushAiChatMessage(ui.messages, "assistant", reply.content);
      renderAiChatMessages(ui);
      setAiChatStatus(ui, `接続中: ${String(payload?.model || "gemini")}`, "success");
      return true;
    } catch (error) {
      setAiChatStatus(ui, "送信に失敗しました。", "error");
      showToast(toFriendlyMessage(error), "error");
      return false;
    } finally {
      clearTimeout(timeout);
      ui.pending = false;
      setAiChatFormEnabled(ui, ui.ready);
      ui.input.focus();
    }
  }

  async function sendAiChatMessage(text) {
    const message = String(text || "").trim();
    if (!message) {
      showToast("送信するメッセージが空です。", "error");
      return false;
    }
    if (message.length > 4000) {
      showToast("メッセージが長すぎます（最大4000文字）。", "error");
      return false;
    }
    if (!aiChatUi) {
      await initAiChatSidebar();
    }
    if (!aiChatUi) {
      showToast("AIチャットを初期化できませんでした。", "error");
      return false;
    }
    if (aiChatUi.pending) {
      showToast("AIチャットの応答待ちです。完了後に再実行してください。", "error");
      return false;
    }
    return sendAiChat(aiChatUi, message);
  }

  async function initAiChatSidebar() {
    const shell = document.querySelector(".dashboard-shell");
    if (!shell || shell.querySelector(".dashboard-ai-chat")) return;

    const ui = buildAiChatSidebar();
    aiChatUi = ui;
    shell.appendChild(ui.root);
    renderAiChatMessages(ui);

    ui.form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await sendAiChat(ui);
    });

    ui.input.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      event.preventDefault();
      await sendAiChat(ui);
    });

    ui.clearButton.addEventListener("click", () => {
      ui.messages = writeAiChatMessages([]);
      renderAiChatMessages(ui);
      setAiChatStatus(ui, ui.ready ? "履歴をクリアしました。" : "履歴をクリアしました（未接続）。", "info");
    });

    const status = await fetchAiChatStatus();
    ui.ready = Boolean(status?.ready);
    if (ui.ready) {
      const model = String(status?.model || "gemini");
      setAiChatStatus(ui, `接続中: ${model}`, "success");
      setAiChatFormEnabled(ui, true);
    } else {
      const reason = String(status?.reason || "AI APIの設定が必要です。");
      setAiChatStatus(ui, `未接続: ${reason}`, "error");
      setAiChatFormEnabled(ui, false);
    }
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
  const sidebarLayout = mountDashboardSidebar();
  mountThemeToggle();
  initSidebarLayout(sidebarLayout);
  initAiChatSidebar();

  window.DashboardCommon = {
    applyTheme,
    bindCopyButtons,
    fetchAiChatStatus,
    initAiChatSidebar,
    initThemeToggle,
    normalizeSearchText,
    sendAiChatMessage,
    showToast,
    storeTheme,
    toFriendlyMessage,
    updateThemeToggleState,
  };
})();
