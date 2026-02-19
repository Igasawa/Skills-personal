from __future__ import annotations

from pathlib import Path
import re

from fastapi import FastAPI
import pytest

from dashboard.routes import api as api_routes


def test_api_router_registers_expected_routes() -> None:
    app = FastAPI()
    app.include_router(api_routes.create_api_router())
    api_paths = {
        route.path
        for route in app.router.routes
        if isinstance(getattr(route, "path", None), str) and str(route.path).startswith("/api/")
    }

    expected_paths = {
        "/api/archive/{ym}",
        "/api/errors/doc-update/run",
        "/api/errors/document-freshness",
        "/api/errors/incidents",
        "/api/errors/incidents/{incident_id}",
        "/api/errors/incidents/{incident_id}/archive",
        "/api/errors/incidents/{incident_id}/go",
        "/api/errors/incidents/{incident_id}/plan",
        "/api/errors/incidents/plan-all",
        "/api/exclusions/{ym}",
        "/api/folder/{ym}/receipts",
        "/api/folders/open-receipts",
        "/api/folders/receipt",
        "/api/folders/{ym}/manual-inbox",
        "/api/folders/{ym}/mf-bulk-inbox",
        "/api/folders/{ym}/mf-csv-inbox",
        "/api/folders/{ym}/open-receipts",
        "/api/folders/{ym}/provider-inbox/{provider}",
        "/api/folders/{ym}/provider-skipped/latest",
        "/api/folders/{ym}/provider-source",
        "/api/folders/{ym}/receipt",
        "/api/folders/{ym}/receipts",
        "/api/kil-review",
        "/api/manual/{ym}/import",
        "/api/mf-bulk-upload/{ym}",
        "/api/mf-csv-import/{ym}",
        "/api/mf-draft-actions/{ym}",
        "/api/month-close-checklist/{ym}",
        "/api/month-close/{ym}",
        "/api/print-pdf/{ym}/{source}/{filename}",
        "/api/print-run/{ym}",
        "/api/print-run/{ym}/{source}",
        "/api/print/{ym}/{source}",
        "/api/print/{ym}/{source}/complete",
        "/api/provider-import/{ym}/result",
        "/api/providers/{ym}/download",
        "/api/providers/{ym}/import",
        "/api/providers/{ym}/print-run",
        "/api/runs",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/stop",
        "/api/scheduler/state",
        "/api/steps/{ym}",
        "/api/steps/{ym}/reset/{step_id}",
        "/api/workflow-pages",
        "/api/workflow-pages/{workflow_page_id}",
        "/api/workflow-templates",
        "/api/workflow-templates/{template_id}",
        "/api/workspace/state",
    }

    assert expected_paths.issubset(api_paths)


def test_create_api_router_delegates_to_registrar_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _record(name: str):
        def _fake(**kwargs: object) -> None:
            calls.append(name)

        return _fake

    monkeypatch.setattr(api_routes, "register_api_folder_endpoints", _record("folder"))
    monkeypatch.setattr(api_routes, "register_api_print_endpoints", _record("print"))
    monkeypatch.setattr(api_routes, "register_api_run_endpoints", _record("run"))
    monkeypatch.setattr(api_routes, "register_api_workflow_endpoints", _record("workflow"))
    monkeypatch.setattr(api_routes, "register_builtin_api_run_routes", _record("builtin"))
    monkeypatch.setattr(api_routes, "register_api_kil_review_routes", _record("kil"))

    api_routes.create_api_router()

    assert calls == ["folder", "print", "run", "workflow", "builtin", "kil"]


def test_dashboard_templates_reference_expected_script_chunks() -> None:
    base = Path(__file__).resolve().parents[1] / "dashboard" / "templates"
    html = {
        base / "index.html": [
            "/static/js/common.js",
            "/static/js/index.constants.js",
            "/static/js/index.state.js",
            "/static/js/index.api.js",
            "/static/js/index.render.js",
            "/static/js/index.events.js",
            "/static/js/index.js",
        ],
        base / "status.html": [
            "/static/js/common.js",
            "/static/js/index.constants.js",
            "/static/js/index.state.js",
            "/static/js/index.api.js",
            "/static/js/index.render.js",
            "/static/js/index.events.js",
            "/static/js/index.js",
        ],
        base / "expense_workflow_copy.html": [
            "/static/js/common.js",
            "/static/js/index.constants.js",
            "/static/js/index.state.js",
            "/static/js/index.api.js",
            "/static/js/index.render.js",
            "/static/js/index.events.js",
            "/static/js/index.js",
            "/static/js/scheduler.js",
        ],
    }

    for path, expected_scripts in html.items():
        text = path.read_text(encoding="utf-8")
        scripts = re.findall(r'<script src="([^"]+)"', text)
        previous = -1
        for expected in expected_scripts:
            assert expected in scripts
            current = scripts.index(expected)
            assert current > previous
            previous = current


