from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "dashboard" / "templates"
STATIC_JS_DIR = ROOT / "dashboard" / "static" / "js"
STATIC_STYLES_DIR = ROOT / "dashboard" / "static" / "styles"
ROUTES_DIR = ROOT / "dashboard" / "routes"


REQUIRED_FILES = [
    TEMPLATES_DIR / "kil_review.html",
    STATIC_JS_DIR / "kil-review.js",
    STATIC_STYLES_DIR / "pages.css",
]


@dataclass
class CheckResult:
    ok: bool
    message: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ok(message: str) -> CheckResult:
    return CheckResult(ok=True, message=message)


def _ng(message: str) -> CheckResult:
    return CheckResult(ok=False, message=message)


def _contains(path: Path, needle: str) -> bool:
    return needle in _read_text(path)


def check_required_files() -> CheckResult:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    if missing:
        return _ng(f"必須ファイル不足: {', '.join(missing)}")
    return _ok("必須ファイル: OK")


def check_server_file_contract() -> CheckResult:
    checks: list[CheckResult] = []

    pages = ROUTES_DIR / "pages.py"
    api = ROUTES_DIR / "api.py"
    common = STATIC_JS_DIR / "common.js"
    template = TEMPLATES_DIR / "kil_review.html"
    scripts = STATIC_JS_DIR / "kil-review.js"

    for path in (pages, api, common, template, scripts):
        if not path.exists():
            return _ng(f"{path} is missing")

    checks.append(
        _ok("pages.py: /kil-review ルートあり")
        if _contains(pages, '"/kil-review"')
        else _ng("pages.py: /kil-review ルートがありません")
    )
    checks.append(
        _ok("api.py: /api/kil-review エンドポイントあり")
        if _contains(api, '"/api/kil-review"')
        else _ng("api.py: /api/kil-review エンドポイントがありません")
    )
    checks.append(
        _ok("common.js: ナビゲーションに KIL Review がある")
        if _contains(common, '"/kil-review"') and _contains(common, 'tab: "kil-review"')
        else _ng("common.js: ナビゲーションに /kil-review 定義がありません")
    )
    checks.append(
        _ok("common.js: /kil-review の active 判定あり")
        if _contains(common, '"/kil-review"') and _contains(common, 'if (normalized === "/kil-review")')
        else _ng("common.js: /kil-review の active 判定がありません")
    )
    checks.append(
        _ok("kil_review.html: 必要IDを確認")
        if all(_contains(template, needle) for needle in ("kil-review-source", "kil-review-limit", "kil-review-refresh"))
        else _ng("kil_review.html: 必要IDが不足しています")
    )
    checks.append(
        _ok("kil-review.js: API呼び出しあり")
        if _contains(scripts, '"/api/kil-review"')
        else _ng("kil-review.js: API呼び出しがありません")
    )

    ok = all(item.ok for item in checks)
    messages = [item.message for item in checks]
    return CheckResult(
        ok=ok,
        message="; ".join(messages),
    )


def _fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        payload_bytes = response.read()
        payload_text = payload_bytes.decode("utf-8")
        return json.loads(payload_text)


def check_kil_review_page(base_url: str) -> CheckResult:
    url = base_url.rstrip("/")
    request_url = f"{url}/kil-review"
    try:
        html = _fetch_text(request_url)
    except urllib.error.HTTPError as exc:
        return _ng(f"ページ取得エラー: {request_url} ({exc.code})")
    except urllib.error.URLError as exc:
        return _ng(f"ページ要求エラー: {request_url} ({exc})")
    except UnicodeDecodeError as exc:
        return _ng(f"ページ文字コードエラー: {request_url} ({exc})")

    required_markers = [
        'id="kil-review-source"',
        'id="kil-review-limit"',
        'id="kil-review-refresh"',
        'id="kil-review-status"',
        'id="kil-review-items"',
        'src="/static/js/kil-review.js"',
        "KIL Review Dashboard",
    ]
    missing = [marker for marker in required_markers if marker not in html]
    if missing:
        return _ng(f"/kil-review ページに不足マーカー: {', '.join(missing)}")
    return _ok("kil-review ページ: UIマーカー確認済み")


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        payload_bytes = response.read()
        return payload_bytes.decode("utf-8")


