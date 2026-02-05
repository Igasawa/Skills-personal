from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
SKILL_ROOT = BASE_DIR.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

YM_RE = re.compile(r"^\d{4}-\d{2}$")
RUN_ID_RE = re.compile(r"^run_\d{8}_\d{6}$")
ORDER_ID_RE = re.compile(r"^[0-9A-Za-z-]+$")
SAFE_NAME_RE = re.compile(r"^[^/\\\\]+$")

DEFAULT_AMAZON_URL = "https://www.amazon.co.jp/gp/your-account/order-history"
DEFAULT_RAKUTEN_URL = "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
DEFAULT_MFCLOUD_ACCOUNTS_URL = "https://expense.moneyforward.com/accounts"

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _artifact_root() -> Path:
    return _ax_home() / "artifacts" / "mfcloud-expense-receipt-reconcile"


def _runs_root() -> Path:
    return _artifact_root() / "_runs"


def _preflight_global_path() -> Path:
    return _artifact_root() / "_preflight.json"


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _compact_mf_summary(vendor: str, memo: str) -> str:
    raw = f"{vendor} {memo}".strip()
    raw = raw.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    raw = re.sub(r"\s+", " ", raw).strip()

    raw = re.sub(r"^(?:\d+\s+){1,4}", "", raw).strip()
    raw = re.sub(r"^\d{4}/\d{1,2}/\d{1,2}\([^)]+\)\s*", "", raw).strip()

    noise_tokens = [
        "下書き",
        "アラート",
        "対象外",
        "本部",
        "詳細",
        "削除",
        "未精算",
        "精算済み",
        "経費",
        "領収書",
        "請求書",
        "添付",
        "未添付",
    ]
    for token in noise_tokens:
        raw = raw.replace(token, " ")

    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _load_exclusions(reports_dir: Path) -> set[tuple[str, str]]:
    path = reports_dir / "exclude_orders.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return set()
    items = data.get("exclude")
    if not isinstance(items, list):
        return set()
    out: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        order_id = str(item.get("order_id") or "").strip()
        if source not in {"amazon", "rakuten"}:
            continue
        if not order_id or not ORDER_ID_RE.match(order_id):
            continue
        out.add((source, order_id))
    return out


def _workflow_path(reports_dir: Path) -> Path:
    return reports_dir / "workflow.json"


def _read_workflow(reports_dir: Path) -> dict[str, Any]:
    data = _read_json(_workflow_path(reports_dir))
    return data if isinstance(data, dict) else {}


def _write_workflow(reports_dir: Path, data: dict[str, Any]) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    _write_json(_workflow_path(reports_dir), data)


