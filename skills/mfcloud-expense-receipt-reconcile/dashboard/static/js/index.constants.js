  // UI copy is centralized in this file.
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const pageEl = document.querySelector(".page");
  const form = document.getElementById("run-form");
  const logEl = document.getElementById("run-log");
  const errorBox = document.getElementById("error-box");
  const stopButton = document.getElementById("stop-run");
  const wizardNext = document.getElementById("wizard-next");
  const latestRunDotEl = document.querySelector("[data-latest-run-dot]");
  const latestRunStatusEl = document.querySelector("[data-latest-run-status]");
  const latestRunTimeEl = document.querySelector("[data-latest-run-time]");
  const latestRunIdEl = document.querySelector("[data-latest-run-id]");
  const latestRunYmEl = document.querySelector("[data-latest-run-ym]");
  const latestRunLinkEl = document.querySelector("[data-latest-run-link]");
  const logRunIdEl = document.querySelector("[data-log-run-id]");
  const logRunStatusEl = document.querySelector("[data-log-run-status]");

  const runStatusById = {};
  let awaitingRunFinalization = false;
  let stepRetryTimer = null;
  let activeLogRunId = "";
  let stepRefreshInFlight = false;
  let stepRefreshStartedAt = 0;
  let stepFocusTimer = null;
  let autoReloadScheduled = false;
  const REQUEST_TIMEOUT_MS = 12000;
  const STEP_REFRESH_STALE_MS = 15000;
  const archiveStateOverrides = Object.create(null);
  const PROVIDER_SOURCE_SETUP_GUIDE_URL =
    "https://github.com/Igasawa/Skills-personal/blob/main/skills/mfcloud-expense-receipt-reconcile/SKILL.md";

  const monthCloseChecklistKeys = ["expense_submission", "document_printout", "mf_accounting_link"];
  const YM_STORAGE_KEY = "mfcloud.dashboard.selectedYm";
  const YM_PATTERN = /^(\d{4})-(\d{2})$/;
  const TEMPLATE_STEP_DEFAULT_ACTION = "";
  // Canonical action list is mirror of API validation (`WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS`)
  // and scheduler action whitelist (`SCHEDULER_ALLOWED_ACTION_KEYS`).
  const TEMPLATE_STEP_ACTIONS = [
    { value: "preflight", label: "手順0（準備）" },
    { value: "preflight_mf", label: "手順0（MFのみ）" },
    { value: "amazon_download", label: "手順1（Amazon取得）" },
    { value: "rakuten_download", label: "手順2（楽天取得）" },
    { value: "amazon_print", label: "Amazon除外判断・印刷" },
    { value: "rakuten_print", label: "楽天除外判断・印刷" },
    { value: "provider_ingest", label: "手順3（共通フォルダ取り込み）" },
    { value: "mf_bulk_upload_task", label: "手順4（MF一括アップロード）" },
    { value: "month_close", label: "手順6（月次クローズ）" },
  ];
  const TEMPLATE_STEP_ACTION_LABELS = Object.fromEntries(TEMPLATE_STEP_ACTIONS.map((item) => [item.value, item.label]));
  const TEMPLATE_STEP_TYPES = [
    { value: "manual", label: "人" },
    { value: "agent", label: "AI" },
    { value: "browser", label: "AI（browser）" },
  ];
  const TEMPLATE_STEP_TYPE_VALUES = new Set(TEMPLATE_STEP_TYPES.map((item) => item.value));
  const TEMPLATE_STEP_TRIGGERS = [
    { value: "manual", label: "手動実行" },
    { value: "schedule", label: "スケジュール" },
    { value: "webhook", label: "Webhook" },
    { value: "after_step", label: "前手順完了後" },
  ];
  const TEMPLATE_STEP_TRIGGER_VALUES = new Set(TEMPLATE_STEP_TRIGGERS.map((item) => item.value));
  const TEMPLATE_STEP_TRIGGER_KINDS = [
    { value: "manual_start", label: "手動開始" },
    { value: "scheduled", label: "スケジュール" },
    { value: "external_event", label: "外部イベント" },
    { value: "after_previous", label: "前手順完了後" },
  ];
  const TEMPLATE_STEP_TRIGGER_KIND_VALUES = new Set(TEMPLATE_STEP_TRIGGER_KINDS.map((item) => item.value));
  const TEMPLATE_STEP_EXECUTION_MODES = [
    { value: "manual_confirm", label: "手動確認" },
    { value: "auto", label: "自動" },
  ];
  const TEMPLATE_STEP_EXECUTION_MODE_VALUES = new Set(TEMPLATE_STEP_EXECUTION_MODES.map((item) => item.value));
  const TEMPLATE_STEP_MAX_AGENT_PROMPT_CHARS = 4000;
  const TEMPLATE_STEP_UI_MODE = {
    compact: "compact",
    advanced: "advanced",
  };
  const TEMPLATE_STEP_UI_MODE_DEFAULT = TEMPLATE_STEP_UI_MODE.compact;
  const AUTO_TIMER_LABEL_OFF = "+";
  const AUTO_TIMER_LABEL_ON = "-";
  const TEMPLATE_REQUIRED_STEPS = [];
  const TEMPLATE_REQUIRED_STEP_ACTION_SET = new Set(TEMPLATE_REQUIRED_STEPS.map((row) => row.action));
  const TEMPLATE_STEP_DEFAULT_TITLES = {
    preflight: "",
    preflight_mf: "手順0 MF再取得のみ",
    amazon_download: "手順1 Amazon領収書取得",
    amazon_print: "手順1 Amazon除外判断・印刷",
    rakuten_download: "手順2 楽天領収書取得",
    rakuten_print: "手順2 楽天除外判断・印刷",
    provider_ingest: "手順3 共通フォルダ取り込み",
    mf_bulk_upload_task: "手順4 MF一括アップロード",
    month_close: "手順6 月次クローズ",
  };
  const WORKFLOW_STEP_BLOCK_KEYS_BY_ACTION = {
    preflight: "preflight",
    preflight_mf: "preflight",
    amazon_download: "amazon",
    amazon_print: "amazon",
    rakuten_download: "rakuten",
    rakuten_print: "rakuten",
    provider_ingest: "provider_ingest",
    mf_bulk_upload_task: "mf_bulk_upload_task",
    month_close: "month_close",
  };
  const WORKFLOW_STEP_BLOCK_SELECTORS = {
    preflight: "#step-preflight",
    amazon: "#step-amazon-task",
    rakuten: "#step-rakuten-task",
    provider_ingest: "#step-provider-ingest",
    mf_bulk_upload_task: "#step-mf-bulk-upload-task",
    month_close: "#step-month-close",
  };
  const WORKFLOW_ACTIONS_BY_BLOCK_KEY = {
    preflight: ["preflight", "preflight_mf"],
    amazon: ["amazon_download", "amazon_print"],
    rakuten: ["rakuten_download", "rakuten_print"],
    provider_ingest: ["provider_ingest"],
    mf_bulk_upload_task: ["mf_bulk_upload_task"],
    month_close: ["month_close"],
  };
  const WORKFLOW_STEP_BLOCK_ORDER = [
    "preflight",
    "amazon",
    "rakuten",
    "provider_ingest",
    "mf_bulk_upload_task",
    "month_close",
  ];
  const TEMPLATE_STEP_ACTION_VALUES = new Set(TEMPLATE_STEP_ACTIONS.map((item) => item.value));
  const templateSaveState = { inFlight: false };
  const workflowPageCreateState = { inFlight: false };
  let activeTemplateStepDragRow = null;
  const TEMPLATE_MODE_CONFIG = {
    edit: {
      chip: "編集",
      saveLabel: "作成テンプレートを更新",
      description: "作成元テンプレートを編集中です。保存すると現在のテンプレート設定を更新します。",
      summary: "フォームモード: 編集",
      successMessage: "作成テンプレートを更新しました。",
    },
  };