def check_api(base_url: str, strict: bool) -> CheckResult:
    url = base_url.rstrip("/")
    sources = ["auto", "index", "markdown", "all", "fallback"]
    required_top_level = {
        "status",
        "requested_source",
        "source_used",
        "source_counts",
        "count",
        "items",
        "review",
        "risk_counts",
    }

    for source in sources:
        request_url = f"{url}/api/kil-review?source={source}&limit=5"
        try:
            payload = _fetch_json(request_url)
        except urllib.error.HTTPError as exc:
            return _ng(f"HTTPエラー: source={source} ({exc.code})")
        except urllib.error.URLError as exc:
            return _ng(f"API要求エラー: source={source} ({exc})")
        except json.JSONDecodeError:
            return _ng(f"JSONパース失敗: source={source}")

        missing = sorted(required_top_level - set(payload.keys()))
        if missing:
            return _ng(f"{source}: 必須キー不足: {', '.join(missing)}")

        count = payload.get("count")
        if not isinstance(count, int) or count < 0:
            return _ng(f"{source}: count が不正")

        if count != len(payload.get("items", [])):
            return _ng(f"{source}: count({count}) と items 件数({len(payload.get('items', []))}) が不一致")
        if payload.get("limit") != 5:
            return _ng(f"{source}: limit が想定値と異なります ({payload.get('limit')})")

        review = payload.get("review")
        if not isinstance(review, dict):
            return _ng(f"{source}: review は辞書形式ではありません")
        if payload.get("status") != "ok":
            return _ng(f"{source}: status が ok ではありません ({payload.get('status')})")
        if strict:
            source_counts = payload.get("source_counts")
            if not isinstance(source_counts, dict):
                return _ng(f"{source}: source_counts が辞書形式ではありません")
            for key in ("index", "markdown"):
                value = source_counts.get(key)
                if not isinstance(value, int) or value < 0:
                    return _ng(f"{source}: source_counts[{key}] は0以上整数ではありません")

            for key in ("overdue", "due_within_7d", "no_deadline"):
                value = review.get(key)
                if not isinstance(value, int) or value < 0:
                    return _ng(f"{source}: review[{key}] は0以上整数ではありません")

            for item in payload.get("items", []):
                if not isinstance(item, dict):
                    return _ng(f"{source}: items が不正（辞書ではありません）")
                for field in ("source", "commit", "date", "summary"):
                    if not str(item.get(field) or "").strip():
                        return _ng(f"{source}: item に必須項目 '{field}' がありません")
                if item.get("source") not in {"index", "markdown"}:
                    return _ng(f"{source}: 不正な source '{item.get('source')}'")

    return _ok("API チェック: OK")


def run(base_url: str, skip_http: bool, strict: bool) -> int:
    checks: list[CheckResult] = [
        check_required_files(),
        check_server_file_contract(),
    ]

    if not skip_http:
        if strict:
            checks.append(check_kil_review_page(base_url))
            checks.append(check_api(base_url, strict=True))
        else:
            checks.append(check_api(base_url, strict=False))

    failed = [item for item in checks if not item.ok]
    passed = [item for item in checks if item.ok]
    mode = "契約チェック+HTTP API" if not skip_http else "契約チェックのみ"
    print(f"KIL Review 受け入れサマリー: チェック={len(checks)} / 成功={len(passed)} / 失敗={len(failed)} / モード={mode}")

    if failed:
        for item in failed:
            print(f"[未達] {item.message}")
        print(f"\nKIL Review 不合格: {len(failed)} 件のチェックが未達です。")
        return 1

    print("\nKIL Review 合格: 人手レビューは現時点で不要です。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run acceptance checks for KIL Review dashboard page.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base dashboard URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="Skip runtime HTTP checks and validate files/contracts only.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable stricter API and rendered page checks (slower but more complete).",
    )
    args = parser.parse_args()
    return run(base_url=args.base_url, skip_http=args.skip_http, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