def _collect_orders(root: Path, ym: str, exclusions: set[tuple[str, str]]) -> list[dict[str, Any]]:
    status_labels = {
        "ok": "取得済み",
        "no_receipt": "領収書なし",
        "out_of_month": "対象外",
        "unknown_date": "日付不明",
        "error": "エラー",
        "gift_card": "ギフト券",
        "filtered_payment_method": "支払い方法除外",
    }

    raw: list[dict[str, Any]] = []
    for source in ("amazon", "rakuten"):
        path = root / source / "orders.jsonl"
        for obj in _read_jsonl(path):
            order_id = str(obj.get("order_id") or "").strip() or None
            order_date = str(obj.get("order_date") or "").strip() or None
            if order_date and not order_date.startswith(ym):
                continue
            status = str(obj.get("status") or "").strip() or "ok"
            total = obj.get("total_yen") if obj.get("total_yen") is not None else obj.get("total")
            item_name = str(obj.get("item_name") or "").strip() or None
            raw.append(
                {
                    "source": source,
                    "order_id": order_id,
                    "order_date": order_date,
                    "total_yen": total,
                    "status": status,
                    "item_name": item_name,
                    "include_flag": obj.get("include"),
                    "has_pdf": bool(obj.get("pdf_path")),
                }
            )

    def score(r: dict[str, Any]) -> int:
        s = 0
        if r.get("has_pdf"):
            s += 4
        if r.get("total_yen") not in (None, ""):
            s += 2
        if r.get("item_name"):
            s += 1
        if r.get("order_date"):
            s += 1
        return s

    def merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        base, other = (a, b) if score(a) >= score(b) else (b, a)
        if not base.get("order_date") and other.get("order_date"):
            base["order_date"] = other["order_date"]
        if base.get("total_yen") in (None, "") and other.get("total_yen") not in (None, ""):
            base["total_yen"] = other["total_yen"]
        if not base.get("item_name") and other.get("item_name"):
            base["item_name"] = other["item_name"]
        elif base.get("item_name") and other.get("item_name") and base.get("item_name") != other.get("item_name"):
            names: list[str] = []
            for name in (base.get("item_name"), other.get("item_name")):
                if name and name not in names:
                    names.append(name)
            base["item_name"] = " / ".join(names[:2])
        if base.get("status") in {"unknown_date", "error"} and other.get("status") not in {"unknown_date", "error"}:
            base["status"] = other["status"]
        base["has_pdf"] = base.get("has_pdf") or other.get("has_pdf")
        if base.get("include_flag") is None and other.get("include_flag") is not None:
            base["include_flag"] = other.get("include_flag")
        return base

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []
    for rec in raw:
        order_id = rec.get("order_id")
        if not order_id:
            if not rec.get("has_pdf") and rec.get("status") in {"unknown_date", "error"}:
                continue
            extras.append(rec)
            continue
        key = (rec.get("source"), order_id)
        if key in merged:
            merged[key] = merge(merged[key], rec)
        else:
            merged[key] = rec

    records = list(merged.values()) + extras

    out: list[dict[str, Any]] = []
    for rec in records:
        status = str(rec.get("status") or "ok")
        order_id = rec.get("order_id")
        auto_excluded = status == "gift_card"
        default_excluded = rec.get("include_flag") is False and not auto_excluded
        excluded = auto_excluded or default_excluded or (order_id and (rec.get("source"), order_id) in exclusions)
        can_toggle = bool(order_id) and not auto_excluded
        out.append(
            {
                "source": rec.get("source"),
                "source_label": "Amazon" if rec.get("source") == "amazon" else "楽天",
                "order_id": order_id,
                "order_date": rec.get("order_date"),
                "total_yen": rec.get("total_yen"),
                "item_name": rec.get("item_name"),
                "status": status,
                "status_label": status_labels.get(status, status),
                "has_pdf": bool(rec.get("has_pdf")),
                "excluded": excluded,
                "auto_excluded": auto_excluded,
                "can_toggle": can_toggle,
            }
        )

    out.sort(key=lambda x: (x.get("order_date") or "", x.get("order_id") or ""))
    return out


def _resolve_pdf_path(root: Path, source: str, name_or_path: Any) -> Path | None:
    if source not in {"amazon", "rakuten"}:
        return None
    if not name_or_path:
        return None
    raw = str(name_or_path)
    if not raw:
        return None
    p = Path(raw)
    try:
        if not p.is_absolute():
            p = (root / source / "pdfs" / p).resolve()
        else:
            p = p.resolve()
    except Exception:
        return None
    base = (root / source / "pdfs").resolve()
    try:
        p.relative_to(base)
    except Exception:
        return None
    if p.suffix.lower() != ".pdf":
        return None
    if not p.exists():
        return None
    return p


def _collect_excluded_pdfs(root: Path, ym: str, exclusions: set[tuple[str, str]]) -> list[dict[str, Any]]:
    status_labels = {
        "ok": "取得済み",
        "no_receipt": "領収書なし",
        "out_of_month": "対象外",
        "unknown_date": "日付不明",
        "error": "エラー",
        "gift_card": "ギフト券",
        "filtered_payment_method": "支払方法除外",
    }
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source in ("amazon", "rakuten"):
        path = root / source / "orders.jsonl"
        for obj in _read_jsonl(path):
            order_id = str(obj.get("order_id") or "").strip() or None
            order_date = str(obj.get("order_date") or "").strip() or None
            if order_date and not order_date.startswith(ym):
                continue
            status = str(obj.get("status") or "").strip() or "ok"
            total = obj.get("total_yen") if obj.get("total_yen") is not None else obj.get("total")
            item_name = str(obj.get("item_name") or "").strip() or None
            include_flag = obj.get("include")
            auto_excluded = status == "gift_card"
            default_excluded = include_flag is False and not auto_excluded
            excluded = auto_excluded or default_excluded or (order_id and (source, order_id) in exclusions)
            if not excluded:
                continue
            pdf_path = _resolve_pdf_path(root, source, obj.get("pdf_path"))
            if not pdf_path:
                continue
            key = (source, order_id or "", pdf_path.name)
            if key in records:
                continue
            records[key] = {
                "source": source,
                "source_label": "Amazon" if source == "amazon" else "楽天",
                "order_id": order_id,
                "order_date": order_date,
                "total_yen": total,
                "item_name": item_name,
                "status": status,
                "status_label": status_labels.get(status, status),
                "pdf_name": pdf_path.name,
                "pdf_size_kb": max(1, int(pdf_path.stat().st_size / 1024)),
                "excluded_reason": "自動除外" if auto_excluded or default_excluded else "手動除外",
            }

    rows = list(records.values())
    rows.sort(key=lambda x: (x.get("source") or "", x.get("order_date") or "", x.get("order_id") or ""))
    return rows



