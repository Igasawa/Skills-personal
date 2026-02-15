#!/usr/bin/env python
"""Generate a lightweight review log for official manuals and rules.

Usage:
  python scripts/review_official_manual.py --review-type weekly
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CHECK_TARGETS = [
    (
        "Amazon HelpNode (nodeId=201894740)",
        "https://www.amazon.co.jp/gp/help/customer/display.html?nodeId=201894740",
        "manual",
    ),
    (
        "Amazon order history",
        "https://www.amazon.co.jp/gp/your-account/order-history",
        "internal_scraping_target",
    ),
    (
        "Rakuten FAQ 000006734",
        "https://ichiba.faq.rakuten.net/detail/000006734",
        "manual",
    ),
    (
        "Rakuten Books delivery status",
        "https://books.rakuten.co.jp/mypage/delivery/status",
        "manual",
    ),
    (
        "Rakuten order home",
        "https://order.my.rakuten.co.jp/",
        "internal_scraping_target",
    ),
    (
        "MoneyForward AP guide (AP31)",
        "https://biz.moneyforward.com/support/expense/guide/ap/ap31.html",
        "manual",
    ),
    (
        "MoneyForward personal guide (PA34)",
        "https://biz.moneyforward.com/support/expense/guide/personal/pa34.html",
        "manual",
    ),
    (
        "MoneyForward FAQ r10",
        "https://biz.moneyforward.com/support/expense/faq/ap-faq/r10.html",
        "manual",
    ),
]


@dataclass
class DateCheck:
    source: str
    reviewed: str | None
    days_since: int | None
    is_stale: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run official manual review checks")
    parser.add_argument(
        "--review-type",
        default="weekly",
        choices=["weekly", "monthly", "change_response"],
        help="Review type for generated log",
    )
    parser.add_argument(
        "--knowledge",
        default="references/official_manual_knowledge.yaml",
        help="Path to official_manual_knowledge.yaml",
    )
    parser.add_argument(
        "--alignment-notes",
        default="references/official_manual_alignment_notes.md",
        help="Path to official_manual_alignment_notes.md",
    )
    parser.add_argument(
        "--log-template",
        default="references/official_manual_review_log_template.md",
        help="Path to review log template",
    )
    parser.add_argument(
        "--out-dir",
        default="references/review_logs",
        help="Directory to store review logs",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=10,
        help="HTTP timeout for URL checks",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=14,
        help="Stale threshold in days for reference dates",
    )
    parser.add_argument(
        "--url-retries",
        type=int,
        default=2,
        help="Retry count for URL checks on transient errors",
    )
    parser.add_argument(
        "--url-retry-delay-seconds",
        type=float,
        default=1.5,
        help="Delay in seconds before retrying URL checks",
    )
    parser.add_argument(
        "--skip-url-check",
        action="store_true",
        help="Skip URL availability checks and only verify reference review dates",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report only")
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_iso_date(text: str) -> str | None:
    patterns = [
        re.compile(r"^last_reviewed:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE),
        re.compile(r"^更新日[:：]\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE),
    ]
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def check_last_reviewed(path: Path, max_age_days: int) -> DateCheck:
    text = read_text(path)
    reviewed = extract_iso_date(text)
    if reviewed is None:
        return DateCheck(path.as_posix(), None, None, True)
    reviewed_on = date.fromisoformat(reviewed)
    days_since = (date.today() - reviewed_on).days
    return DateCheck(path.as_posix(), reviewed, days_since, days_since > max_age_days)


def parse_knowledge_sources(path: Path) -> list[dict]:
    text = read_text(path)
    sources: list[dict] = []
    current: dict = {}
    in_official_sources = False

    def flush_current() -> None:
        nonlocal current
        if current.get("url") and current.get("status_check"):
            sources.append(current)
        current = {}

    for line in text.splitlines():
        if re.match(r"^\s*official_sources:\s*$", line):
            in_official_sources = True
            continue

        if not in_official_sources:
            continue

        if re.match(r"^\s*$", line):
            continue

        indent = len(re.match(r"^(\s*)", line).group(1))
        if indent <= 4:
            flush_current()
            in_official_sources = False
            continue

        id_match = re.match(r"^\s{6}-\s*id:\s*(.+?)\s*$", line)
        if id_match:
            flush_current()
            current = {"id": id_match.group(1), "status_check": "manual"}
            continue

        if not current:
            continue

        name_match = re.match(r"^\s{8}name:\s*(.+?)\s*$", line)
        if name_match:
            current["name"] = name_match.group(1)
            continue

        url_match = re.match(r"^\s{8}url:\s*(.+?)\s*$", line)
        if url_match:
            value = url_match.group(1)
            if value.startswith(("http://", "https://")):
                current["url"] = value
            continue

        status_match = re.match(r"^\s{8}status_check:\s*(.+?)\s*$", line)
        if status_match:
            current["status_check"] = status_match.group(1)

    flush_current()
    return sources


def check_url_status(
    url: str,
    timeout_seconds: int,
    retries: int,
    retry_delay_seconds: float,
) -> tuple[str | None, int | None, str | None, int]:
    total_attempts = retries + 1
    for attempt in range(1, total_attempts + 1):
        req = Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ManualReviewBot/1.0)"},
        )
        try:
            with urlopen(req, timeout=timeout_seconds) as response:
                return None, response.status, None, attempt
        except HTTPError as exc:
            if exc.code is not None and 500 <= exc.code < 600 and attempt < total_attempts:
                sleep(retry_delay_seconds)
                continue
            return exc.reason, exc.code, None, attempt
        except URLError as exc:
            if attempt < total_attempts:
                sleep(retry_delay_seconds)
                continue
            return str(exc.reason), None, None, attempt
        except Exception as exc:  # pragma: no cover - defensive path
            if attempt < total_attempts:
                sleep(retry_delay_seconds)
                continue
            return str(exc), None, None, attempt

    return "unreachable", None, None, 0


def build_knowledge_alignment(path: Path) -> dict:
    target_urls_by_status: dict[str, set[str]] = defaultdict(set)
    for _, url, status in CHECK_TARGETS:
        target_urls_by_status[status].add(url)

    knowledge_by_status: dict[str, set[str]] = defaultdict(set)
    for source in parse_knowledge_sources(path):
        status_check = source["status_check"]
        knowledge_by_status[status_check].add(source["url"])

    status_list = sorted(set(target_urls_by_status) | set(knowledge_by_status))
    by_status: dict[str, dict] = {}
    for status in status_list:
        target_urls = target_urls_by_status.get(status, set())
        knowledge_urls = knowledge_by_status.get(status, set())
        by_status[status] = {
            "target_urls": sorted(target_urls),
            "knowledge_urls": sorted(knowledge_urls),
            "missing_in_targets": sorted(knowledge_urls - target_urls),
            "extra_in_targets": sorted(target_urls - knowledge_urls),
            "in_sync": not (knowledge_urls - target_urls) and not (target_urls - knowledge_urls),
        }

    target_urls = set().union(*target_urls_by_status.values()) if target_urls_by_status else set()
    knowledge_urls = set().union(*knowledge_by_status.values()) if knowledge_by_status else set()
    return {
        "status": by_status,
        "target_urls": sorted(target_urls),
        "knowledge_urls": sorted(knowledge_urls),
        "missing_in_targets": sorted(knowledge_urls - target_urls),
        "extra_in_targets": sorted(target_urls - knowledge_urls),
        "in_sync": not (knowledge_urls - target_urls) and not (target_urls - knowledge_urls),
    }


def run_checks(args: argparse.Namespace) -> dict:
    status_checks = []
    alignment = build_knowledge_alignment(Path(args.knowledge))

    for name, url, status in CHECK_TARGETS:
        if args.skip_url_check:
            status_checks.append(
                {
                    "name": name,
                    "url": url,
                    "status_check": status,
                    "ok": True,
                    "status_code": None,
                    "error": "skipped",
                    "checked": False,
                    "attempts": 0,
                }
            )
            continue

        reason, status_code, _, attempts = check_url_status(
            url,
            args.timeout_seconds,
            args.url_retries,
            args.url_retry_delay_seconds,
        )
        status_checks.append(
            {
                "name": name,
                "url": url,
                "status_check": status,
                "ok": status_code is not None and 200 <= status_code < 400,
                "status_code": status_code,
                "error": reason,
                "checked": True,
                "attempts": attempts,
            }
        )

    knowledge_check = check_last_reviewed(Path(args.knowledge), args.max_age_days)
    alignment_check = check_last_reviewed(Path(args.alignment_notes), args.max_age_days)

    return {
        "date": date.today().isoformat(),
        "review_type": args.review_type,
        "sources": status_checks,
        "knowledge": {
            "path": knowledge_check.source,
            "last_reviewed": knowledge_check.reviewed,
            "days_since": knowledge_check.days_since,
            "stale": knowledge_check.is_stale,
        },
        "alignment_notes": {
            "path": alignment_check.source,
            "last_reviewed": alignment_check.reviewed,
            "days_since": alignment_check.days_since,
            "stale": alignment_check.is_stale,
        },
        "max_age_days": args.max_age_days,
        "skip_url_check": args.skip_url_check,
        "knowledge_alignment": alignment,
    }


def render_log(report: dict, template_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().replace(microsecond=0).strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"official_manual_review_{report['review_type']}_{timestamp}.md"

    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""

    url_lines = []
    for source in report["sources"]:
        status = (
            source["status_code"]
            if source["status_code"] is not None
            else (source["error"] or "not_checked")
        )
        suffix = f"{status}"
        if source["attempts"]:
            suffix += f" (attempts={source['attempts']})"
        if source["error"] and source["status_code"] is not None:
            suffix += f" ({source['error']})"
        url_lines.append(f"- {source['name']}: {suffix}")

    alignment_lines = []
    alignment = report["knowledge_alignment"]
    alignment_lines.append(f"- in_sync: {alignment['in_sync']}")
    if alignment["missing_in_targets"]:
        alignment_lines.append(f"- Missing in review targets: {', '.join(alignment['missing_in_targets'])}")
    if alignment["extra_in_targets"]:
        alignment_lines.append(f"- Extra in review targets: {', '.join(alignment['extra_in_targets'])}")
    for status, values in alignment["status"].items():
        alignment_lines.append(f"- status_check={status}")
        if values["missing_in_targets"]:
            alignment_lines.append(f"  - Missing in review targets: {', '.join(values['missing_in_targets'])}")
        if values["extra_in_targets"]:
            alignment_lines.append(f"  - Extra in review targets: {', '.join(values['extra_in_targets'])}")
        if not values["missing_in_targets"] and not values["extra_in_targets"]:
            alignment_lines.append("  - No mismatch")
    if not alignment_lines:
        alignment_lines.append("- Knowledge URLs and review targets are aligned")

    log_body = []
    log_body.append("# 正式ドキュメント連携レビュー")
    log_body.append("")
    log_body.append(f"実施日: {report['date']}")
    log_body.append(f"レビュー種別: {report['review_type']}")
    log_body.append(f"許容経過日数: {report['max_age_days']}")
    log_body.append("")
    log_body.append("## 1. URLチェック")
    log_body.extend(url_lines)
    log_body.append("")
    log_body.append("## 2. 知識ファイル更新")
    log_body.append(f"- `{report['knowledge']['path']}`: {report['knowledge']['last_reviewed']} (stale={report['knowledge']['stale']})")
    log_body.append(f"- `{report['alignment_notes']['path']}`: {report['alignment_notes']['last_reviewed']} (stale={report['alignment_notes']['stale']})")
    log_body.append("")
    log_body.append("## 3. 照合")
    log_body.extend(alignment_lines)
    log_body.append("")
    if template:
        log_body.append("## 4. 運用メモ")
        log_body.append(template.strip())
        log_body.append("")
    log_body.append("## 5. JSON")
    log_body.append("```json")
    log_body.append(json.dumps(report, ensure_ascii=False, indent=2))
    log_body.append("```")

    out_path.write_text("\n".join(log_body) + "\n", encoding="utf-8")
    return out_path


def all_ok(report: dict) -> bool:
    source_ok = all(source["ok"] for source in report["sources"] if source.get("checked", True))
    return (
        source_ok
        and not report["knowledge"]["stale"]
        and not report["alignment_notes"]["stale"]
        and report["knowledge_alignment"]["in_sync"]
    )


def main() -> int:
    args = parse_args()
    report = run_checks(args)
    out_path = render_log(
        report=report,
        template_path=Path(args.log_template),
        out_dir=Path(args.out_dir),
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        failed = [s for s in report["sources"] if not s["ok"]]
        print(f"Review type: {report['review_type']}")
        print(f"Log: {out_path}")
        if report["skip_url_check"]:
            print("URL checks: skipped")
        if failed:
            print("Unhealthy source(s):")
            for item in failed:
                print(f" - {item['name']}: {item['status_code'] or item['error']}")
        if not report["knowledge_alignment"]["in_sync"]:
            print("Knowledge/targets are not aligned:")
            if report["knowledge_alignment"]["missing_in_targets"]:
                print(f" - Missing in review targets: {report['knowledge_alignment']['missing_in_targets']}")
            if report["knowledge_alignment"]["extra_in_targets"]:
                print(f" - Extra in review targets: {report['knowledge_alignment']['extra_in_targets']}")
        print(f"knowledge_stale: {report['knowledge']['stale']}")
        print(f"alignment_notes_stale: {report['alignment_notes']['stale']}")

    return 0 if all_ok(report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
