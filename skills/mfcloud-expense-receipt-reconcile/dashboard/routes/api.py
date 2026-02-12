from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pypdf import PdfReader, PdfWriter

from services import core


def create_api_router() -> APIRouter:
    router = APIRouter()
    WORKSPACE_MAX_LINKS = 100
    WORKSPACE_MAX_LABEL_CHARS = 80
    WORKSPACE_MAX_PROMPT_ENTRIES = 200
    WORKSPACE_MAX_PROMPT_CHARS = 50000
    WORKSPACE_MAX_NOTE_ENTRIES = 400
    WORKSPACE_MAX_NOTE_CHARS = 4000
    WORKSPACE_DEFAULT_PROMPT_KEY = "mf_expense_reports"

    def _actor_from_request(request: Request) -> dict[str, str]:
        ip = request.client.host if request.client else ""
        ua = str(request.headers.get("user-agent") or "").strip()
        return {
            "channel": "dashboard",
            "id": "local_user",
            "ip": ip,
            "user_agent": ua[:300],
        }

    def _try_year_month(payload: dict[str, Any]) -> tuple[int, int] | None:
        try:
            year = int(payload.get("year"))
            month = int(payload.get("month"))
        except Exception:
            return None
        if month < 1 or month > 12:
            return None
        return year, month

    def _open_directory(path: Path) -> subprocess.CompletedProcess[str]:
        if sys.platform.startswith("win"):
            cmd = ["explorer", str(path)]
        elif sys.platform == "darwin":
            cmd = ["open", str(path)]
        else:
            cmd = ["xdg-open", str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        # Windows explorer occasionally returns non-zero even when the folder
        # actually opened (no stdout/stderr, existing target).
        if (
            sys.platform.startswith("win")
            and result.returncode != 0
            and path.exists()
            and not str(result.stdout or "").strip()
            and not str(result.stderr or "").strip()
        ):
            return subprocess.CompletedProcess(
                args=result.args,
                returncode=0,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def _workspace_state_path() -> Path:
        return core._artifact_root() / "_workspace" / "workspace_state.json"

    def _workspace_default_state() -> dict[str, Any]:
        return {
            "links": [],
            "prompts": {},
            "link_notes": {},
            "active_prompt_key": WORKSPACE_DEFAULT_PROMPT_KEY,
            "revision": 0,
            "updated_at": None,
        }

    def _normalize_workspace_label(value: Any) -> str:
        return " ".join(str(value or "").strip().split())[:WORKSPACE_MAX_LABEL_CHARS]

    def _normalize_workspace_url(value: Any) -> str | None:
        url = str(value or "").strip()
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        if not parsed.netloc:
            return None
        return parsed.geturl()

    def _sanitize_workspace_links(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in value:
            if not isinstance(row, dict):
                continue
            url = _normalize_workspace_url(row.get("url"))
            if not url:
                continue
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            label = _normalize_workspace_label(row.get("label"))
            if not label:
                label = urlparse(url).netloc or url
            out.append({"label": label, "url": url})
            if len(out) >= WORKSPACE_MAX_LINKS:
                break
        return out

    def _is_valid_prompt_key(key: Any) -> bool:
        text = str(key or "").strip()
        if not text:
            return False
        if text == WORKSPACE_DEFAULT_PROMPT_KEY:
            return True
        return text.startswith("custom:")

    def _sanitize_workspace_prompts(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, str] = {}
        for key, raw in value.items():
            prompt_key = str(key or "").strip()
            if not _is_valid_prompt_key(prompt_key):
                continue
            text = str(raw or "")
            if len(text) > WORKSPACE_MAX_PROMPT_CHARS:
                text = text[:WORKSPACE_MAX_PROMPT_CHARS]
            out[prompt_key] = text
            if len(out) >= WORKSPACE_MAX_PROMPT_ENTRIES:
                break
        return out

    def _sanitize_workspace_link_notes(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, str] = {}
        for key, raw in value.items():
            note_key = str(key or "").strip()
            if not _is_valid_prompt_key(note_key):
                continue
            text = str(raw or "")
            if len(text) > WORKSPACE_MAX_NOTE_CHARS:
                text = text[:WORKSPACE_MAX_NOTE_CHARS]
            out[note_key] = text
            if len(out) >= WORKSPACE_MAX_NOTE_ENTRIES:
                break
        return out

    def _sanitize_workspace_active_prompt_key(value: Any) -> str:
        key = str(value or "").strip()
        if _is_valid_prompt_key(key):
            return key
        return WORKSPACE_DEFAULT_PROMPT_KEY

    def _normalize_workspace_state(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return _workspace_default_state()
        links = _sanitize_workspace_links(payload.get("links"))
        prompts = _sanitize_workspace_prompts(payload.get("prompts"))
        link_notes = _sanitize_workspace_link_notes(payload.get("link_notes"))
        active_prompt_key = _sanitize_workspace_active_prompt_key(payload.get("active_prompt_key"))
        revision = core._safe_non_negative_int(payload.get("revision"), default=0)
        updated_at = str(payload.get("updated_at") or "").strip() or None
        return {
            "links": links,
            "prompts": prompts,
            "link_notes": link_notes,
            "active_prompt_key": active_prompt_key,
            "revision": int(revision),
            "updated_at": updated_at,
        }

    def _read_workspace_state() -> dict[str, Any]:
        state = _normalize_workspace_state(core._read_json(_workspace_state_path()))
        if not state.get("active_prompt_key"):
            state["active_prompt_key"] = WORKSPACE_DEFAULT_PROMPT_KEY
        state["revision"] = core._safe_non_negative_int(state.get("revision"), default=0)
        return state

    def _write_workspace_state(state: dict[str, Any], *, revision: int | None = None) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        sanitized = _normalize_workspace_state(state)
        if revision is None:
            current = _normalize_workspace_state(core._read_json(_workspace_state_path()))
            next_revision = core._safe_non_negative_int(current.get("revision"), default=0) + 1
        else:
            next_revision = core._safe_non_negative_int(revision, default=0)
        sanitized["revision"] = int(next_revision)
        sanitized["updated_at"] = now
        path = _workspace_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        core._write_json(path, sanitized)
        return sanitized

    def _merge_workspace_links(
        client_links: list[dict[str, str]],
        server_links: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        merged: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in [*client_links, *server_links]:
            if not isinstance(row, dict):
                continue
            url = _normalize_workspace_url(row.get("url"))
            if not url:
                continue
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            label = _normalize_workspace_label(row.get("label"))
            if not label:
                label = urlparse(url).netloc or url
            merged.append({"label": label, "url": url})
            if len(merged) >= WORKSPACE_MAX_LINKS:
                break
        return merged

    def _merge_workspace_prompts(client_prompts: dict[str, str], server_prompts: dict[str, str]) -> dict[str, str]:
        merged = dict(server_prompts)
        merged.update(client_prompts)
        return _sanitize_workspace_prompts(merged)

    def _merge_workspace_link_notes(client_notes: dict[str, str], server_notes: dict[str, str]) -> dict[str, str]:
        merged = dict(server_notes)
        merged.update(client_notes)
        return _sanitize_workspace_link_notes(merged)

    def _extract_print_file_paths(manifest: dict[str, Any] | None) -> list[str]:
        if not isinstance(manifest, dict):
            return []
        rows = manifest.get("files")
        if not isinstance(rows, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            out.append(path)
        return out

    def _write_manual_open_print_script(path: Path, files: list[str]) -> None:
        lines = [
            "$ErrorActionPreference = 'Continue'",
            "$files = @(",
        ]
        lines += [f'  "{p}"' for p in files]
        lines += [
            ")",
            "$opened = 0",
            "$failed = 0",
            "$missing = 0",
            "foreach ($f in $files) {",
            "  if (-not (Test-Path $f)) {",
            "    Write-Warning (\"missing: \" + $f)",
            "    $missing += 1",
            "    continue",
            "  }",
            "  try {",
            "    Start-Process -FilePath $f -ErrorAction Stop",
            "    $opened += 1",
            "  } catch {",
            "    Write-Warning (\"open_failed: \" + $f + \" :: \" + $_.Exception.Message)",
            "    $failed += 1",
            "  }",
            "  Start-Sleep -Milliseconds 300",
            "}",
            "Write-Output (\"print_summary opened=\" + $opened + \" failed=\" + $failed + \" missing=\" + $missing + \" total=\" + $files.Count)",
            "if ($failed -gt 0) {",
            "  exit 1",
            "}",
            "exit 0",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _safe_print_source(source: str) -> str:
        normalized = str(source or "").strip().lower()
        if normalized not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=400, detail="source must be amazon or rakuten.")
        return normalized

    def _source_manifest_path(reports_dir: Path, source: str) -> Path:
        return reports_dir / f"print_manifest.{source}.json"

    def _source_list_path(reports_dir: Path, source: str) -> Path:
        return reports_dir / f"print_list.{source}.txt"

    def _open_file(path: Path) -> subprocess.CompletedProcess[str]:
        if sys.platform.startswith("win"):
            cmd = ["explorer", str(path)]
        elif sys.platform == "darwin":
            cmd = ["open", str(path)]
        else:
            cmd = ["xdg-open", str(path)]
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def _desktop_shortcut_root() -> Path:
        override = str(os.environ.get("AX_DASHBOARD_SHORTCUT_DIR") or "").strip()
        if override:
            root = Path(override).expanduser()
        else:
            root = Path.home() / "Desktop"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _write_folder_shortcut(target: Path, shortcut_name: str) -> Path | None:
        if not sys.platform.startswith("win"):
            return None
        clean_name = str(shortcut_name or "").strip()
        if not clean_name:
            return None
        shortcut_path = _desktop_shortcut_root() / f"{clean_name}.url"
        content = (
            "[InternetShortcut]\n"
            f"URL={target.resolve().as_uri()}\n"
            "IconFile=explorer.exe\n"
            "IconIndex=0\n"
        )
        shortcut_path.write_text(content, encoding="utf-8")
        return shortcut_path

    def _merge_pdfs(input_paths: list[Path], merged_path: Path) -> tuple[int, int]:
        writer = PdfWriter()
        merged_file_count = 0
        merged_page_count = 0
        for pdf_path in input_paths:
            reader = PdfReader(str(pdf_path))
            pages = list(reader.pages)
            if not pages:
                continue
            for page in pages:
                writer.add_page(page)
            merged_file_count += 1
            merged_page_count += len(pages)
        if merged_page_count <= 0:
            raise HTTPException(status_code=500, detail="No valid PDF pages were found for merge.")
        merged_path.parent.mkdir(parents=True, exist_ok=True)
        with merged_path.open("wb") as handle:
            writer.write(handle)
        return merged_file_count, merged_page_count

    def _open_receipts_folder_for_ym(ym: str, actor: dict[str, str]) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        root = core._artifact_root() / ym
        amazon_pdfs = root / "amazon" / "pdfs"
        rakuten_pdfs = root / "rakuten" / "pdfs"
        root.mkdir(parents=True, exist_ok=True)
        if amazon_pdfs.exists() and rakuten_pdfs.exists():
            target = root
        elif amazon_pdfs.exists():
            target = amazon_pdfs
        elif rakuten_pdfs.exists():
            target = rakuten_pdfs
        else:
            # Fallback: open the month root even if receipts are not generated yet.
            target = root

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
                event_type="source_action",
                action="open_receipts_folder",
                status="failed",
                actor=actor,
                details={"reason": detail, "path": str(target)},
            )
            raise HTTPException(status_code=500, detail=detail)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="source_action",
            action="open_receipts_folder",
            status="success",
            actor=actor,
            details={"path": str(target)},
        )
        return JSONResponse({"status": "ok", "path": str(target)})

    @router.get("/api/steps/{ym}")
    def api_steps(ym: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        state = core._workflow_state_for_ym(year, month)
        return JSONResponse(state, headers={"Cache-Control": "no-store"})

    @router.post("/api/steps/{ym}/reset/{step_id}")
    def api_step_reset(ym: str, step_id: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        result = core._reset_step_state(year, month, str(step_id).strip(), actor=actor)
        return JSONResponse({"status": "ok", **result})

    @router.get("/api/exclusions/{ym}")
    def api_get_exclusions(ym: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym / "reports"
        data = core._read_json(root / "exclude_orders.json")
        if not isinstance(data, dict):
            data = {"ym": ym, "exclude": []}
        return JSONResponse(data)

    @router.post("/api/exclusions/{ym}")
    def api_set_exclusions(ym: str, payload: dict[str, Any], request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        exclude = payload.get("exclude")
        if not isinstance(exclude, list):
            raise HTTPException(status_code=400, detail="exclude must be a list.")
        source = str(payload.get("source") or "").strip()
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=400, detail="source must be amazon or rakuten.")
        try:
            core._assert_source_action_allowed(year, month, source, "confirm")
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="confirm",
                status="rejected",
                actor=actor,
                source=source,
                details={"reason": str(exc.detail)},
            )
            raise

        cleaned: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in exclude:
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source") or "").strip()
            order_id = str(item.get("order_id") or "").strip()
            if item_source not in {"amazon", "rakuten"}:
                continue
            if not order_id or not core.ORDER_ID_RE.match(order_id):
                continue
            key = (item_source, order_id)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append({"source": item_source, "order_id": order_id})

        reports_dir = core._artifact_root() / ym / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        data = {"ym": ym, "exclude": cleaned, "updated_at": datetime.now().isoformat(timespec="seconds")}
        core._write_json(reports_dir / "exclude_orders.json", data)
        wf = core._read_workflow(reports_dir)
        section = wf.get(source) if isinstance(wf.get(source), dict) else {}
        section["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
        section.pop("printed_at", None)
        section.pop("print_prepared_at", None)
        wf[source] = section
        core._write_workflow(reports_dir, wf)
        core._append_audit_event(
            year=year,
            month=month,
            event_type="source_action",
            action="confirm",
            status="success",
            actor=actor,
            source=source,
            details={"exclude_count": len(cleaned)},
        )

        return JSONResponse({"status": "ok", "count": len(cleaned)})

    @router.post("/api/print/{ym}/{source}")
    def api_print(ym: str, source: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=400, detail="Invalid source.")

        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        try:
            core._assert_source_action_allowed(year, month, source, "print")
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_prepare",
                status="rejected",
                actor=actor,
                source=source,
                details={"reason": str(exc.detail)},
            )
            raise
        output_root = core._artifact_root() / ym
        scripts_dir = core.SKILL_ROOT / "scripts"
        reports_dir = output_root / "reports"
        exclude_orders_json = output_root / "reports" / "exclude_orders.json"
        print_script = reports_dir / "print_all.ps1"
        source_manifest_path = _source_manifest_path(reports_dir, source)
        source_list_path = _source_list_path(reports_dir, source)
        print_count: int | None = None

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
            "--skip-shortcut-download",
        ]
        if exclude_orders_json.exists():
            cmd += ["--exclude-orders-json", str(exclude_orders_json)]

        try:
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

            manifest = core._read_json(source_manifest_path)
            if isinstance(manifest, dict):
                try:
                    print_count = int(manifest.get("count"))
                except Exception:
                    print_count = None

            if not source_manifest_path.exists():
                raise HTTPException(status_code=404, detail=f"{source_manifest_path.name} not found.")
            print_command = f"POST /api/print-run/{ym}/{source}"
            wf = core._read_workflow(reports_dir)
            section = wf.get(source) if isinstance(wf.get(source), dict) else {}
            section["print_prepared_at"] = datetime.now().isoformat(timespec="seconds")
            # Prepare is intentionally "before print": completion must be recorded manually.
            section.pop("printed_at", None)
            wf[source] = section
            core._write_workflow(reports_dir, wf)
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_prepare",
                status="success",
                actor=actor,
                source=source,
                details={
                    "print_script": str(print_script),
                    "print_manifest": str(source_manifest_path),
                    "print_list": str(source_list_path),
                    "count": print_count,
                },
            )

            return JSONResponse(
                {
                    "status": "ok",
                    "source": source,
                    "count": print_count,
                    "print_script": str(print_script),
                    "print_manifest": str(source_manifest_path),
                    "print_list": str(source_list_path),
                    "print_command": print_command,
                    "excluded_pdfs_url": f"/runs/{ym}/excluded-pdfs",
                }
            )
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_prepare",
                status="failed",
                actor=actor,
                source=source,
                details={
                    "reason": str(exc.detail),
                    "print_script": str(print_script),
                    "print_manifest": str(source_manifest_path),
                    "print_list": str(source_list_path),
                    "count": print_count,
                },
            )
            raise

    @router.post("/api/print/{ym}/{source}/complete")
    def api_print_complete(ym: str, source: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=400, detail="Invalid source.")

        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        output_root = core._artifact_root() / ym
        reports_dir = output_root / "reports"
        source_manifest_path = _source_manifest_path(reports_dir, source)
        print_count: int | None = None

        try:
            core._assert_source_action_allowed(year, month, source, "print")
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_complete",
                status="rejected",
                actor=actor,
                source=source,
                details={"reason": str(exc.detail)},
            )
            raise

        try:
            wf = core._read_workflow(reports_dir)
            section = wf.get(source) if isinstance(wf.get(source), dict) else {}
            if not section.get("print_prepared_at"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Print preparation is required before marking {source} print completion.",
                )
            if not source_manifest_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail="Print preparation not found. Run print preparation first.",
                )

            manifest = core._read_json(source_manifest_path)
            if isinstance(manifest, dict):
                try:
                    print_count = int(manifest.get("count"))
                except Exception:
                    print_count = None

            section["printed_at"] = datetime.now().isoformat(timespec="seconds")
            wf[source] = section
            core._write_workflow(reports_dir, wf)
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_complete",
                status="success",
                actor=actor,
                source=source,
                details={"count": print_count},
            )

            return JSONResponse({"status": "ok", "source": source, "count": print_count})
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_complete",
                status="rejected" if exc.status_code in {400, 404, 409} else "failed",
                actor=actor,
                source=source,
                details={"reason": str(exc.detail), "count": print_count},
            )
            raise

    def _execute_source_print_run(ym: str, source: str, actor: dict[str, str]) -> JSONResponse:
        ym = core._safe_ym(ym)
        source = _safe_print_source(source)
        year, month = core._split_ym(ym)
        reports_dir = core._artifact_root() / ym / "reports"
        workflow = core._read_workflow(reports_dir)
        section = workflow.get(source) if isinstance(workflow.get(source), dict) else {}
        if not section.get("print_prepared_at"):
            detail = f"Print preparation is required before {source} bulk print run."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_run",
                status="rejected",
                actor=actor,
                source=source,
                details={"reason": detail},
            )
            raise HTTPException(status_code=409, detail=detail)

        manifest_path = _source_manifest_path(reports_dir, source)
        manifest = core._read_json(manifest_path)
        if not manifest_path.exists() or not isinstance(manifest, dict):
            detail = f"{manifest_path.name} not found. Run print preparation first."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_run",
                status="rejected",
                actor=actor,
                source=source,
                details={"reason": detail},
            )
            raise HTTPException(status_code=404, detail=detail)

        raw_paths = _extract_print_file_paths(manifest)
        if not raw_paths:
            detail = f"No print targets were found in {manifest_path.name}."
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_run",
                status="rejected",
                actor=actor,
                source=source,
                details={"reason": detail},
            )
            raise HTTPException(status_code=409, detail=detail)

        existing_paths: list[Path] = []
        missing_files: list[str] = []
        for raw_path in raw_paths:
            candidate = Path(raw_path)
            if candidate.exists() and candidate.is_file():
                existing_paths.append(candidate)
            else:
                missing_files.append(str(candidate))
        if not existing_paths:
            detail = (
                f"All target PDFs are missing for {source}. "
                f"manifest={manifest_path.name} missing_count={len(missing_files)}"
            )
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_run",
                status="failed",
                actor=actor,
                source=source,
                details={"reason": detail, "missing_count": len(missing_files)},
            )
            raise HTTPException(status_code=500, detail=detail)

        merged_pdf_path = reports_dir / f"print_merged_{source}.pdf"
        try:
            merged_count, merged_pages = _merge_pdfs(existing_paths, merged_pdf_path)
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_run",
                status="failed",
                actor=actor,
                source=source,
                details={"reason": str(exc.detail), "missing_count": len(missing_files)},
            )
            raise
        except Exception as exc:
            detail = f"Merged PDF generation failed: {exc}"
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="print_run",
                status="failed",
                actor=actor,
                source=source,
                details={"reason": detail, "missing_count": len(missing_files)},
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
                event_type="source_action",
                action="print_run",
                status="failed",
                actor=actor,
                source=source,
                details={"reason": detail, "missing_count": len(missing_files)},
            )
            raise HTTPException(status_code=500, detail=detail)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="source_action",
            action="print_run",
            status="success",
            actor=actor,
            source=source,
            details={
                "mode": "manual_open",
                "count": merged_count,
                "merged_pages": merged_pages,
                "missing_count": len(missing_files),
                "missing_files": missing_files,
                "merged_pdf_path": str(merged_pdf_path),
            },
        )
        return JSONResponse(
            {
                "status": "ok",
                "ym": ym,
                "source": source,
                "print_mode": "manual_open",
                "count": merged_count,
                "missing_count": len(missing_files),
                "merged_pdf_path": str(merged_pdf_path),
            }
        )

    @router.post("/api/print-run/{ym}/{source}")
    def api_print_run_by_source(ym: str, source: str, request: Request) -> JSONResponse:
        actor = _actor_from_request(request)
        return _execute_source_print_run(ym, source, actor)

    @router.post("/api/print-run/{ym}")
    def api_print_run_legacy(ym: str, request: Request, source: str | None = None) -> JSONResponse:
        actor = _actor_from_request(request)
        if source:
            return _execute_source_print_run(ym, source, actor)
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        detail = "Deprecated endpoint. Use /api/print-run/{ym}/{source}."
        core._append_audit_event(
            year=year,
            month=month,
            event_type="source_action",
            action="print_run",
            status="rejected",
            actor=actor,
            details={"reason": detail},
        )
        raise HTTPException(status_code=400, detail=detail)

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

    @router.post("/api/manual/{ym}/import")
    def api_manual_import(ym: str, request: Request) -> JSONResponse:
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
            result = core._import_manual_receipts_for_ym(year, month)
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

        core._append_audit_event(
            year=year,
            month=month,
            event_type="provider_ingest",
            action="import",
            status="success",
            actor=actor,
            details={
                "found_files": result.get("found_files"),
                "imported": result.get("imported"),
                "skipped_duplicates": result.get("skipped_duplicates"),
                "failed": result.get("failed"),
                "providers": result.get("providers"),
                "orders_jsonl": result.get("orders_jsonl"),
                "provider_report_json": result.get("provider_report_json"),
            },
        )
        return JSONResponse(result)

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

    def _run_archive_action(
        *,
        ym: str,
        request: Request,
        action: str,
        cleanup: bool,
    ) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        include_pdfs = True
        include_debug = False
        try:
            if action == "month_close":
                checklist_payload = core._read_month_close_checklist_for_ym(ym)
                checklist = checklist_payload.get("checklist")
                missing_items = core._incomplete_month_close_checklist_keys(checklist)
                if missing_items:
                    joined = ", ".join(missing_items)
                    raise HTTPException(
                        status_code=409,
                        detail=f"Month close checklist is incomplete: {joined}",
                    )
            core._assert_archive_allowed(year, month)
            result = core._archive_outputs_for_ym(
                year,
                month,
                include_pdfs=include_pdfs,
                include_debug=include_debug,
                cleanup=cleanup,
            )
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="archive",
                action=action,
                status="rejected" if exc.status_code in {400, 404, 409} else "failed",
                actor=actor,
                details={
                    "reason": str(exc.detail),
                    "include_pdfs": include_pdfs,
                    "include_debug": include_debug,
                    "cleanup": cleanup,
                },
            )
            raise
        core._append_audit_event(
            year=year,
            month=month,
            event_type="archive",
            action=action,
            status="success",
            actor=actor,
            details={
                "archived_to": result.get("archived_to"),
                "include_pdfs": include_pdfs,
                "include_debug": include_debug,
                "cleanup": cleanup,
                "cleanup_report": result.get("cleanup_report"),
                "cleanup_removed": result.get("cleanup_removed"),
            },
        )
        response = dict(result)
        response["history_entry"] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "ym": ym,
            "action": action,
            "action_label": "月次クローズ" if action == "month_close" else "アーカイブ",
            "archived_to": result.get("archived_to"),
            "archive_url": f"/runs/{ym}/archived-receipts",
        }
        return JSONResponse(response)

    @router.post("/api/archive/{ym}")
    def api_archive(ym: str, request: Request) -> JSONResponse:
        return _run_archive_action(
            ym=ym,
            request=request,
            action="manual_archive",
            cleanup=False,
        )

    @router.post("/api/month-close/{ym}")
    def api_month_close(ym: str, request: Request) -> JSONResponse:
        return _run_archive_action(
            ym=ym,
            request=request,
            action="month_close",
            cleanup=True,
        )

    @router.get("/api/month-close-checklist/{ym}")
    def api_get_month_close_checklist(ym: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        data = core._read_month_close_checklist_for_ym(ym)
        return JSONResponse(data)

    @router.post("/api/month-close-checklist/{ym}")
    def api_set_month_close_checklist(ym: str, payload: dict[str, Any], request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        checklist = core._validate_month_close_checklist_payload(payload.get("checklist"))
        checklist_path = core._month_close_checklist_path_for_ym(ym)

        data = {
            "ym": ym,
            "checklist": checklist,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        core._write_json(checklist_path, data)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="month_close_checklist",
            action="update",
            status="success",
            actor=actor,
            details={"checklist": checklist},
        )

        return JSONResponse({"status": "ok", "checklist": checklist})

    @router.get("/api/workspace/state")
    def api_get_workspace_state() -> JSONResponse:
        state = _read_workspace_state()
        return JSONResponse({"status": "ok", **state}, headers={"Cache-Control": "no-store"})

    @router.post("/api/workspace/state")
    def api_set_workspace_state(payload: dict[str, Any]) -> JSONResponse:
        payload = payload if isinstance(payload, dict) else {}
        current = _read_workspace_state()
        current_revision = core._safe_non_negative_int(current.get("revision"), default=0)
        base_revision_raw = payload.get("base_revision")
        has_base_revision = base_revision_raw is not None
        base_revision = core._safe_non_negative_int(base_revision_raw, default=-1)
        revision_conflict = bool(has_base_revision and base_revision != current_revision)

        if "links" in payload:
            links_payload = _sanitize_workspace_links(payload.get("links"))
            if revision_conflict:
                current["links"] = _merge_workspace_links(links_payload, _sanitize_workspace_links(current.get("links")))
            else:
                current["links"] = links_payload
        if "prompts" in payload:
            prompts_payload = _sanitize_workspace_prompts(payload.get("prompts"))
            if revision_conflict:
                current["prompts"] = _merge_workspace_prompts(
                    prompts_payload,
                    _sanitize_workspace_prompts(current.get("prompts")),
                )
            else:
                current["prompts"] = prompts_payload
        if "link_notes" in payload:
            notes_payload = _sanitize_workspace_link_notes(payload.get("link_notes"))
            if revision_conflict:
                current["link_notes"] = _merge_workspace_link_notes(
                    notes_payload,
                    _sanitize_workspace_link_notes(current.get("link_notes")),
                )
            else:
                current["link_notes"] = notes_payload
        if "active_prompt_key" in payload:
            current["active_prompt_key"] = _sanitize_workspace_active_prompt_key(payload.get("active_prompt_key"))
        saved = _write_workspace_state(current, revision=current_revision + 1)
        return JSONResponse(
            {"status": "ok", **saved, "conflict_resolved": revision_conflict},
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/print-pdf/{ym}/{source}/{filename}")
    def api_print_pdf(ym: str, source: str, filename: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=404, detail="PDF not found.")
        if not filename or not core.SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=404, detail="PDF not found.")
        root = core._artifact_root() / ym
        path = core._resolve_pdf_path(root, source, filename)
        if not path:
            raise HTTPException(status_code=404, detail="PDF not found.")
        pdf_url = f"/files/{ym}/pdf/{source}/{path.name}"
        year, month = core._split_ym(ym)
        core._append_audit_event(
            year=year,
            month=month,
            event_type="source_action",
            action="print_single_pdf",
            status="success",
            actor=_actor_from_request(request),
            source=source,
            details={"file": str(path.name), "mode": "manual_open"},
        )
        return JSONResponse(
            {
                "status": "ok",
                "file": str(path.name),
                "pdf_url": pdf_url,
                "print_mode": "manual_open",
            }
        )

    @router.post("/api/runs")
    def api_run(payload: dict[str, Any], request: Request) -> JSONResponse:
        actor = _actor_from_request(request)
        req_payload = dict(payload)
        req_payload["_audit_actor"] = actor
        mode = str(req_payload.get("mode") or "unknown")
        try:
            result = core._start_run(req_payload)
        except HTTPException as exc:
            ym = _try_year_month(req_payload)
            detail = str(exc.detail)
            if ym and ("Invalid year/month" in detail or "Month must be between" in detail):
                year, month = ym
                core._append_audit_event(
                    year=year,
                    month=month,
                    event_type="run",
                    action=mode,
                    status="rejected",
                    actor=actor,
                    mode=mode,
                    details={"reason": detail},
                )
            raise
        return JSONResponse(result)

    @router.post("/api/runs/{run_id}/stop")
    def api_run_stop(run_id: str, request: Request) -> JSONResponse:
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
        params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
        try:
            year = int(params.get("year"))
            month = int(params.get("month"))
        except Exception:
            year = None
            month = None
        if year is not None and month is not None:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="run",
                action="stop",
                status="success",
                actor=_actor_from_request(request),
                mode=str(params.get("mode") or ""),
                run_id=run_id,
                details={"returncode": -1},
            )
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
        return JSONResponse({"run": meta, "log_tail": log_text}, headers={"Cache-Control": "no-store"})

    @router.get("/api/mf-draft-actions/{ym}")
    def api_get_mf_draft_actions(ym: str, limit_events: int = 0) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        payload = core._mf_draft_actions_summary_for_ym(year, month, limit_events=limit_events)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    return router