def _ym_default(now: date | None = None) -> tuple[int, int]:
    d = now or date.today()
    if d.month == 1:
        return d.year - 1, 12
    return d.year, d.month - 1


def _parse_csv_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value).split(",") if s.strip()]


def _format_allowlist(value: Any) -> str:
    return ", ".join(_parse_csv_list(value))


def _scan_artifacts() -> list[dict[str, Any]]:
    root = _artifact_root()
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        if p.name == "_runs":
            continue
        if not YM_RE.match(p.name):
            continue

        reports_dir = p / "reports"
        missing_json = reports_dir / "missing_evidence_candidates.json"
        run_config = p / "run_config.resolved.json"

        data = _read_json(missing_json) or {}
        counts = data.get("counts") if isinstance(data, dict) else {}
        rows = data.get("rows") if isinstance(data, dict) else None
        rows_count = len(rows) if isinstance(rows, list) else None

        amazon_pdfs = list((p / "amazon" / "pdfs").glob("*.pdf")) if (p / "amazon" / "pdfs").exists() else []
        rakuten_pdfs = list((p / "rakuten" / "pdfs").glob("*.pdf")) if (p / "rakuten" / "pdfs").exists() else []

        items.append(
            {
                "ym": p.name,
                "path": str(p),
                "has_reports": reports_dir.exists(),
                "counts": counts or {},
                "report_rows": rows_count,
                "amazon_pdf_count": len(amazon_pdfs),
                "rakuten_pdf_count": len(rakuten_pdfs),
                "run_config": _read_json(run_config) or {},
            }
        )

    items.sort(key=lambda x: x["ym"], reverse=True)
    return items


def _scan_run_jobs() -> list[dict[str, Any]]:
    _reconcile_running_jobs()
    root = _runs_root()
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for p in root.glob("run_*.json"):
        data = _read_json(p) or {}
        if not data:
            continue
        items.append(data)
    items.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return items


def _running_job_exists() -> bool:
    for job in _scan_run_jobs():
        if job.get("status") == "running":
            return True
    return False


def _get_latest_running_job() -> dict[str, Any] | None:
    for job in _scan_run_jobs():
        if job.get("status") == "running":
            return job
    return None


def _latest_run_config() -> dict[str, Any]:
    for item in _scan_artifacts():
        cfg = item.get("run_config")
        if isinstance(cfg, dict) and cfg:
            return cfg
    return {}


def _load_config_file() -> dict[str, Any]:
    config_path = _ax_home() / "configs" / "mfcloud-expense-receipt-reconcile.json"
    data = _read_json(config_path)
    return data if isinstance(data, dict) else {}


