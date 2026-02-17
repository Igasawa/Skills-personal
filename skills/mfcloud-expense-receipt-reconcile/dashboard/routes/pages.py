from __future__ import annotations

from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services import core

ARCHIVE_SNAPSHOT_RE = re.compile(r"^\d{8}_\d{6}$")


def create_pages_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        defaults = core._resolve_form_defaults()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "defaults": defaults,
                "ax_home": str(core._ax_home()),
                "active_tab": "wizard",
            },
        )

    @router.get("/status", response_class=HTMLResponse)
    def status(request: Request) -> HTMLResponse:
        artifacts = core._scan_artifacts()
        archive_history = core._scan_archive_history(limit=20)
        jobs = core._scan_run_jobs()
        running_job = core._get_latest_running_job()
        latest_job = jobs[0] if jobs else None
        latest_job_ym = None
        if isinstance(latest_job, dict):
            params = latest_job.get("params") if isinstance(latest_job.get("params"), dict) else {}
            try:
                y = int(params.get("year"))
                m = int(params.get("month"))
                if 1 <= m <= 12:
                    latest_job_ym = f"{y:04d}-{m:02d}"
            except Exception:
                latest_job_ym = None

        return templates.TemplateResponse(
            request,
            "status.html",
            {
                "artifacts": artifacts,
                "archive_history": archive_history,
                "latest_job": latest_job,
                "latest_job_ym": latest_job_ym,
                "running_job": running_job,
                "ax_home": str(core._ax_home()),
                "active_tab": "status",
            },
        )

    @router.get("/workspace", response_class=HTMLResponse)
    def workspace(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "workspace.html",
            {
                "ax_home": str(core._ax_home()),
                "active_tab": "workspace",
            },
        )

    @router.get("/errors", response_class=HTMLResponse)
    def errors(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "errors.html",
            {
                "ax_home": str(core._ax_home()),
                "active_tab": "errors",
            },
        )

    @router.get("/runs/{ym}", response_class=HTMLResponse)
    def run_detail(request: Request, ym: str) -> HTMLResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym
        if not root.exists():
            raise HTTPException(status_code=404, detail="Run not found.")

        reports_dir = root / "reports"
        missing_json = reports_dir / "missing_evidence_candidates.json"
        data = core._read_json(missing_json) or {}
        rows = data.get("rows") if isinstance(data, dict) else []
        counts = data.get("counts") if isinstance(data, dict) else {}
        merged_counts = dict(counts or {})
        merged_counts.update(core._derive_order_counts_from_jsonl(root, ym))
        rows = rows if isinstance(rows, list) else []
        for row in rows:
            mf_use_date = str(row.get("mf_use_date") or "").strip() or None
            row["mf_use_date"] = mf_use_date or "-"
            vendor = str(row.get("mf_vendor") or "")
            memo = str(row.get("mf_memo") or "")
            summary = core._compact_mf_summary(vendor, memo)
            row["mf_summary"] = summary if summary else " ".join([vendor, memo]).strip()
            amount = row.get("mf_amount_yen")
            if isinstance(amount, (int, float)):
                row["mf_amount_label"] = f"{int(amount):,}円"
            elif isinstance(amount, str) and amount.strip().isdigit():
                row["mf_amount_label"] = f"{int(amount.strip()):,}円"
            else:
                row["mf_amount_label"] = "-"

        exclusions = core._load_exclusions(reports_dir)
        orders = core._collect_orders(root, ym, exclusions)
        excluded_count = sum(1 for o in orders if o.get("excluded"))
        included_count = max(0, len(orders) - excluded_count)
        merged_counts.update(
            {
                "manual_excluded_orders": len(exclusions),
                "excluded_orders": excluded_count,
                "included_orders": included_count,
            }
        )
        workflow = core._read_workflow(reports_dir)
        amazon_workflow = workflow.get("amazon") if isinstance(workflow.get("amazon"), dict) else {}
        rakuten_workflow = workflow.get("rakuten") if isinstance(workflow.get("rakuten"), dict) else {}

        amazon_pdfs = list((root / "amazon" / "pdfs").glob("*.pdf")) if (root / "amazon" / "pdfs").exists() else []
        rakuten_pdfs = list((root / "rakuten" / "pdfs").glob("*.pdf")) if (root / "rakuten" / "pdfs").exists() else []

        print_script = reports_dir / "print_all.ps1"
        mf_draft_actions = reports_dir / "mf_draft_create_actions.jsonl"
        amazon_print_manifest = reports_dir / "print_manifest.amazon.json"
        rakuten_print_manifest = reports_dir / "print_manifest.rakuten.json"
        amazon_bulk_print_ready = bool(amazon_workflow.get("print_prepared_at")) and amazon_print_manifest.exists()
        rakuten_bulk_print_ready = bool(rakuten_workflow.get("print_prepared_at")) and rakuten_print_manifest.exists()

        return templates.TemplateResponse(
            request,
            "run.html",
            {
                "ym": ym,
                "counts": merged_counts,
                "rows": rows[:50],
                "row_total": len(rows),
                "orders": orders,
                "orders_total": len(orders),
                "excluded_count": excluded_count,
                "included_count": included_count,
                "amazon_pdf_count": len(amazon_pdfs),
                "rakuten_pdf_count": len(rakuten_pdfs),
                "has_reports": reports_dir.exists(),
                "print_script": str(print_script) if print_script.exists() else None,
                "amazon_print_prepared": bool(amazon_workflow.get("print_prepared_at")),
                "rakuten_print_prepared": bool(rakuten_workflow.get("print_prepared_at")),
                "amazon_bulk_print_ready": amazon_bulk_print_ready,
                "rakuten_bulk_print_ready": rakuten_bulk_print_ready,
                "mf_draft_actions_exists": mf_draft_actions.exists(),
                "file_labels": {
                    "missing_csv": "未添付候補CSV",
                    "missing_json": "未添付候補JSON",
                    "monthly_thread": "月次メモ",
                    "run_config": "実行設定",
                    "audit_log": "監査ログ(JSONL)",
                    "mf_draft_actions": "MF下書き作成ログ(JSONL)",
                    "print_script": "印刷用スクリプト",
                },
            },
        )

    @router.get("/runs/{ym}/excluded-pdfs", response_class=HTMLResponse)
    def run_excluded_pdfs(request: Request, ym: str) -> HTMLResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym
        if not root.exists():
            raise HTTPException(status_code=404, detail="Run not found.")
        reports_dir = root / "reports"
        exclusions = core._load_exclusions(reports_dir)
        rows = core._collect_excluded_pdfs(root, ym, exclusions)
        available_months = [
            str(item.get("ym"))
            for item in core._scan_artifacts()
            if isinstance(item, dict) and isinstance(item.get("ym"), str)
        ]
        if ym not in available_months:
            available_months.insert(0, ym)
        available_months = list(dict.fromkeys(available_months))
        amazon_count = sum(1 for r in rows if r.get("source") == "amazon")
        rakuten_count = sum(1 for r in rows if r.get("source") == "rakuten")
        return templates.TemplateResponse(
            request,
            "excluded_pdfs.html",
            {
                "ym": ym,
                "rows": rows,
                "total": len(rows),
                "amazon_count": amazon_count,
                "rakuten_count": rakuten_count,
                "available_months": available_months,
            },
        )

    @router.get("/runs/{ym}/archived-receipts", response_class=HTMLResponse)
    def run_archived_receipts(request: Request, ym: str) -> HTMLResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym
        if not root.exists():
            raise HTTPException(status_code=404, detail="Run not found.")

        archive_data = core._scan_archived_receipts(root)
        available_months = [
            str(item.get("ym"))
            for item in core._scan_artifacts()
            if isinstance(item, dict) and isinstance(item.get("ym"), str)
        ]
        if ym not in available_months:
            available_months.insert(0, ym)
        available_months = list(dict.fromkeys(available_months))
        return templates.TemplateResponse(
            request,
            "archive_receipts.html",
            {
                "ym": ym,
                "rows": archive_data.get("rows") if isinstance(archive_data.get("rows"), list) else [],
                "snapshots": archive_data.get("snapshots") if isinstance(archive_data.get("snapshots"), list) else [],
                "total": int(archive_data.get("receipt_count") or 0),
                "snapshot_count": int(archive_data.get("snapshot_count") or 0),
                "amazon_count": int(archive_data.get("amazon_count") or 0),
                "rakuten_count": int(archive_data.get("rakuten_count") or 0),
                "archive_root": str(archive_data.get("archive_root") or ""),
                "available_months": available_months,
            },
        )

    @router.get("/runs/{ym}/archive-receipts", include_in_schema=False)
    def run_archived_receipts_legacy(request: Request, ym: str) -> RedirectResponse:
        ym = core._safe_ym(ym)
        return RedirectResponse(url=str(request.url_for("run_archived_receipts", ym=ym)))

    @router.get("/files/{ym}/{kind}")
    def download_file(ym: str, kind: str) -> FileResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym
        if not root.exists():
            raise HTTPException(status_code=404, detail="Run not found.")

        mapping = {
            "missing_csv": root / "reports" / "missing_evidence_candidates.csv",
            "missing_json": root / "reports" / "missing_evidence_candidates.json",
            "monthly_thread": root / "reports" / "monthly_thread.md",
            "run_config": root / "run_config.resolved.json",
            "audit_log": root / "reports" / "audit_log.jsonl",
            "mf_draft_actions": root / "reports" / "mf_draft_create_actions.jsonl",
            "print_script": root / "reports" / "print_all.ps1",
        }
        if kind not in mapping:
            raise HTTPException(status_code=404, detail="File not found.")
        path = mapping[kind]
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path)

    @router.get("/files/{ym}/pdf/{source}/{filename}")
    def download_pdf(ym: str, source: str, filename: str) -> FileResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=404, detail="File not found.")
        if not filename or not core.SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=404, detail="File not found.")
        root = core._artifact_root() / ym
        path = core._resolve_pdf_path(root, source, filename)
        if not path:
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path, media_type="application/pdf", filename=Path(path).name)

    @router.get("/files/{ym}/archive/{snapshot}/{source}/{filename}")
    def download_archived_pdf(ym: str, snapshot: str, source: str, filename: str) -> FileResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=404, detail="File not found.")
        if not ARCHIVE_SNAPSHOT_RE.match(str(snapshot or "")):
            raise HTTPException(status_code=404, detail="File not found.")
        if not filename or not core.SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=404, detail="File not found.")

        root = core._artifact_root() / ym
        base_dir = (root / "archive" / snapshot / source / "pdfs").resolve()
        path = (base_dir / filename).resolve()
        try:
            path.relative_to(base_dir)
        except Exception:
            raise HTTPException(status_code=404, detail="File not found.")
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path, media_type="application/pdf", filename=Path(path).name)

    return router
