from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from services import core


def create_pages_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        artifacts = core._scan_artifacts()
        jobs = core._scan_run_jobs()
        running_job = core._get_latest_running_job()
        defaults = core._resolve_form_defaults()
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
            "index.html",
            {
                "request": request,
                "artifacts": artifacts,
                "latest_job": latest_job,
                "latest_job_ym": latest_job_ym,
                "running_job": running_job,
                "defaults": defaults,
                "ax_home": str(core._ax_home()),
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
        rows = rows if isinstance(rows, list) else []
        for row in rows:
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

        amazon_pdfs = list((root / "amazon" / "pdfs").glob("*.pdf")) if (root / "amazon" / "pdfs").exists() else []
        rakuten_pdfs = list((root / "rakuten" / "pdfs").glob("*.pdf")) if (root / "rakuten" / "pdfs").exists() else []

        print_script = reports_dir / "print_all.ps1"
        print_command = ""
        if print_script.exists():
            print_command = f'powershell -NoProfile -ExecutionPolicy Bypass -File "{print_script}"'

        return templates.TemplateResponse(
            "run.html",
            {
                "request": request,
                "ym": ym,
                "counts": counts or {},
                "rows": rows[:50],
                "row_total": len(rows),
                "orders": orders,
                "orders_total": len(orders),
                "excluded_count": excluded_count,
                "amazon_pdf_count": len(amazon_pdfs),
                "rakuten_pdf_count": len(rakuten_pdfs),
                "has_reports": reports_dir.exists(),
                "print_script": str(print_script) if print_script.exists() else None,
                "print_command": print_command,
                "file_labels": {
                    "missing_csv": "未添付候補CSV",
                    "missing_json": "未添付候補JSON",
                    "monthly_thread": "月次メモ",
                    "run_config": "実行設定",
                    "audit_log": "監査ログ(JSONL)",
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
        amazon_count = sum(1 for r in rows if r.get("source") == "amazon")
        rakuten_count = sum(1 for r in rows if r.get("source") == "rakuten")
        return templates.TemplateResponse(
            "excluded_pdfs.html",
            {
                "request": request,
                "ym": ym,
                "rows": rows,
                "total": len(rows),
                "amazon_count": amazon_count,
                "rakuten_count": rakuten_count,
            },
        )

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

    return router