def _resolve_form_defaults() -> dict[str, Any]:
    year, month = _ym_default()
    defaults: dict[str, Any] = {
        "year": year,
        "month": month,
        "mfcloud_url": "",
        "rakuten_enabled": False,
        "rakuten_allowlist": "",
        "notes": "",
        "rakuten_orders_url": DEFAULT_RAKUTEN_URL,
        "amazon_orders_url": DEFAULT_AMAZON_URL,
    }

    last_run = _latest_run_config()
    if last_run:
        defaults["year"] = last_run.get("year") or defaults["year"]
        defaults["month"] = last_run.get("month") or defaults["month"]
        urls = last_run.get("urls") if isinstance(last_run.get("urls"), dict) else {}
        defaults["mfcloud_url"] = urls.get("mfcloud_expense_list") or defaults["mfcloud_url"]
        defaults["amazon_orders_url"] = urls.get("amazon_orders") or defaults["amazon_orders_url"]
        rakuten = last_run.get("rakuten") if isinstance(last_run.get("rakuten"), dict) else {}
        defaults["rakuten_enabled"] = bool(rakuten.get("enabled", defaults["rakuten_enabled"]))
        defaults["rakuten_allowlist"] = _format_allowlist(
            rakuten.get("payment_method_allowlist") or defaults["rakuten_allowlist"]
        )
        defaults["rakuten_orders_url"] = rakuten.get("orders_url") or defaults["rakuten_orders_url"]
        defaults["notes"] = last_run.get("monthly_notes") or defaults["notes"]

    config = _load_config_file()
    cfg = config.get("config") if isinstance(config.get("config"), dict) else {}
    urls = cfg.get("urls") if isinstance(cfg.get("urls"), dict) else {}
    rakuten = cfg.get("rakuten") if isinstance(cfg.get("rakuten"), dict) else {}
    defaults["mfcloud_url"] = urls.get("mfcloud_expense_list") or defaults["mfcloud_url"]
    defaults["amazon_orders_url"] = urls.get("amazon_orders") or defaults["amazon_orders_url"]
    defaults["rakuten_enabled"] = bool(rakuten.get("enabled", defaults["rakuten_enabled"]))
    defaults["rakuten_allowlist"] = _format_allowlist(
        rakuten.get("payment_method_allowlist") or defaults["rakuten_allowlist"]
    )
    defaults["rakuten_orders_url"] = rakuten.get("orders_url") or defaults["rakuten_orders_url"]
    defaults["notes"] = cfg.get("monthly_notes") or defaults["notes"]

    return defaults


def _tail_text(path: Path, max_bytes: int = 5000) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _mark_preflight_started(year: int, month: int) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    data = {"status": "started", "started_at": ts, "year": year, "month": month}
    output_root = _artifact_root() / f"{year:04d}-{month:02d}"
    reports_dir = output_root / "reports"
    _write_json(reports_dir / "preflight.json", data)
    _write_json(_preflight_global_path(), data)


def _pid_alive(pid: Any) -> bool:
    if not pid:
        return False
    try:
        pid_int = int(pid)
    except Exception:
        return False
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid_int}"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return True
        return re.search(rf"\\b{pid_int}\\b", out) is not None
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


def _reconcile_running_jobs() -> None:
    root = _runs_root()
    if not root.exists():
        return
    for p in root.glob("run_*.json"):
        data = _read_json(p)
        if not isinstance(data, dict):
            continue
        if data.get("status") != "running":
            continue
        if _pid_alive(data.get("pid")):
            continue
        data["status"] = "failed"
        if not data.get("finished_at"):
            data["finished_at"] = datetime.now().isoformat(timespec="seconds")
        if data.get("returncode") is None:
            data["returncode"] = -1
        _write_json(p, data)


def _run_worker(process: subprocess.Popen, meta_path: Path) -> None:
    exit_code = process.wait()
    meta = _read_json(meta_path) or {}
    meta["status"] = "success" if exit_code == 0 else "failed"
    meta["finished_at"] = datetime.now().isoformat(timespec="seconds")
    meta["returncode"] = exit_code
    _write_json(meta_path, meta)