window.DashboardIndexConstants = {
  Common,
  showToast,
  toFriendlyMessage,
  bindCopyButtons,
  pageEl,
  form,
  logEl,
  errorBox,
  stopButton,
  wizardNext,
  latestRunDotEl,
  latestRunStatusEl,
  latestRunTimeEl,
  latestRunIdEl,
  latestRunYmEl,
  latestRunLinkEl,
  logRunIdEl,
  logRunStatusEl,
  runStatusById,
  awaitingRunFinalization,
  stepRetryTimer,
  activeLogRunId,
  stepRefreshInFlight,
  stepRefreshStartedAt,
  stepFocusTimer,
  autoReloadScheduled,
  REQUEST_TIMEOUT_MS,
  STEP_REFRESH_STALE_MS,
  archiveStateOverrides,
  PROVIDER_SOURCE_SETUP_GUIDE_URL,
  monthCloseChecklistKeys,
  YM_STORAGE_KEY,
  YM_PATTERN,
  TEMPLATE_STEP_DEFAULT_ACTION,
  TEMPLATE_STEP_ACTIONS,
  TEMPLATE_STEP_ACTION_LABELS,
  TEMPLATE_STEP_TYPES,
  TEMPLATE_STEP_TYPE_VALUES,
  TEMPLATE_STEP_TRIGGERS,
  TEMPLATE_STEP_TRIGGER_VALUES,
  TEMPLATE_STEP_TRIGGER_KINDS,
  TEMPLATE_STEP_TRIGGER_KIND_VALUES,
  TEMPLATE_STEP_EXECUTION_MODES,
  TEMPLATE_STEP_EXECUTION_MODE_VALUES,
  TEMPLATE_STEP_MAX_AGENT_PROMPT_CHARS,
  TEMPLATE_REQUIRED_STEPS,
  TEMPLATE_REQUIRED_STEP_ACTION_SET,
  TEMPLATE_STEP_DEFAULT_TITLES,
  WORKFLOW_STEP_BLOCK_KEYS_BY_ACTION,
  WORKFLOW_STEP_BLOCK_SELECTORS,
  WORKFLOW_ACTIONS_BY_BLOCK_KEY,
  WORKFLOW_STEP_BLOCK_ORDER,
  TEMPLATE_STEP_ACTION_VALUES,
  templateSaveState,
  TEMPLATE_STEP_UI_MODE,
  TEMPLATE_STEP_UI_MODE_DEFAULT,
  AUTO_TIMER_LABEL_OFF,
  AUTO_TIMER_LABEL_ON,
  workflowPageCreateState,
  activeTemplateStepDragRow,
  TEMPLATE_MODE_CONFIG,
};
