#!/usr/bin/env python3
"""
Playwright runner for repeatable Lolipop UI tasks.

Expected input format (stdin or --input):
{
  "config": {
    "lolipop": {
      "base_url": "https://secure.lolipop.jp",
      "session_name": "lolipop",
      "environment": "production"
    },
    "auth": {
      "username": "...",
      "password": "...",
      "storage_state_path": null
    },
    "dry_run": true,
    "allow_production": false
  },
  "params": {
    "action": "run-playbook",
    "domain": "example.lolipop.jp",
    "playbook": {"name": "...", "steps": [...]},
    "playbook_path": "path/to/plan.json"
  }
}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ACTION_RUN_PLAYBOOK = "run-playbook"
ACTION_VALIDATE = "validate"
ALLOWED_ACTIONS = (ACTION_VALIDATE, ACTION_RUN_PLAYBOOK)


READ_ONLY_ACTIONS = {
    "goto",
    "assert_title_contains",
    "assert_url_contains",
    "assert_text",
    "wait_for_selector",
    "screenshot",
    "wait_ms",
}

MUTATING_ACTIONS = {
    "click",
    "double_click",
    "fill",
    "check",
    "uncheck",
    "select_option",
    "press",
}


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _default_session_state_path(name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(name).strip())
    if not safe:
        safe = "lolipop"
    return _ax_home() / "sessions" / f"{safe}.storage.json"


def _default_report_dir() -> Path:
    return _ax_home() / "reports" / "lolipop_admin_ops"


def _read_json_input(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            raise ValueError("Input JSON must be an object at top level")

    if sys.stdin and not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        raise ValueError("Input JSON must be an object at top level")

    return {}


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _sanitize_domain(value: Any) -> str:
    domain = _blank_to_none(value)
    if not domain:
        raise ValueError("domain is required")
    if "." not in domain:
        raise ValueError(f"invalid domain format: {domain}")
    return domain


def _safe_path(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)


def _normalize_url(base: str, path_or_url: str | None) -> str:
    if not path_or_url:
        return base
    u = str(path_or_url).strip()
    if not u:
        return base
    if re.match(r"^https?://", u, re.IGNORECASE):
        return u
    b = base.rstrip("/")
    if u.startswith("/"):
        return f"{b}{u}"
    return f"{b}/{u}"


def _is_production(environment: str | None) -> bool:
    return _blank_to_none(environment) in (None, "production", "prod", "main", "live")


def _read_playbook_from_path(playbook_path: str | None) -> Any:
    if not playbook_path:
        return None
    p = Path(playbook_path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Playbook not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def _load_playbook(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"name": "empty", "steps": []}
    if isinstance(raw, list):
        return {"name": "inline", "steps": raw}
    if not isinstance(raw, dict):
        raise ValueError("playbook must be an object or a step array")
    steps = raw.get("steps")
    if steps is None:
        raise ValueError("playbook.steps is required")
    if not isinstance(steps, list):
        raise ValueError("playbook.steps must be an array")
    normalized = dict(raw)
    normalized["steps"] = steps
    return normalized


def _normalize_step(step: Any, index: int) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise ValueError(f"step[{index}] is not an object")
    typ = _blank_to_none(step.get("type") or step.get("action"))
    if not typ:
        raise ValueError(f"step[{index}] missing type/action")
    if typ not in (READ_ONLY_ACTIONS | MUTATING_ACTIONS):
        raise ValueError(f"step[{index}] unsupported type: {typ}")
    return {
        "type": typ,
        "selector": _blank_to_none(step.get("selector")),
        "url": _blank_to_none(step.get("url")),
        "text": _blank_to_none(step.get("text")),
        "value": _blank_to_none(step.get("value")),
        "name": _blank_to_none(step.get("name")),
        "timeout": int(step.get("timeout")) if _blank_to_none(step.get("timeout")) else None,
        "state": _blank_to_none(step.get("state")) or "visible",
        "delay_ms": int(step.get("delay_ms")) if _blank_to_none(step.get("delay_ms")) else 300,
    }

def _load_playwright():
    try:
        from playwright.sync_api import TimeoutError as PWTimeoutError
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import Error as PWError
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "playwright is not installed. install and set up browser:\n"
            "  python -m pip install --user playwright\n"
            "  python -m playwright install chromium"
        ) from e
    return sync_playwright, PWTimeoutError, PWError


def _first_visible_selector(page: Any, selectors: list[str], timeout_ms: int) -> str | None:
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=timeout_ms, state="visible")
            return sel
        except Exception:
            continue
    return None


def _login_if_needed(page: Any, username: str | None, password: str | None, timeout_ms: int = 30000) -> None:
    username_selector_candidates = [
        "input[name='username']",
        "input[name='mail']",
        "input[name='email']",
        "input[type='email']",
        "#username",
        "#login_id",
        "#user_name",
    ]
    password_selector_candidates = [
        "input[type='password']",
        "input[name='password']",
        "#password",
        "#login_password",
        "#user_pass",
    ]
    submit_selector_candidates = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('ログイン')",
        "button:has-text('Login')",
        "input:has-text('Login')",
        "a:has-text('ログイン')",
    ]

    # If no login form is visible, assume already authenticated.
    username_selector = _first_visible_selector(page, username_selector_candidates, timeout_ms=3000)
    password_selector = _first_visible_selector(page, password_selector_candidates, timeout_ms=3000)
    if not (username_selector and password_selector):
        return

    if not username or not password:
        raise ValueError("login form is shown but credentials are missing")

    page.locator(username_selector).first.fill(username)
    page.locator(password_selector).first.fill(password)

    submit_selector = _first_visible_selector(page, submit_selector_candidates, timeout_ms=3000)
    if submit_selector is None:
        raise ValueError("login submit button was not found")

    page.locator(submit_selector).first.click(timeout=timeout_ms)
    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

def _run_step(
    page: Any,
    base_url: str,
    step: dict[str, Any],
    *,
    dry_run: bool,
    timeout_ms: int,
    index: int,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    t = step["type"]
    selector = step.get("selector")
    url = step.get("url")
    value = step.get("value")
    text = step.get("text")
    step_name = step.get("name") or t
    step_timeout = int(step.get("timeout") or 30000)

    result: dict[str, Any] = {
        "index": index,
        "type": t,
        "name": step_name,
        "status": "skipped" if dry_run and t in MUTATING_ACTIONS else "pending",
        "dry_run": dry_run,
    }

    if dry_run and t in MUTATING_ACTIONS:
        result["reason"] = "skipped_in_dry_run"
        return result

    if t == "goto":
        target = _normalize_url(base_url, url)
        page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(step.get("delay_ms", 300))
        result["status"] = "ok"
        result["url"] = target
        return result

    if t == "wait_ms":
        delay = int(value or 0)
        page.wait_for_timeout(delay)
        result["status"] = "ok"
        result["waited_ms"] = delay
        return result

    if not selector and t not in {"goto", "wait_ms", "assert_title_contains", "assert_url_contains", "assert_text", "screenshot"}:
        raise ValueError(f"step[{index}] requires selector: {t}")

    locator = page.locator(selector)
    loc_timeout = timeout_ms if timeout_ms else step_timeout

    if t == "wait_for_selector":
        locator.wait_for(state=step.get("state", "visible"), timeout=loc_timeout)
        result["status"] = "ok"
        return result

    if t == "assert_title_contains":
        page.wait_for_load_state("domcontentloaded", timeout=loc_timeout)
        if not (text and text.lower() in page.title().lower()):
            raise AssertionError(f"title does not contain expected text: {text}")
        result["status"] = "ok"
        return result

    if t == "assert_url_contains":
        page.wait_for_load_state("domcontentloaded", timeout=loc_timeout)
        if not (text and text.lower() in page.url.lower()):
            raise AssertionError(f"url does not contain expected text: {text}")
        result["status"] = "ok"
        result["url"] = page.url
        return result

    if t == "assert_text":
        if not text:
            raise ValueError(f"step[{index}] requires text for assert_text")
        locator = page.locator(f"text={text}")
        locator.first.wait_for(state="visible", timeout=loc_timeout)
        result["status"] = "ok"
        result["text"] = text
        return result

    if t == "click":
        locator.first.click(timeout=loc_timeout)
        page.wait_for_timeout(step.get("delay_ms", 150))
        result["status"] = "ok"
        return result

    if t == "double_click":
        locator.first.dblclick(timeout=loc_timeout)
        page.wait_for_timeout(step.get("delay_ms", 150))
        result["status"] = "ok"
        return result

    if t == "fill":
        locator.first.fill(str(value or ""), timeout=loc_timeout)
        result["status"] = "ok"
        return result

    if t == "check":
        locator.first.check(timeout=loc_timeout)
        result["status"] = "ok"
        return result

    if t == "uncheck":
        locator.first.uncheck(timeout=loc_timeout)
        result["status"] = "ok"
        return result

    if t == "select_option":
        locator.first.select_option(value=value)
        result["status"] = "ok"
        return result

    if t == "press":
        locator.first.press(value or "Enter")
        result["status"] = "ok"
        return result

    if t == "screenshot":
        # keep deterministic naming: screenshot_<index>_<name>.png
        safe = _safe_path(step_name)
        file_name = f"screenshot_{index:03d}_{safe}.png"
        target = (report_dir / file_name) if report_dir else Path(file_name)
        page.screenshot(path=str(target), full_page=True)
        result["status"] = "ok"
        result["screenshot"] = str(target)
        return result

    raise RuntimeError(f"unsupported step type: {t}")


def _build_output(
    *,
    status: str,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "data": data or {},
        "error": error,
    }


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    ap = argparse.ArgumentParser(description="Lolipop admin operations")
    ap.add_argument("--input", help="input JSON file path (optional)")

    ap.add_argument("--action", choices=ALLOWED_ACTIONS, help="validate or run-playbook")
    ap.add_argument("--domain", help="target domain (required)")
    ap.add_argument("--base-url", dest="base_url", help="administrator base URL")
    ap.add_argument("--environment", help="production|staging (default: production)")
    ap.add_argument("--playbook", "--plan-file", dest="playbook", help="path to JSON playbook file")
    ap.add_argument(
        "--plan-json",
        help="JSON literal playbook (alternative to --playbook when called from orchestrator)",
    )

    ap.add_argument("--session-name", default=None, help="storage_state session name")
    ap.add_argument("--storage-state", default=None, help="path to session storage file")
    ap.add_argument("--username", help="optional username if storage_state is not available")
    ap.add_argument("--password", help="optional password if storage_state is not available")
    ap.add_argument("--headed", action="store_true", default=None, help="run browser in headed mode")
    ap.add_argument("--timeout", type=int, default=60000, help="default action timeout in ms")
    ap.add_argument("--allow-production", action="store_true", default=None, help="allow production modification")
    ap.add_argument("--report-dir", default=None, help="report directory (default: %AX_HOME%/reports/lolipop_admin_ops)")
    ap.add_argument("--dry-run", action="store_true", default=None, help="list plan + validate checks only")
    ap.add_argument("--apply", action="store_true", help="execute mutations (overrides dry-run)")

    args = ap.parse_args(argv)

    raw_input = _read_json_input(args.input)
    config = raw_input.get("config", {}) if isinstance(raw_input, dict) else {}
    params = raw_input.get("params", {}) if isinstance(raw_input, dict) else {}
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    if not isinstance(params, dict):
        raise ValueError("params must be an object")

    lolipop_cfg = config.get("lolipop", {}) if isinstance(config, dict) else {}
    if not isinstance(lolipop_cfg, dict):
        raise ValueError("config.lolipop must be an object")
    auth_cfg = config.get("auth", {}) if isinstance(config, dict) else {}
    if not isinstance(auth_cfg, dict):
        raise ValueError("config.auth must be an object")

    action = _coalesce(
        args.action,
        _blank_to_none(params.get("action")),
        _blank_to_none(lolipop_cfg.get("action")),
        ACTION_VALIDATE,
    )
    domain = _sanitize_domain(
        _coalesce(
            args.domain,
            _blank_to_none(params.get("domain")),
            _blank_to_none(lolipop_cfg.get("domain")),
        )
    )

    base_url = _blank_to_none(args.base_url) or _blank_to_none(params.get("base_url")) or _blank_to_none(lolipop_cfg.get("base_url")) or "https://secure.lolipop.jp"
    session_name = _blank_to_none(args.session_name) or _blank_to_none(lolipop_cfg.get("session_name")) or "lolipop"
    username = _blank_to_none(args.username) or _blank_to_none(params.get("username")) or _blank_to_none(auth_cfg.get("username")) or _blank_to_none(os.environ.get("LOLIPOP_USERNAME"))
    password = _blank_to_none(args.password) or _blank_to_none(params.get("password")) or _blank_to_none(auth_cfg.get("password")) or _blank_to_none(os.environ.get("LOLIPOP_PASSWORD"))
    environment = _blank_to_none(args.environment) or _blank_to_none(params.get("environment")) or _blank_to_none(lolipop_cfg.get("environment")) or "production"

    cfg_dry_run = bool(config.get("dry_run", True)) if isinstance(config.get("dry_run"), bool) else True
    if args.dry_run is None:
        dry_run = cfg_dry_run
    else:
        dry_run = bool(args.dry_run)
    if args.apply:
        dry_run = False

    cfg_allow = config.get("allow_production", False) if isinstance(config.get("allow_production"), bool) else False
    if args.allow_production is None:
        allow_production = bool(cfg_allow)
    else:
        allow_production = bool(args.allow_production)

    if action == ACTION_RUN_PLAYBOOK and not dry_run and _is_production(environment) and not allow_production:
        raise ValueError("Production target requires --allow-production")

    storage_state = _blank_to_none(
        _coalesce(
            args.storage_state,
            _blank_to_none(params.get("storage_state")),
            _blank_to_none(lolipop_cfg.get("storage_state_path")),
            _blank_to_none(auth_cfg.get("storage_state_path")),
        )
    )
    if not storage_state:
        storage_state = str(_default_session_state_path(session_name))
    storage_state_path = Path(storage_state)

    report_dir = Path(
        _blank_to_none(args.report_dir)
        or _blank_to_none(lolipop_cfg.get("report_dir"))
        or str(_default_report_dir())
    ).expanduser()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = report_dir / _safe_path(domain) / stamp
    report_dir.mkdir(parents=True, exist_ok=True)

    playbook_path = _coalesce(
        args.playbook,
        _blank_to_none(params.get("playbook_path")),
        _blank_to_none(lolipop_cfg.get("playbook_path")),
        _blank_to_none(config.get("playbook_path")),
    )
    raw_plan: Any = None
    if args.plan_json:
        raw_plan = _blank_to_none(args.plan_json)
    elif isinstance(params.get("playbook"), (dict, list, str)):
        raw_plan = params.get("playbook")

    if args.playbook or _coalesce(raw_plan, _blank_to_none(playbook_path)):
        raw_playbook: Any
        if args.playbook or _blank_to_none(playbook_path):
            raw_playbook = _read_playbook_from_path(_coalesce(args.playbook, playbook_path))
        else:
            if isinstance(raw_plan, str):
                try:
                    raw_playbook = json.loads(raw_plan)
                except json.JSONDecodeError as exc:
                    raise ValueError("plan-json is not valid JSON") from exc
            else:
                raw_playbook = raw_plan
        playbook = _load_playbook(raw_playbook)
    else:
        playbook = {"name": "no_playbook", "steps": []}

    if action == ACTION_RUN_PLAYBOOK and not playbook.get("steps"):
        raise ValueError("No steps found in playbook")

    if not storage_state_path.exists():
        if not (username and password):
            raise ValueError(
                f"storage_state not found: {storage_state_path}. "
                "Create it once with scripts/ax.ps1 playwright login --name lolipop --url ... and/or set credentials in AX_HOME/secrets/lolipop.env."
            )
        storage_state_path = None

    sync_playwright, pw_timeout_err, pw_error = _load_playwright()

    if _is_production(environment) and action == ACTION_RUN_PLAYBOOK and not dry_run and not allow_production:
        # safety check duplicated for explicitness
        raise ValueError("Production target blocked: pass --allow-production")

    before_path = str((report_dir / "before.png").resolve())
    after_path = str((report_dir / "after.png").resolve())

    steps_data: list[dict[str, Any]] = []
    run_result: dict[str, Any] = {
        "domain": domain,
        "environment": environment,
        "action": action,
        "dry_run": dry_run,
        "base_url": base_url,
        "report_dir": str(report_dir),
        "playbook": {"name": playbook.get("name"), "steps": len(playbook.get("steps", []))},
        "storage_state_used": str(storage_state_path) if storage_state_path else None,
        "screenshot": {},
    }

    with sync_playwright() as p:
        context_kwargs: dict[str, Any] = {}
        if storage_state_path:
            context_kwargs["storage_state"] = str(storage_state_path)
        browser = p.chromium.launch(headless=not bool(args.headed))
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        try:
            page.goto(_normalize_url(base_url, None), wait_until="domcontentloaded", timeout=int(args.timeout))
            if not storage_state_path and (username and password):
                _login_if_needed(page, username=username, password=password, timeout_ms=int(args.timeout))
            page.wait_for_timeout(1200)
            page.screenshot(path=before_path, full_page=True)

            run_result["screenshot"]["before"] = before_path

            if action == ACTION_VALIDATE:
                if playbook.get("steps"):
                    steps = [_normalize_step(s, i) for i, s in enumerate(playbook["steps"], 1)]
                    for i, step in enumerate(steps, 1):
                        steps_data.append(
                            _run_step(
                                page,
                                base_url,
                                step,
                                dry_run=True,
                                timeout_ms=int(args.timeout),
                                index=i,
                                report_dir=report_dir,
                            )
                        )
                else:
                    steps_data.append(
                        {"index": 1, "type": "validate", "status": "ok", "name": "session_load"}
                    )

            else:
                steps = [_normalize_step(s, i) for i, s in enumerate(playbook["steps"], 1)]
                for i, step in enumerate(steps, 1):
                    steps_data.append(
                        _run_step(
                            page,
                            base_url,
                            step,
                            dry_run=dry_run,
                            timeout_ms=int(args.timeout),
                            index=i,
                            report_dir=report_dir,
                        )
                    )
                if any(s["status"] == "failed" for s in steps_data):
                    raise RuntimeError("one or more steps failed")

            page.screenshot(path=after_path, full_page=True)
            run_result["screenshot"]["after"] = after_path

            if not dry_run and action == ACTION_RUN_PLAYBOOK:
                for s in steps_data:
                    if s.get("type") == "screenshot" and s.get("screenshot"):
                        shot = Path(s["screenshot"])
                        if shot.exists():
                            s["screenshot"] = str(shot)

            result = _build_output(
                status="success",
                data={
                    **run_result,
                    "steps": steps_data,
                },
            )
        except pw_timeout_err as e:
            raise RuntimeError(f"Playwright timeout: {e}") from e
        except pw_error as e:
            raise RuntimeError(f"Playwright error: {e}") from e
        finally:
            context.close()
            browser.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001
        err_payload = _build_output(
            status="error",
            error={"type": type(e).__name__, "message": str(e)},
        )
        if os.environ.get("AX_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
            err_payload["error"]["traceback"] = traceback.format_exc()
        print(json.dumps(err_payload, ensure_ascii=False, indent=2))
        raise SystemExit(1)