def _start_run(payload: dict[str, Any]) -> dict[str, Any]:
    if _running_job_exists():
        raise HTTPException(status_code=409, detail="Another run is already in progress.")

    mode = str(payload.get("mode") or "full").strip()
    valid_modes = {"preflight", "amazon_download", "rakuten_download", "amazon_print", "rakuten_print", "mf_reconcile"}
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail="Invalid mode.")

    try:
        year = int(payload.get("year"))
        month = int(payload.get("month"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid year/month.") from exc
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")
    mfcloud_url = str(payload.get("mfcloud_url") or "").strip()
    if mode == "mf_reconcile" and not mfcloud_url:
        raise HTTPException(status_code=400, detail="MF Cloud expense list URL is required.")

    rakuten_enabled = bool(payload.get("rakuten_enabled"))
    rakuten_allowlist = str(payload.get("rakuten_allowlist") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    rakuten_orders_url = str(payload.get("rakuten_orders_url") or DEFAULT_RAKUTEN_URL)

    runs_root = _runs_root()
    runs_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{ts}"
    log_path = runs_root / f"{run_id}.log"
    meta_path = runs_root / f"{run_id}.json"

    auth_handoff = bool(payload.get("auth_handoff", True))
    auto_receipt_name = bool(payload.get("auto_receipt_name", True))
    skip_receipt_name = not auto_receipt_name
    cmd = [
        sys.executable,
        "-u",
        "scripts/run.py",
        "--year",
        str(year),
        "--month",
        str(month),
    ]
    if auth_handoff:
        cmd += ["--interactive", "--headed"]
    else:
        cmd += ["--non-interactive", "--headless"]
    if mfcloud_url:
        cmd += ["--mfcloud-expense-list-url", mfcloud_url]
    if notes:
        cmd += ["--notes", notes]
    if skip_receipt_name:
        cmd += ["--skip-receipt-name"]

    if mode == "preflight":
        _mark_preflight_started(year, month)
        cmd += ["--preflight", "--mfcloud-accounts-url", DEFAULT_MFCLOUD_ACCOUNTS_URL]
    elif mode in {"amazon_download", "amazon_print"}:
        cmd += ["--skip-mfcloud", "--skip-rakuten", "--skip-reconcile"]
        if mode == "amazon_print":
            cmd += ["--print-list", "--print-sources", "amazon"]
    elif mode in {"rakuten_download", "rakuten_print"}:
        cmd += [
            "--skip-mfcloud",
            "--skip-amazon",
            "--skip-reconcile",
            "--enable-rakuten",
            "--rakuten-allow-payment-methods",
            rakuten_allowlist,
        ]
        if mode == "rakuten_print":
            cmd += ["--print-list", "--print-sources", "rakuten"]
        if rakuten_orders_url:
            cmd += ["--rakuten-orders-url", rakuten_orders_url]
    elif mode == "mf_reconcile":
        cmd += ["--skip-amazon", "--skip-rakuten"]
        output_root = _artifact_root() / f"{year:04d}-{month:02d}"
        if (output_root / "rakuten" / "orders.jsonl").exists():
            cmd += ["--enable-rakuten"]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            cmd,
            cwd=str(SKILL_ROOT),
            stdout=log,
            stderr=log,
            env=env,
        )

    meta = {
        "run_id": run_id,
        "status": "running",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "pid": process.pid,
        "log_path": str(log_path),
        "cmd": cmd,
        "params": {
            "year": year,
            "month": month,
            "mfcloud_url": mfcloud_url,
            "rakuten_enabled": rakuten_enabled,
            "rakuten_allowlist": rakuten_allowlist,
            "notes": notes,
            "rakuten_orders_url": rakuten_orders_url,
            "mode": mode,
            "auth_handoff": auth_handoff,
            "auto_receipt_name": auto_receipt_name,
        },
    }
    _write_json(meta_path, meta)

    watcher = threading.Thread(target=_run_worker, args=(process, meta_path), daemon=True)
    watcher.start()

    return {"run_id": run_id, "status": "running"}


def _safe_ym(ym: str) -> str:
    if not YM_RE.match(ym):
        raise HTTPException(status_code=400, detail="Invalid year-month format.")
    return ym


def _safe_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id.")
    return run_id


def _split_ym(ym: str) -> tuple[int, int]:
    return int(ym[:4]), int(ym[5:7])


def _running_mode_for_ym(year: int, month: int) -> str | None:
    for job in _scan_run_jobs():
        if job.get("status") != "running":
            continue
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        if params.get("year") == year and params.get("month") == month:
            return str(params.get("mode") or "")
    return None


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    artifacts = _scan_artifacts()
    jobs = _scan_run_jobs()
    running_job = _get_latest_running_job()
    defaults = _resolve_form_defaults()
    latest_artifact = artifacts[0] if artifacts else None
    latest_job = jobs[0] if jobs else None
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "artifacts": artifacts,
            "latest_artifact": latest_artifact,
            "latest_job": latest_job,
            "running_job": running_job,
            "defaults": defaults,
            "ax_home": str(_ax_home()),
        },
    )


