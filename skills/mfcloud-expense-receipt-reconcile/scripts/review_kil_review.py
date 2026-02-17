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
        return _ng(f"required files missing: {', '.join(missing)}")
    return _ok("required files exist")


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
        _ok("pages.py has /kil-review route")
        if _contains(pages, '"/kil-review"')
        else _ng("pages.py is missing route /kil-review")
    )
    checks.append(
        _ok("api.py has /api/kil-review endpoint")
        if _contains(api, '"/api/kil-review"')
        else _ng("api.py is missing /api/kil-review endpoint")
    )
    checks.append(
        _ok("common.js has kil-review nav link")
        if _contains(common, '"/kil-review"') and _contains(common, 'tab: "kil-review"')
        else _ng("common.js does not include /kil-review menu definition")
    )
    checks.append(
        _ok("common.js handles kil-review active tab")
        if _contains(common, '"/kil-review"') and _contains(common, 'if (normalized === "/kil-review")')
        else _ng("common.js does not handle /kil-review active tab")
    )
    checks.append(
        _ok("kil_review.html includes required ids")
        if all(_contains(template, needle) for needle in ("kil-review-source", "kil-review-limit", "kil-review-refresh"))
        else _ng("kil_review.html is missing required element ids")
    )
    checks.append(
        _ok("kil-review.js calls /api/kil-review")
        if _contains(scripts, '"/api/kil-review"')
        else _ng("kil-review.js is missing api request")
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


def check_api(base_url: str) -> CheckResult:
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
            return _ng(f"HTTP error for source={source}: {exc.code}")
        except urllib.error.URLError as exc:
            return _ng(f"Request failed for source={source}: {exc}")
        except json.JSONDecodeError:
            return _ng(f"Invalid JSON for source={source}")

        missing = sorted(required_top_level - set(payload.keys()))
        if missing:
            return _ng(f"{source}: missing top-level keys: {', '.join(missing)}")

        count = payload.get("count")
        if not isinstance(count, int) or count < 0:
            return _ng(f"{source}: invalid count value")

        if count != len(payload.get("items", [])):
            return _ng(f"{source}: count({count}) does not match rows({len(payload.get('items', []))})")

        review = payload.get("review")
        if not isinstance(review, dict):
            return _ng(f"{source}: review must be dict")
        if payload.get("status") != "ok":
            return _ng(f"{source}: status is not ok ({payload.get('status')})")

    return _ok("api checks passed")


def run(base_url: str, skip_http: bool) -> int:
    checks: list[CheckResult] = [
        check_required_files(),
        check_server_file_contract(),
    ]

    if not skip_http:
        checks.append(check_api(base_url))

    failed = [item for item in checks if not item.ok]
    if failed:
        for item in failed:
            print(f"[NG] {item.message}")
        print(f"\nKIL review failed: {len(failed)} check(s) failed.")
        return 1

    print("\nKIL review checks passed. No review required.")
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
    args = parser.parse_args()
    return run(base_url=args.base_url, skip_http=args.skip_http)


if __name__ == "__main__":
    raise SystemExit(main())
