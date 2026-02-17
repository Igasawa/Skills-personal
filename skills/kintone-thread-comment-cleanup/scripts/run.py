#!/usr/bin/env python3
"""
Delete kintone space thread comments via UI automation (Playwright).

Standard JSON interface:
Input (stdin or --input):
{
  "config": {
    "kintone": {
      "subdomain": "5atx9",
      "space_id": 81,
      "thread_id": 131,
      "allow_production": false
    },
    "auth": {
      "username": "...",  # optional (prefer env KINTONE_USERNAME)
      "password": "...",  # optional (prefer env KINTONE_PASSWORD)
      "storage_state_path": null
    },
    "dry_run": true,
    "headed": false
  },
  "params": {
    "comment_ids": ["4789"],
    "match_texts": ["[AX preflight]"],
    "max_delete": 10
  }
}
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import traceback
from typing import Any


_COMMENT_ID_RE = re.compile(r"\bocean-ui-comments-post-id-(\d+)\b")


def _read_json_input(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    if sys.stdin and not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    return {}


def _coalesce(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip()
    return cleaned or None


def _as_int(value: Any, *, name: str) -> int:
    if value is None:
        raise ValueError(f"Missing required integer: {name}")
    try:
        return int(value)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid integer for {name}: {value!r}") from e


def _as_bool(value: Any, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off", ""):
            return False
    raise ValueError(f"Invalid boolean for {name}: {value!r}")


def _ensure_utf8_stdout() -> None:
    # Avoid UnicodeEncodeError on Windows console (cp932) for uncommon chars.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


@dataclass(frozen=True)
class KintoneThread:
    subdomain: str
    space_id: int
    thread_id: int

    @property
    def url(self) -> str:
        return f"https://{self.subdomain}.cybozu.com/k/#/space/{self.space_id}/thread/{self.thread_id}"


@dataclass(frozen=True)
class AuthConfig:
    username: str | None
    password: str | None
    storage_state_path: str | None


def _parse_thread(config: dict[str, Any], args: argparse.Namespace) -> KintoneThread:
    k = (config.get("kintone") or {}) if isinstance(config, dict) else {}
    subdomain = _blank_to_none(_coalesce(args.subdomain, k.get("subdomain"), "5atx9"))
    if subdomain is None:
        raise ValueError("Invalid kintone subdomain")
    space_id = _as_int(_coalesce(args.space_id, k.get("space_id")), name="space_id")
    thread_id = _as_int(_coalesce(args.thread_id, k.get("thread_id")), name="thread_id")
    return KintoneThread(subdomain=subdomain, space_id=space_id, thread_id=thread_id)


def _parse_auth(config: dict[str, Any], args: argparse.Namespace) -> AuthConfig:
    a = (config.get("auth") or {}) if isinstance(config, dict) else {}
    username = _blank_to_none(_coalesce(args.username, a.get("username"), os.environ.get("KINTONE_USERNAME")))
    password = _blank_to_none(_coalesce(args.password, a.get("password"), os.environ.get("KINTONE_PASSWORD")))
    storage_state_path = _blank_to_none(_coalesce(args.storage_state, a.get("storage_state_path")))
    return AuthConfig(username=username, password=password, storage_state_path=storage_state_path)


def _is_sandbox_thread(t: KintoneThread) -> bool:
    return t.subdomain == "5atx9" and t.space_id == 81 and t.thread_id == 131


def _extract_comment_id(class_name: str) -> str | None:
    m = _COMMENT_ID_RE.search(class_name or "")
    return m.group(1) if m else None


def _load_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "playwright が未導入です。以下を実行してください:\n"
            "  python -m pip install --user playwright\n"
            "  python -m playwright install chromium"
        ) from e


def _login_if_needed(page: Any, auth: AuthConfig) -> None:
    # If we already have a valid session (storage_state), /login won't appear.
    if "/login" not in page.url:
        return

    if not auth.username or not auth.password:
        raise ValueError(
            "ログインが必要ですが認証情報がありません。"
            "KINTONE_USERNAME/KINTONE_PASSWORD を設定するか、storage_state を用意してください。"
        )

    page.wait_for_selector('input[name="username"]', timeout=60_000)
    page.fill('input[name="username"]', auth.username)
    page.fill('input[name="password"]', auth.password)
    page.click('input[type="submit"].login-button')


def _collect_comments(page: Any) -> list[dict[str, Any]]:
    rows = page.eval_on_selector_all(
        ".ocean-ui-comments-commentbase",
        """els => els.map(el => {
          const cls = el.getAttribute('class') || '';
          return { className: cls, text: (el.innerText || '').trim() };
        })""",
    )
    out: list[dict[str, Any]] = []
    for r in rows or []:
        cls = r.get("className") if isinstance(r, dict) else ""
        txt = r.get("text") if isinstance(r, dict) else ""
        cid = _extract_comment_id(str(cls or ""))
        out.append(
            {
                "comment_id": cid,
                "class_name": str(cls or ""),
                "text": str(txt or ""),
            }
        )
    return out


def _select_targets(
    *,
    comments: list[dict[str, Any]],
    comment_ids: list[str],
    match_texts: list[str],
    max_delete: int,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for c in comments:
        cid = c.get("comment_id")
        if isinstance(cid, str) and cid:
            by_id[cid] = c

    selected: list[dict[str, Any]] = []

    # Explicit IDs first (stable).
    for cid in comment_ids:
        if cid in by_id:
            selected.append(by_id[cid])
        else:
            selected.append({"comment_id": cid, "missing": True})

    # Then match_texts (may select multiple comments).
    if match_texts:
        for c in comments:
            text = c.get("text") or ""
            if not isinstance(text, str):
                continue
            if any(mt in text for mt in match_texts):
                if c not in selected:
                    selected.append(c)

    # De-dup by comment_id where possible.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for c in selected:
        cid = c.get("comment_id")
        if not isinstance(cid, str) or not cid:
            deduped.append(c)
            continue
        if cid in seen:
            continue
        seen.add(cid)
        deduped.append(c)

    if max_delete < 0:
        raise ValueError("max_delete must be >= 0")
    return deduped[:max_delete]


def _confirm_delete(page: Any) -> str:
    selectors = [
        'a.removelink-confirm-btn-cybozu:has-text("削除する")',
        'button:has-text("削除する")',
        'a:has-text("削除する")',
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=15_000)
            loc.click()
            return sel
        except Exception:
            continue
    raise RuntimeError("削除確認UI（削除する）が見つかりませんでした")


def _delete_comment_by_id(page: Any, comment_id: str) -> dict[str, Any]:
    selector = f".ocean-ui-comments-post-id-{comment_id}"
    item = page.locator(selector).first
    if item.count() == 0:
        return {"comment_id": comment_id, "deleted": False, "reason": "not_found"}

    item.scroll_into_view_if_needed(timeout=30_000)
    item.locator("a.ocean-ui-comments-commentbase-delete").first.click()
    confirm_sel = _confirm_delete(page)

    # Wait until element is removed.
    try:
        item.wait_for(state="detached", timeout=60_000)
    except Exception:
        # Some UI updates keep the element but hide it; re-check existence.
        if page.locator(selector).count() > 0:
            raise

    return {"comment_id": comment_id, "deleted": True, "confirm_selector": confirm_sel}


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()

    ap = argparse.ArgumentParser(description="kintone thread comment cleanup")
    ap.add_argument("--input", help="path to input JSON (otherwise stdin)")

    ap.add_argument("--subdomain", help="kintone subdomain (default: 5atx9)")
    ap.add_argument("--space-id", dest="space_id", type=int, help="kintone space id")
    ap.add_argument("--thread-id", dest="thread_id", type=int, help="kintone thread id")

    ap.add_argument("--comment-id", action="append", default=[], help="comment id to delete (repeatable)")
    ap.add_argument("--match-text", action="append", default=[], help="delete comments containing text (repeatable)")
    ap.add_argument("--max-delete", type=int, default=10, help="limit number of deletions/listings (default: 10)")

    ap.add_argument("--username", help="kintone username (avoid; prefer env/secrets)")
    ap.add_argument("--password", help="kintone password (avoid; prefer env/secrets)")
    ap.add_argument("--storage-state", dest="storage_state", help="Playwright storage_state json path (optional)")

    ap.add_argument("--dry-run", action="store_true", default=None, help="list targets only (default)")
    ap.add_argument("--apply", action="store_true", help="actually delete")
    ap.add_argument("--allow-production", action="store_true", help="allow deletion outside sandbox thread")
    ap.add_argument("--headed", action="store_true", default=None, help="run browser headed (for debugging)")

    args = ap.parse_args(argv)

    raw = _read_json_input(args.input)
    config = raw.get("config") if isinstance(raw, dict) else None
    params = raw.get("params") if isinstance(raw, dict) else None
    config = config if isinstance(config, dict) else {}
    params = params if isinstance(params, dict) else {}

    thread = _parse_thread(config, args)
    auth = _parse_auth(config, args)

    cfg_dry_run = bool(config.get("dry_run", True))
    if args.dry_run is None:
        dry_run = cfg_dry_run
    else:
        dry_run = bool(args.dry_run)
    if args.apply:
        dry_run = False

    cfg_headed = bool(config.get("headed", False))
    if args.headed is None:
        headed = cfg_headed
    else:
        headed = bool(args.headed)

    comment_ids = [
        str(x).strip()
        for x in (_coalesce(args.comment_id, params.get("comment_ids")) or [])
        if str(x).strip()
    ]
    match_texts = [
        str(x)
        for x in (_coalesce(args.match_text, params.get("match_texts")) or [])
        if str(x).strip()
    ]
    max_delete = _as_int(_coalesce(args.max_delete, params.get("max_delete"), 10), name="max_delete")

    if not comment_ids and not match_texts:
        raise ValueError("Either comment_ids or match_texts must be provided")

    allow_production_cfg = bool((config.get("kintone") or {}).get("allow_production", False))
    allow_production = bool(_coalesce(args.allow_production, allow_production_cfg))
    if not _is_sandbox_thread(thread) and not allow_production:
        raise ValueError(
            "本番スレッドの削除は拒否されました。"
            "sandbox で確認後、--allow-production を付けて実行してください。"
        )

    out_dir = Path("output") / "playwright"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    sync_playwright = _load_playwright()

    deleted: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    screenshots: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx_kwargs: dict[str, Any] = {}
        if auth.storage_state_path:
            ctx_kwargs["storage_state"] = auth.storage_state_path
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())

        page.goto(thread.url, wait_until="domcontentloaded", timeout=60_000)
        _login_if_needed(page, auth)
        page.wait_for_timeout(8_000)
        page.goto(thread.url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(10_000)

        before = out_dir / f"before_{thread.space_id}_{thread.thread_id}_{stamp}.png"
        page.screenshot(path=str(before), full_page=True)
        screenshots["before"] = str(before)

        comments = _collect_comments(page)
        selected = _select_targets(
            comments=comments, comment_ids=comment_ids, match_texts=match_texts, max_delete=max_delete
        )

        if not dry_run:
            for t in selected:
                cid = t.get("comment_id")
                if not isinstance(cid, str) or not cid:
                    deleted.append({"deleted": False, "reason": "missing_comment_id", "target": t})
                    continue
                if t.get("missing") is True:
                    deleted.append({"comment_id": cid, "deleted": False, "reason": "not_found"})
                    continue
                deleted.append(_delete_comment_by_id(page, cid))

        after = out_dir / f"after_{thread.space_id}_{thread.thread_id}_{stamp}.png"
        page.screenshot(path=str(after), full_page=True)
        screenshots["after"] = str(after)

        context.close()
        browser.close()

    out = {
        "status": "success",
        "data": {
            "dry_run": dry_run,
            "kintone": {"subdomain": thread.subdomain, "space_id": thread.space_id, "thread_id": thread.thread_id},
            "selected": [
                {
                    "comment_id": c.get("comment_id"),
                    "missing": bool(c.get("missing", False)),
                    "text_head": (c.get("text") or "")[:120],
                }
                for c in selected
            ],
            "deleted": deleted,
            "screenshots": screenshots,
        },
    }

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001
        debug = os.environ.get("AX_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
        err: dict[str, Any] = {"status": "error", "error": {"type": type(e).__name__, "message": str(e)}}
        if debug:
            err["error"]["traceback"] = traceback.format_exc()
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stdout)
        raise SystemExit(1)