@app.get("/runs/{ym}", response_class=HTMLResponse)
def run_detail(request: Request, ym: str) -> HTMLResponse:
    ym = _safe_ym(ym)
    root = _artifact_root() / ym
    if not root.exists():
        raise HTTPException(status_code=404, detail="Run not found.")

    reports_dir = root / "reports"
    missing_json = reports_dir / "missing_evidence_candidates.json"
    data = _read_json(missing_json) or {}
    rows = data.get("rows") if isinstance(data, dict) else []
    counts = data.get("counts") if isinstance(data, dict) else {}
    rows = rows if isinstance(rows, list) else []
    for row in rows:
        vendor = str(row.get("mf_vendor") or "")
        memo = str(row.get("mf_memo") or "")
        summary = _compact_mf_summary(vendor, memo)
        row["mf_summary"] = summary if summary else " ".join([vendor, memo]).strip()
        amount = row.get("mf_amount_yen")
        if isinstance(amount, (int, float)):
            row["mf_amount_label"] = f"{int(amount):,}円"
        elif isinstance(amount, str) and amount.strip().isdigit():
            row["mf_amount_label"] = f"{int(amount.strip()):,}円"
        else:
            row["mf_amount_label"] = "-"

    exclusions = _load_exclusions(reports_dir)
    orders = _collect_orders(root, ym, exclusions)
    excluded_count = sum(1 for o in orders if o.get("excluded"))

    amazon_pdfs = list((root / "amazon" / "pdfs").glob("*.pdf")) if (root / "amazon" / "pdfs").exists() else []
    rakuten_pdfs = list((root / "rakuten" / "pdfs").glob("*.pdf")) if (root / "rakuten" / "pdfs").exists() else []

    print_script = reports_dir / "print_all.ps1"
    print_command = ""
    if print_script.exists():
        print_command = f'powershell -NoProfile -ExecutionPolicy Bypass -File "{print_script}"'

    return TEMPLATES.TemplateResponse(
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
                "print_script": "印刷用スクリプト",
            },
        },
    )


@app.get("/runs/{ym}/excluded-pdfs", response_class=HTMLResponse)
def run_excluded_pdfs(request: Request, ym: str) -> HTMLResponse:
    ym = _safe_ym(ym)
    root = _artifact_root() / ym
    if not root.exists():
        raise HTTPException(status_code=404, detail="Run not found.")
    reports_dir = root / "reports"
    exclusions = _load_exclusions(reports_dir)
    rows = _collect_excluded_pdfs(root, ym, exclusions)
    amazon_count = sum(1 for r in rows if r.get("source") == "amazon")
    rakuten_count = sum(1 for r in rows if r.get("source") == "rakuten")
    return TEMPLATES.TemplateResponse(
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


@app.get("/files/{ym}/{kind}")
def download_file(ym: str, kind: str) -> FileResponse:
    ym = _safe_ym(ym)
    root = _artifact_root() / ym
    if not root.exists():
        raise HTTPException(status_code=404, detail="Run not found.")

    mapping = {
        "missing_csv": root / "reports" / "missing_evidence_candidates.csv",
        "missing_json": root / "reports" / "missing_evidence_candidates.json",
        "monthly_thread": root / "reports" / "monthly_thread.md",
        "run_config": root / "run_config.resolved.json",
        "print_script": root / "reports" / "print_all.ps1",
    }
    if kind not in mapping:
        raise HTTPException(status_code=404, detail="File not found.")
    path = mapping[kind]
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)