def test_dashboard_index_js_exports_contract() -> None:
    base = Path(__file__).resolve().parents[1] / "dashboard" / "static" / "js"
    checks = {
        base / "index.constants.js": (
            "window.DashboardIndexConstants",
            [
                "Common",
                "showToast",
                "toFriendlyMessage",
                "bindCopyButtons",
                "pageEl",
                "form",
                "logEl",
                "errorBox",
                "stopButton",
                "wizardNext",
                "latestRunDotEl",
                "latestRunStatusEl",
                "latestRunTimeEl",
                "latestRunIdEl",
                "latestRunYmEl",
                "latestRunLinkEl",
                "logRunIdEl",
                "logRunStatusEl",
                "runStatusById",
                "awaitingRunFinalization",
                "stepRetryTimer",
                "activeLogRunId",
                "stepRefreshInFlight",
                "stepRefreshStartedAt",
                "stepFocusTimer",
                "autoReloadScheduled",
                "REQUEST_TIMEOUT_MS",
                "STEP_REFRESH_STALE_MS",
                "archiveStateOverrides",
                "PROVIDER_SOURCE_SETUP_GUIDE_URL",
                "monthCloseChecklistKeys",
                "YM_STORAGE_KEY",
                "YM_PATTERN",
                "TEMPLATE_STEP_DEFAULT_ACTION",
                "TEMPLATE_STEP_ACTIONS",
                "TEMPLATE_STEP_ACTION_LABELS",
                "TEMPLATE_REQUIRED_STEPS",
                "TEMPLATE_REQUIRED_STEP_ACTION_SET",
                "TEMPLATE_STEP_DEFAULT_TITLES",
                "WORKFLOW_STEP_BLOCK_KEYS_BY_ACTION",
                "WORKFLOW_STEP_BLOCK_SELECTORS",
                "WORKFLOW_ACTIONS_BY_BLOCK_KEY",
                "WORKFLOW_STEP_BLOCK_ORDER",
                "TEMPLATE_STEP_ACTION_VALUES",
                "templateSaveState",
                "workflowPageCreateState",
                "activeTemplateStepDragRow",
                "TEMPLATE_MODE_CONFIG",
            ],
        ),
        base / "index.state.js": (
            "window.DashboardIndexState",
            [
                "normalizeYm",
                "parseYm",
                "parseWorkflowTemplate",
                "parseWorkflowPage",
                "workflowTemplate",
                "workflowPage",
                "defaultTitleForStepAction",
                "normalizeTemplateStepAutoRun",
                "normalizeTemplateStepOrder",
                "normalizeTemplateStepExecutionLog",
                "normalizeTemplateStepTimerForAutoRun",
                "normalizeWorkflowStepRows",
                "isRequiredTemplateStepAction",
                "actionToWorkflowBlockKey",
                "nextAvailableTemplateStepAction",
                "getTemplateMode",
                "getTemplateModeConfig",
                "syncTemplatePageHeader",
                "normalizeTemplateSourceUrls",
                "isValidHttpUrl",
                "getTemplateSourceUrlListEl",
                "getTemplateSourceUrlRows",
                "getTemplateSourceUrlInputs",
                "collectTemplateSourceUrls",
                "getPrimaryTemplateSourceUrl",
                "setTemplateSourceUrlInputNames",
                "refreshTemplateSourceUrlRowMeta",
                "validateTemplateSourceUrls",
                "ensureTemplateSourceUrlRows",
                "addTemplateSourceUrlRow",
                "getTemplateStepsListEl",
                "getTemplateStepRows",
                "getTemplateStepActionOptionsHtml",
                "normalizeTemplateStepAction",
                "generateTemplateStepId",
                "emitTemplateStepsChanged",
                "normalizeTemplateStepTimerMinutes",
                "parseTemplateStepExecutionLogFromRow",
                "formatTemplateStepLatestExecutionLog",
                "setTemplateStepExecutionLogOnRow",
                "getTemplateStepDragAfterRow",
                "ensureTemplateStepDnDBindings",
                "parseTemplateStepRow",
                "refreshTemplateStepRows",
                "validateTemplateStepRows",
                "collectTemplateSteps",
                "addTemplateStepFromDefaultCard",
                "hydrateTemplateSteps",
                "hydrateTemplateSourceUrls",
                "applyTemplateModeUI",
                "getTemplateIdFromForm",
                "getTemplateSourceIdFromForm",
                "getTemplateUpdatedAtFromForm",
                "shouldSyncYmQueryParams",
                "readYmFromQueryString",
                "readYmFromLocalStorage",
                "persistYmSelection",
                "restoreYmSelection",
                "normalizeChecklistState",
                "isChecklistComplete",
                "formatDateTimeInJst",
                "nowIsoLikeInJst",
            ],
        ),
        base / "index.api.js": (
            "window.DashboardIndexApi",
            [
                "apiGetJson",
                "showError",
                "clearError",
                "scheduleStepSync",
                "fetchStatus",
                "isStepReflected",
                "syncAfterRunCompletion",
                "startLogPolling",
                "stopLogPolling",
                "normalizeStatusForDot",
                "toYmText",
                "updateRunSummary",
                "refreshLog",
                "buildPayload",
                "resolveFormYearMonth",
                "buildTemplatePayload",
                "buildWorkflowPagePayload",
                "createWorkflowPage",
                "editWorkflowPageSettings",
                "archiveCurrentWorkflowPage",
                "showWorkflowPageStepEditorModal",
                "saveWorkflowPageSteps",
                "editWorkflowPageSteps",
                "rollbackWorkflowPageSteps",
                "saveWorkflowTemplate",
                "startRun",
                "prependArchiveHistoryRow",
                "runArchiveAction",
                "importManualReceipts",
                "openMfBulkInbox",
                "runMfBulkUpload",
                "openMfCsvInbox",
                "runMfCsvImport",
                "runManualAction",
                "providerLabel",
                "openProviderInbox",
                "openProviderSource",
                "importProviderReceipts",
                "printProviderReceipts",
                "runProviderAction",
            ],
        ),
        base / "index.render.js": (
            "window.DashboardIndexRender",
            [
                "getYmFromForm",
                "setStepStatus",
                "setTaskStatus",
                "renderNextStep",
                "recordWizardFallback",
                "navigateToStep",
                "inferNextStepFromFlags",
                "normalizeNextStepValue",
                "isKnownNextStep",
                "resolveNextStep",
                "formatArchiveTimeForDisplay",
                "archivePageHref",
                "applyArchivePageLink",
                "computeNextStep",
                "inferAllowedModes",
                "applyActionAvailability",
                "applyArchiveAvailability",
                "applyManualAvailability",
                "applyProviderAvailability",
                "toCount",
                "buildMfSummaryText",
                "renderMfSummary",
                "fileNameFromPath",
                "buildProviderSourceSummarySuffix",
                "buildProviderSourceSummaryText",
                "renderProviderSourceSummary",
                "buildProviderImportSummaryText",
                "renderProviderImportSummary",
                "setStepLinkState",
                "applyLinkAvailability",
                "buildStepStates",
                "buildTaskStates",
            ],
        ),
        base / "index.events.js": (
            "window.DashboardIndexEvents",
            [
                "refreshSteps",
                "loadMonthCloseChecklist",
                "saveMonthCloseChecklist",
                "updateCheckboxes",
            ],
        ),
    }

    for path, (namespace, symbols) in checks.items():
        text = path.read_text(encoding="utf-8")
        assert namespace in text
        marker = f"{namespace} = {{"
        start = text.find(marker)
        assert start != -1, f"Unable to locate export block in {path.name}"
        brace_start = text.find("{", start)
        brace_end = text.find("};", brace_start)
        assert brace_end != -1, f"Unable to locate export block end in {path.name}"
        block = text[brace_start + 1 : brace_end]
        exported = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?=[:},])", block, flags=re.M))
        for symbol in symbols:
            assert symbol in exported, f"Missing export symbol in {path.name}: {symbol}"
