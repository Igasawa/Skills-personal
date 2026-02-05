from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from services import core


def create_api_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/steps/{ym}")
    def api_steps(ym: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        root = core._artifact_root() / ym
        reports_dir = root / "reports"
        workflow = core._read_workflow(reports_dir)

        preflight_done = (reports_dir / "preflight.json").exists() or core._preflight_global_path().exists()
        amazon_downloaded = (root / "amazon" / "orders.jsonl").exists()
        rakuten_downloaded = (root / "rakuten" / "orders.jsonl").exists()
        amazon_confirmed = bool((workflow.get("amazon") or {}).get("confirmed_at"))
        amazon_printed = bool((workflow.get("amazon") or {}).get("printed_at"))
        rakuten_confirmed = bool((workflow.get("rakuten") or {}).get("confirmed_at"))
        rakuten_printed = bool((workflow.get("rakuten") or {}).get("printed_at"))
        mf_reconciled = (reports_dir / "missing_evidence_candidates.json").exists()
        running_mode = core._running_mode_for_ym(year, month)

        return JSONResponse(
            {
                "ym": ym,
                "preflight": {"done": preflight_done},
                "amazon": {"downloaded": amazon_downloaded, "confirmed": amazon_confirmed, "printed": amazon_printed},
                "rakuten": {"downloaded": rakuten_downloaded, "confirmed": rakuten_confirmed, "printed": rakuten_printed},
                "mf": {"reconciled": mf_reconciled},
                "running_mode": running_mode,
            }
        )

    @router.get("/api/exclusions/{ym}")
    def api_get_exclusions(ym: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym / "reports"
        data = core._read_json(root / "exclude_orders.json")
        if not isinstance(data, dict):
            data = {"ym": ym, "exclude": []}
        return JSONResponse(data)

    @router.post("/api/exclusions/{ym}")
    def api_set_exclusions(ym: str, payload: dict[str, Any]) -> JSONResponse:
        ym = core._safe_ym(ym)
        exclude = payload.get("exclude")
        if not isinstance(exclude, list):
            raise HTTPException(status_code=400, detail="exclude must be a list.")

        cleaned: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in exclude:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            order_id = str(item.get("order_id") or "").strip()
            if source not in {"amazon", "rakuten"}:
                continue
            if not order_id or not core.ORDER_ID_RE.match(order_id):
                continue
            key = (source, order_id)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append({"source": source, "order_id": order_id})

        reports_dir = core._artifact_root() / ym / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        data = {"ym": ym, "exclude": cleaned, "updated_at": datetime.now().isoformat(timespec="seconds")}
        core._write_json(reports_dir / "exclude_orders.json", data)
        source = str(payload.get("source") or "").strip()
        if source in {"amazon", "rakuten"}:
            wf = core._read_workflow(reports_dir)
            section = wf.get(source) if isinstance(wf.get(source), dict) else {}
            section["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
            wf[source] = section
            core._write_workflow(reports_dir, wf)

        return JSONResponse({"status": "ok", "count": len(cleaned)})

    @router.post("/api/print/{ym}/{source}")
    def api_print(ym: str, source: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=400, detail="Invalid source.")

        year, month = core._split_ym(ym)
        output_root = core._artifact_root() / ym
        scripts_dir = core.SKILL_ROOT / "scripts"
        exclude_orders_json = output_root / "reports" / "exclude_orders.json"

        cmd = [
            sys.executable,
            str(scripts_dir / "collect_print.py"),
            "--year",
            str(year),
            "--month",
            str(month),
            "--output-dir",
            str(output_root),
            "--sources",
            source,
        ]
        if exclude_orders_json.exists():
            cmd += ["--exclude-orders-json", str(exclude_orders_json)]

        res = subprocess.run(cmd, cwd=str(scripts_dir), capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=(
                    "collect_print.py failed:\n"
                    f"cmd: {cmd}\n"
                    f"exit: {res.returncode}\n"
                    f"stdout:\n{res.stdout}\n"
                    f"stderr:\n{res.stderr}\n"
                ),
            )

        print_script = output_root / "reports" / "print_all.ps1"
        if not print_script.exists():
            raise HTTPException(status_code=404, detail="print_all.ps1 not found.")

        ps = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(print_script)],
            capture_output=True,
            text=True,
            check=False,
        )
        if ps.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=(
                    "print script failed:\n"
                    f"exit: {ps.returncode}\n"
                    f"stdout:\n{ps.stdout}\n"
                    f"stderr:\n{ps.stderr}\n"
                ),
            )

        reports_dir = output_root / "reports"
        wf = core._read_workflow(reports_dir)
        section = wf.get(source) if isinstance(wf.get(source), dict) else {}
        section["printed_at"] = datetime.now().isoformat(timespec="seconds")
        wf[source] = section
        core._write_workflow(reports_dir, wf)

        return JSONResponse({"status": "ok", "source": source})

    @router.post("/api/print-pdf/{ym}/{source}/{filename}")
    def api_print_pdf(ym: str, source: str, filename: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=404, detail="PDF not found.")
        if not filename or not core.SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=404, detail="PDF not found.")
        root = core._artifact_root() / ym
        path = core._resolve_pdf_path(root, source, filename)
        if not path:
            raise HTTPException(status_code=404, detail="PDF not found.")
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"Start-Process -FilePath '{path}' -Verb Print",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail="Print failed.")
        return JSONResponse({"status": "ok", "file": str(path.name)})

    @router.post("/api/runs")
    def api_run(payload: dict[str, Any]) -> JSONResponse:
        result = core._start_run(payload)
        return JSONResponse(result)

    @router.post("/api/runs/{run_id}/stop")
    def api_run_stop(run_id: str) -> JSONResponse:
        run_id = core._safe_run_id(run_id)
        meta_path = core._runs_root() / f"{run_id}.json"
        meta = core._read_json(meta_path)
        if not meta:
            raise HTTPException(status_code=404, detail="Run not found.")
        if meta.get("status") != "running":
            return JSONResponse({"status": "ignored", "message": "Run is not running."})

        pid = meta.get("pid")
        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass

        meta["status"] = "cancelled"
        meta["finished_at"] = datetime.now().isoformat(timespec="seconds")
        meta["returncode"] = -1
        core._write_json(meta_path, meta)
        return JSONResponse({"status": "cancelled", "run_id": run_id})

    @router.get("/api/runs/{run_id}")
    def api_run_status(run_id: str) -> JSONResponse:
        run_id = core._safe_run_id(run_id)
        core._reconcile_running_jobs()
        meta_path = core._runs_root() / f"{run_id}.json"
        meta = core._read_json(meta_path)
        if not meta:
            raise HTTPException(status_code=404, detail="Run not found.")

        log_path = Path(meta.get("log_path") or "")
        log_text = core._tail_text(log_path, max_bytes=8000)
        return JSONResponse({"run": meta, "log_tail": log_text})

    return router