@app.get("/files/{ym}/pdf/{source}/{filename}")
def download_pdf(ym: str, source: str, filename: str) -> FileResponse:
    ym = _safe_ym(ym)
    if source not in {"amazon", "rakuten"}:
        raise HTTPException(status_code=404, detail="File not found.")
    if not filename or not SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="File not found.")
    root = _artifact_root() / ym
    path = _resolve_pdf_path(root, source, filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/steps/{ym}")
def api_steps(ym: str) -> JSONResponse:
    ym = _safe_ym(ym)
    year, month = _split_ym(ym)
    root = _artifact_root() / ym
    reports_dir = root / "reports"
    workflow = _read_workflow(reports_dir)

    preflight_done = (reports_dir / "preflight.json").exists() or _preflight_global_path().exists()
    amazon_downloaded = (root / "amazon" / "orders.jsonl").exists()
    rakuten_downloaded = (root / "rakuten" / "orders.jsonl").exists()
    amazon_confirmed = bool((workflow.get("amazon") or {}).get("confirmed_at"))
    amazon_printed = bool((workflow.get("amazon") or {}).get("printed_at"))
    rakuten_confirmed = bool((workflow.get("rakuten") or {}).get("confirmed_at"))
    rakuten_printed = bool((workflow.get("rakuten") or {}).get("printed_at"))
    mf_reconciled = (reports_dir / "missing_evidence_candidates.json").exists()
    running_mode = _running_mode_for_ym(year, month)

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


@app.get("/api/exclusions/{ym}")
def api_get_exclusions(ym: str) -> JSONResponse:
    ym = _safe_ym(ym)
    root = _artifact_root() / ym / "reports"
    data = _read_json(root / "exclude_orders.json")
    if not isinstance(data, dict):
        data = {"ym": ym, "exclude": []}
    return JSONResponse(data)


@app.post("/api/exclusions/{ym}")
def api_set_exclusions(ym: str, payload: dict[str, Any]) -> JSONResponse:
    ym = _safe_ym(ym)
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
        if not order_id or not ORDER_ID_RE.match(order_id):
            continue
        key = (source, order_id)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"source": source, "order_id": order_id})

    reports_dir = _artifact_root() / ym / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    data = {"ym": ym, "exclude": cleaned, "updated_at": datetime.now().isoformat(timespec="seconds")}
    _write_json(reports_dir / "exclude_orders.json", data)
    source = str(payload.get("source") or "").strip()
    if source in {"amazon", "rakuten"}:
        wf = _read_workflow(reports_dir)
        section = wf.get(source) if isinstance(wf.get(source), dict) else {}
        section["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
        wf[source] = section
        _write_workflow(reports_dir, wf)

    return JSONResponse({"status": "ok", "count": len(cleaned)})


@app.post("/api/print/{ym}/{source}")
def api_print(ym: str, source: str) -> JSONResponse:
    ym = _safe_ym(ym)
    if source not in {"amazon", "rakuten"}:
        raise HTTPException(status_code=400, detail="Invalid source.")

    year, month = _split_ym(ym)
    output_root = _artifact_root() / ym
    scripts_dir = SKILL_ROOT / "scripts"
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
    wf = _read_workflow(reports_dir)
    section = wf.get(source) if isinstance(wf.get(source), dict) else {}
    section["printed_at"] = datetime.now().isoformat(timespec="seconds")
    wf[source] = section
    _write_workflow(reports_dir, wf)

    return JSONResponse({"status": "ok", "source": source})


@app.post("/api/print-pdf/{ym}/{source}/{filename}")
def api_print_pdf(ym: str, source: str, filename: str) -> JSONResponse:
    ym = _safe_ym(ym)
    if source not in {"amazon", "rakuten"}:
        raise HTTPException(status_code=404, detail="PDF not found.")
    if not filename or not SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="PDF not found.")
    root = _artifact_root() / ym
    path = _resolve_pdf_path(root, source, filename)
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


@app.post("/api/runs")
def api_run(payload: dict[str, Any]) -> JSONResponse:
    result = _start_run(payload)
    return JSONResponse(result)


@app.post("/api/runs/{run_id}/stop")
def api_run_stop(run_id: str) -> JSONResponse:
    run_id = _safe_run_id(run_id)
    meta_path = _runs_root() / f"{run_id}.json"
    meta = _read_json(meta_path)
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
    _write_json(meta_path, meta)
    return JSONResponse({"status": "cancelled", "run_id": run_id})


@app.get("/api/runs/{run_id}")
def api_run_status(run_id: str) -> JSONResponse:
    run_id = _safe_run_id(run_id)
    _reconcile_running_jobs()
    meta_path = _runs_root() / f"{run_id}.json"
    meta = _read_json(meta_path)
    if not meta:
        raise HTTPException(status_code=404, detail="Run not found.")

    log_path = Path(meta.get("log_path") or "")
    log_text = _tail_text(log_path, max_bytes=8000)
    return JSONResponse({"run": meta, "log_tail": log_text})
