from __future__ import annotations

import inspect
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from services import core, core_scheduler, core_shared

from .api_helpers import (
    _actor_from_request,
    _merge_pdfs,
    _normalize_provider_import_result,
    _open_directory,
    _open_file,
    _open_receipts_folder_for_ym,
    _resolve_provider_skipped_dir_for_ym,
    _validate_provider_import_webhook_token,
    _write_folder_shortcut,
)
from . import api as _api_routes


def register_api_folder_endpoints(router: APIRouter) -> None:
    @router.post("/api/folders/{ym}/receipts")
    @router.post("/api/folders/{ym}/receipt")
    @router.post("/api/folders/{ym}/open-receipts")
    @router.post("/api/folder/{ym}/receipts")
    def api_open_receipts_folder(ym: str, request: Request) -> JSONResponse:
        return _open_receipts_folder_for_ym(ym, _actor_from_request(request))


    @router.post("/api/folders/receipts")
    @router.post("/api/folders/receipt")
    @router.post("/api/folders/open-receipts")
    def api_open_receipts_folder_query(ym: str, request: Request) -> JSONResponse:
        return _open_receipts_folder_for_ym(ym, _actor_from_request(request))


    @router.post("/api/folders/{ym}/manual-inbox")
    def api_open_manual_inbox(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        target = core._manual_inbox_dir_for_ym(year, month, create=True)
        shortcut_path: Path | None = None
        try:
            shortcut_path = _write_folder_shortcut(target, f"AX_{ym}_Step3_CommonInbox")
        except Exception:
            shortcut_path = None
        res = _open_directory(target)
        if res.returncode != 0:
            detail = (
                "Open folder failed:\n"
                f"path: {target}\n"
                f"exit: {res.returncode}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            )
            core._append_audit_event(
                year=year,
                month=month,
                event_type="manual",
                action="open_inbox",
                status="failed",
                actor=actor,
                details={
                    "reason": detail,
                    "path": str(target),
                    "shortcut_path": str(shortcut_path) if shortcut_path else "",
                },
            )
            raise HTTPException(status_code=500, detail=detail)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="manual",
            action="open_inbox",
            status="success",
            actor=actor,
            details={
                "path": str(target),
                "shortcut_path": str(shortcut_path) if shortcut_path else "",
            },
        )
        return JSONResponse(
            {
                "status": "ok",
                "ym": ym,
                "path": str(target),
                "shortcut_path": str(shortcut_path) if shortcut_path else "",
            }
        )


    @router.post("/api/folders/{ym}/provider-inbox/{provider}")
    def api_open_provider_inbox(ym: str, provider: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        try:
            target = core._provider_inbox_dir_for_ym(year, month, provider, create=True)
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="open_inbox",
                status="rejected",
                actor=actor,
                details={"reason": str(exc.detail), "provider": str(provider or "").strip().lower()},
            )
            raise

        normalized_provider = str(provider or "").strip().lower()
        res = _open_directory(target)
        if res.returncode != 0:
            detail = (
                "Open folder failed:\n"
                f"path: {target}\n"
                f"exit: {res.returncode}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            )
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="open_inbox",
                status="failed",
                actor=actor,
                details={"reason": detail, "provider": normalized_provider, "path": str(target)},
            )
            raise HTTPException(status_code=500, detail=detail)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="provider_ingest",
            action="open_inbox",
            status="success",
            actor=actor,
            details={"provider": normalized_provider, "path": str(target)},
        )
        return JSONResponse({"status": "ok", "ym": ym, "provider": normalized_provider, "path": str(target)})


    @router.post("/api/folders/{ym}/provider-source")
    def api_open_provider_source(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)

        source_status = _api_routes._provider_source_status_for_ym(year, month)
        source_path = source_status.get("path") or ""
        if not source_status.get("configured"):
            detail = "Provider source directory is not configured."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="open_source",
                status="rejected",
                actor=actor,
                details={"reason": detail},
            )
            raise HTTPException(status_code=409, detail=detail)

        source_target = Path(source_path)
        if not source_status.get("exists"):
            detail = f"Provider source directory does not exist: {source_target}"
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="open_source",
                status="rejected",
                actor=actor,
                details={"reason": detail, "path": source_path},
            )
            raise HTTPException(status_code=409, detail=detail)

        shortcut_path: Path | None = None
        try:
            shortcut_path = _write_folder_shortcut(source_target, f"AX_{ym}_ProviderSource")
        except Exception:
            shortcut_path = None

        res = _open_directory(source_target)
        if res.returncode != 0:
            detail = (
                "Open folder failed:\n"
                f"path: {source_target}\n"
                f"exit: {res.returncode}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            )
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="open_source",
                status="failed",
                actor=actor,
                details={"reason": detail, "path": source_path, "shortcut_path": str(shortcut_path) if shortcut_path else ""},
            )
            raise HTTPException(status_code=500, detail=detail)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="provider_ingest",
            action="open_source",
            status="success",
            actor=actor,
            details={"path": source_path, "shortcut_path": str(shortcut_path) if shortcut_path else ""},
        )
        return JSONResponse(
            {
                "status": "ok",
                "ym": ym,
                "path": source_path,
                "shortcut_path": str(shortcut_path) if shortcut_path else "",
                "source_status": source_status,
            }
        )


    @router.post("/api/folders/{ym}/provider-skipped/latest")
    def api_open_provider_skipped_latest(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        target = _resolve_provider_skipped_dir_for_ym(year, month)
        if target is None:
            detail = "No skipped receipt folder was found for the latest provider import."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="open_skipped",
                status="rejected",
                actor=actor,
                details={"reason": detail},
            )
            raise HTTPException(status_code=404, detail=detail)

        res = _open_directory(target)
        if res.returncode != 0:
            detail = (
                "Open folder failed:\n"
                f"path: {target}\n"
                f"exit: {res.returncode}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            )
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="open_skipped",
                status="failed",
                actor=actor,
                details={"reason": detail, "path": str(target)},
            )
            raise HTTPException(status_code=500, detail=detail)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="provider_ingest",
            action="open_skipped",
            status="success",
            actor=actor,
            details={"path": str(target)},
        )
        return JSONResponse({"status": "ok", "ym": ym, "path": str(target)})


    @router.post("/api/manual/{ym}/import")
    def api_manual_import(
        ym: str,
        request: Request,
        source_dir: str | None = Query(default=None),
        source_mode: str = Query(default="copy"),
        source_dry_run: bool = Query(default=False),
    ) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        running_mode = core._running_mode_for_ym(year, month)
        if running_mode:
            detail = "Another run is already in progress. Wait for completion before manual receipt import."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="manual",
                action="import",
                status="rejected",
                actor=actor,
                details={"reason": detail, "running_mode": running_mode},
            )
            raise HTTPException(status_code=409, detail=detail)
        try:
            import_func = core._import_manual_receipts_for_ym
            try:
                import_sig = inspect.signature(import_func)
                import_params = set(import_sig.parameters)
            except (TypeError, ValueError):
                import_params = set()
            if "source_dir" not in import_params:
                result = import_func(year, month)  # type: ignore[misc]
            else:
                result = import_func(year, month, source_dir, source_mode, source_dry_run)  # type: ignore[misc]
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="manual",
                action="import",
                status="rejected" if exc.status_code in {400, 404, 409} else "failed",
                actor=actor,
                details={"reason": str(exc.detail)},
            )
            raise

        core._append_audit_event(
            year=year,
            month=month,
            event_type="manual",
            action="import",
            status="success",
            actor=actor,
                details={
                    "found_pdfs": result.get("found_pdfs"),
                    "imported": result.get("imported"),
                    "skipped_duplicates": result.get("skipped_duplicates"),
                    "failed": result.get("failed"),
                    "orders_jsonl": result.get("orders_jsonl"),
                    "source_dir": str(source_dir or "").strip(),
                    "source_mode": str(source_mode or "").strip(),
                    "source_dry_run": bool(source_dry_run),
                },
            )
        return JSONResponse(result)


    @router.post("/api/providers/{ym}/import")
    def api_provider_import(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        running_mode = core._running_mode_for_ym(year, month)
        if running_mode:
            detail = "Another run is already in progress. Wait for completion before provider receipt import."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="import",
                status="rejected",
                actor=actor,
                details={"reason": detail, "running_mode": running_mode},
            )
            raise HTTPException(status_code=409, detail=detail)
        try:
            result = core._import_provider_receipts_for_ym(year, month)
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="import",
                status="rejected" if exc.status_code in {400, 404, 409} else "failed",
                actor=actor,
                details={"reason": str(exc.detail)},
            )
            raise

        skipped_duplicates = int(result.get("skipped_duplicates") or 0)
        failed = int(result.get("failed") or 0)
        manual_action_required = bool(result.get("manual_action_required")) or skipped_duplicates > 0 or failed > 0
        result["manual_action_required"] = manual_action_required
        if manual_action_required:
            reason = str(result.get("manual_action_reason") or "").strip()
            if not reason:
                if skipped_duplicates > 0 and failed > 0:
                    reason = "skipped_and_failed"
                elif skipped_duplicates > 0:
                    reason = "skipped"
                else:
                    reason = "failed"
            result["manual_action_reason"] = reason
            skipped_dir = str(result.get("skipped_dir") or "").strip()
            if not skipped_dir:
                resolved = _resolve_provider_skipped_dir_for_ym(year, month)
                if resolved is not None:
                    result["skipped_dir"] = str(resolved)
            if not isinstance(result.get("skipped_files"), list):
                result["skipped_files"] = []

        audit_status = "warning" if manual_action_required else "success"
        core._append_audit_event(
            year=year,
            month=month,
            event_type="provider_ingest",
            action="import",
            status=audit_status,
            actor=actor,
            details={
                "found_files": result.get("found_files"),
                "imported": result.get("imported"),
                "skipped_duplicates": result.get("skipped_duplicates"),
                "failed": result.get("failed"),
                "providers": result.get("providers"),
                "orders_jsonl": result.get("orders_jsonl"),
                "provider_report_json": result.get("provider_report_json"),
                "manual_action_required": manual_action_required,
                "manual_action_reason": result.get("manual_action_reason"),
                "skipped_dir": result.get("skipped_dir"),
                "skipped_files": result.get("skipped_files"),
            },
        )
        return JSONResponse(result)


    @router.post("/api/provider-import/{ym}/result")
    def api_provider_import_webhook(
        ym: str,
        payload: dict[str, Any],
        request: Request,
        token: str | None = Query(default=None),
    ) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        _validate_provider_import_webhook_token(request=request, token=token)
        actor = _actor_from_request(request)

        normalized = _normalize_provider_import_result(payload, year, month)
        report_path = core._artifact_root() / ym / "manual" / "reports" / "provider_import_last.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        core._write_json(report_path, normalized)

        manual_action_required = bool(normalized.get("manual_action_required") or False)
        failed_count = int(normalized.get("failed") or 0)
        audit_status = "warning" if manual_action_required or failed_count > 0 else "success"
        core._append_audit_event(
            year=year,
            month=month,
            event_type="provider_ingest",
            action="import_webhook",
            status=audit_status,
            actor=actor,
            details={
                "source": "google_apps_script",
                "ingestion_channel": str(normalized.get("ingestion_channel") or ""),
                "found_files": normalized.get("found_files"),
                "imported": normalized.get("imported"),
                "skipped_duplicates": normalized.get("skipped_duplicates"),
                "failed": failed_count,
                "manual_action_required": manual_action_required,
                "manual_action_reason": str(normalized.get("manual_action_reason") or ""),
                "report_path": str(report_path),
            },
        )
        return JSONResponse(
            {
                "status": "ok",
                "ym": ym,
                "provider_report_json": str(normalized.get("provider_report_json") or report_path),
                "report_path": str(report_path),
            }
        )


    @router.post("/api/providers/{ym}/print-run")
    def api_provider_print_run(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        output_root = core._artifact_root() / ym
        reports_dir = output_root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        provider_pdfs_dir = output_root / "manual" / "pdfs"
        pdf_paths = sorted(path for path in provider_pdfs_dir.rglob("*.pdf") if path.is_file()) if provider_pdfs_dir.exists() else []
        merged_pdf_path = reports_dir / "print_merged_provider.pdf"

        if not pdf_paths:
            detail = f"No provider PDF files were found under: {provider_pdfs_dir}"
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="print_run",
                status="rejected",
                actor=actor,
                details={"reason": detail, "provider_pdfs_dir": str(provider_pdfs_dir)},
            )
            raise HTTPException(status_code=409, detail=detail)

        try:
            merged_count, merged_pages = _merge_pdfs(pdf_paths, merged_pdf_path)
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="print_run",
                status="failed",
                actor=actor,
                details={
                    "reason": str(exc.detail),
                    "provider_pdfs_dir": str(provider_pdfs_dir),
                    "merged_pdf_path": str(merged_pdf_path),
                },
            )
            raise
        except Exception as exc:
            detail = f"Merged PDF generation failed: {exc}"
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="print_run",
                status="failed",
                actor=actor,
                details={
                    "reason": detail,
                    "provider_pdfs_dir": str(provider_pdfs_dir),
                    "merged_pdf_path": str(merged_pdf_path),
                },
            )
            raise HTTPException(status_code=500, detail=detail) from exc

        open_result = _open_file(merged_pdf_path)
        if open_result.returncode != 0:
            detail = (
                "Open merged PDF failed:\n"
                f"path: {merged_pdf_path}\n"
                f"exit: {open_result.returncode}\n"
                f"stdout:\n{open_result.stdout}\n"
                f"stderr:\n{open_result.stderr}\n"
            )
            core._append_audit_event(
                year=year,
                month=month,
                event_type="provider_ingest",
                action="print_run",
                status="failed",
                actor=actor,
                details={
                    "reason": detail,
                    "provider_pdfs_dir": str(provider_pdfs_dir),
                    "merged_pdf_path": str(merged_pdf_path),
                },
            )
            raise HTTPException(status_code=500, detail=detail)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="provider_ingest",
            action="print_run",
            status="success",
            actor=actor,
            details={
                "mode": "manual_open",
                "count": merged_count,
                "merged_pages": merged_pages,
                "provider_pdfs_dir": str(provider_pdfs_dir),
                "merged_pdf_path": str(merged_pdf_path),
            },
        )
        return JSONResponse(
            {
                "status": "ok",
                "ym": ym,
                "print_mode": "manual_open",
                "count": merged_count,
                "merged_pdf_path": str(merged_pdf_path),
            }
        )


    @router.post("/api/providers/{ym}/download")
    def api_provider_download(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        detail = (
            "Provider auto-download is disabled. "
            "Step 4.5 is manual-only: place receipts in manual/inbox and run import."
        )
        core._append_audit_event(
            year=year,
            month=month,
            event_type="provider_ingest",
            action="download",
            status="rejected",
            actor=actor,
            details={
                "reason": detail,
                "mode": "manual_only",
            },
        )
        raise HTTPException(status_code=409, detail=detail)


    @router.post("/api/folders/{ym}/mf-bulk-inbox")
    def api_open_mf_bulk_inbox(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        target = core._mf_bulk_upload_inbox_dir_for_ym(year, month, create=True)
        shortcut_path: Path | None = None
        try:
            shortcut_path = _write_folder_shortcut(target, f"AX_{ym}_Step4_MfBulkInbox")
        except Exception:
            shortcut_path = None
        res = _open_directory(target)
        if res.returncode != 0:
            detail = (
                "Open folder failed:\n"
                f"path: {target}\n"
                f"exit: {res.returncode}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            )
            core._append_audit_event(
                year=year,
                month=month,
                event_type="mf_bulk_upload",
                action="open_inbox",
                status="failed",
                actor=actor,
                details={
                    "reason": detail,
                    "path": str(target),
                    "shortcut_path": str(shortcut_path) if shortcut_path else "",
                },
            )
            raise HTTPException(status_code=500, detail=detail)
        core._append_audit_event(
            year=year,
            month=month,
            event_type="mf_bulk_upload",
            action="open_inbox",
            status="success",
            actor=actor,
            details={
                "path": str(target),
                "shortcut_path": str(shortcut_path) if shortcut_path else "",
            },
        )
        return JSONResponse(
            {
                "status": "ok",
                "ym": ym,
                "path": str(target),
                "shortcut_path": str(shortcut_path) if shortcut_path else "",
            }
        )


    @router.post("/api/folders/{ym}/mf-csv-inbox")
    def api_open_mf_csv_inbox(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        target = core._mf_csv_import_inbox_dir_for_ym(year, month, create=True)
        shortcut_path: Path | None = None
        try:
            shortcut_path = _write_folder_shortcut(target, f"AX_{ym}_Step4_MfCsvInbox")
        except Exception:
            shortcut_path = None
        res = _open_directory(target)
        if res.returncode != 0:
            detail = (
                "Open folder failed:\n"
                f"path: {target}\n"
                f"exit: {res.returncode}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            )
            core._append_audit_event(
                year=year,
                month=month,
                event_type="mf_csv_import",
                action="open_inbox",
                status="failed",
                actor=actor,
                details={
                    "reason": detail,
                    "path": str(target),
                    "shortcut_path": str(shortcut_path) if shortcut_path else "",
                },
            )
            raise HTTPException(status_code=500, detail=detail)
        core._append_audit_event(
            year=year,
            month=month,
            event_type="mf_csv_import",
            action="open_inbox",
            status="success",
            actor=actor,
            details={
                "path": str(target),
                "shortcut_path": str(shortcut_path) if shortcut_path else "",
            },
        )
        return JSONResponse(
            {
                "status": "ok",
                "ym": ym,
                "path": str(target),
                "shortcut_path": str(shortcut_path) if shortcut_path else "",
            }
        )


    @router.post("/api/mf-bulk-upload/{ym}")
    def api_mf_bulk_upload(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        running_mode = core._running_mode_for_ym(year, month)
        if running_mode:
            detail = "Another run is already in progress. Wait for completion before MF bulk upload."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="mf_bulk_upload",
                action="run",
                status="rejected",
                actor=actor,
                details={"reason": detail, "running_mode": running_mode},
            )
            raise HTTPException(status_code=409, detail=detail)

        try:
            result = core._run_mf_bulk_upload_for_ym(
                year,
                month,
                auth_handoff=True,
                headed=True,
                slow_mo_ms=0,
                transactions_url=core.DEFAULT_MFCLOUD_TRANSACTIONS_URL,
            )
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="mf_bulk_upload",
                action="run",
                status="rejected" if exc.status_code in {400, 404, 409} else "failed",
                actor=actor,
                details={"reason": str(exc.detail)},
            )
            raise

        core._append_audit_event(
            year=year,
            month=month,
            event_type="mf_bulk_upload",
            action="run",
            status="success",
            actor=actor,
            details={
                "files_found": result.get("files_found"),
                "submitted_count": result.get("submitted_count"),
                "queued_count": result.get("queued_count"),
                "read_count": result.get("read_count"),
                "result_json": result.get("result_json"),
            },
        )
        return JSONResponse(result)


    @router.post("/api/mf-csv-import/{ym}")
    def api_mf_csv_import(ym: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        running_mode = core._running_mode_for_ym(year, month)
        if running_mode:
            detail = "Another run is already in progress. Wait for completion before MF CSV import."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="mf_csv_import",
                action="run",
                status="rejected",
                actor=actor,
                details={"reason": detail, "running_mode": running_mode},
            )
            raise HTTPException(status_code=409, detail=detail)

        try:
            result = core._run_mf_csv_import_for_ym(
                year,
                month,
                auth_handoff=True,
                headed=True,
                slow_mo_ms=0,
                import_url=core.DEFAULT_MFCLOUD_TRANSACTIONS_IMPORT_URL,
            )
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="mf_csv_import",
                action="run",
                status="rejected" if exc.status_code in {400, 404, 409} else "failed",
                actor=actor,
                details={"reason": str(exc.detail)},
            )
            raise

        core._append_audit_event(
            year=year,
            month=month,
            event_type="mf_csv_import",
            action="run",
            status="success",
            actor=actor,
            details={
                "files_found": result.get("files_found"),
                "submitted_count": result.get("submitted_count"),
                "queued_count": result.get("queued_count"),
                "result_json": result.get("result_json"),
            },
        )
        return JSONResponse(result)


