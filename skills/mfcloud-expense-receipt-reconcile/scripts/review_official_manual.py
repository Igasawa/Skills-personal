#!/usr/bin/env python
"""Generate a lightweight review log for official manuals and rules.

Usage:
  python scripts/review_official_manual.py --review-type weekly
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CHECK_TARGETS = [
    ("Amazon HelpNode (nodeId=201894740)", "https://www.amazon.co.jp/gp/help/customer/display.html?nodeId=201894740"),
    ("Amazon 注文履歴", "https://www.amazon.co.jp/gp/your-account/order-history"),
    ("楽天FAQ 000006734", "https://ichiba.faq.rakuten.net/detail/000006734"),
    ("楽天Books", "https://books.rakuten.co.jp/mypage/delivery/status"),
    ("MF AP ガイド", "https://biz.moneyforward.com/support/expense/guide/ap/ap31.html"),
    ("MF Personal ガイド", "https://biz.moneyforward.com/support/expense/guide/personal/pa34.html"),
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


def check_url_status(url: str, timeout_seconds: int) -> tuple[str | None, int | None, str | None]:
    req = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ManualReviewBot/1.0)"},
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            return None, response.status, None
    except HTTPError as exc:
        return exc.reason, exc.code, None
    except URLError as exc:
        return str(exc.reason), None, None
    except Exception as exc:  # pragma: no cover - defensive path
        return str(exc), None, None


def run_checks(args: argparse.Namespace) -> dict:
    status_checks = []
    for name, url in CHECK_TARGETS:
        reason, status_code, _ = check_url_status(url, args.timeout_seconds)
        status_checks.append(
            {
                "name": name,
                "url": url,
                "ok": status_code is not None and 200 <= status_code < 400,
                "status_code": status_code,
                "error": reason,
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
    }


def render_log(report: dict, template_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    out_path = out_dir / f"official_manual_review_{report['review_type']}_{timestamp[:10]}.md"

    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    url_lines = []
    for source in report["sources"]:
        status = source["status_code"] if source["status_code"] is not None else "error"
        suffix = f"{status}"
        if source["error"]:
            suffix += f" ({source['error']})"
        url_lines.append(f"- {source['name']}: {suffix}")

    log_body = []
    log_body.append("# 公式マニュアル監査結果（自動記録）")
    log_body.append("")
    log_body.append(f"実施日: {report['date']}")
    log_body.append(f"レビュー種別: {report['review_type']}")
    log_body.append(f"チェック基準: {report['max_age_days']}日以上は要更新")
    log_body.append("")
    log_body.append("## 1. URL 到達確認")
    log_body.extend(url_lines)
    log_body.append("")
    log_body.append("## 2. ルール基準日チェック")
    log_body.append(f"- `{report['knowledge']['path']}`: {report['knowledge']['last_reviewed']} (stale={report['knowledge']['stale']})")
    log_body.append(f"- `{report['alignment_notes']['path']}`: {report['alignment_notes']['last_reviewed']} (stale={report['alignment_notes']['stale']})")
    log_body.append("")
    log_body.append("## 3. 監査ログ（テンプレート）")
    if template:
        log_body.append(template.strip())
    log_body.append("")
    log_body.append("## 4. 生データ")
    log_body.append("```json")
    log_body.append(json.dumps(report, ensure_ascii=False, indent=2))
    log_body.append("```")

    out_path.write_text("\n".join(log_body) + "\n", encoding="utf-8")
    return out_path


def all_ok(report: dict) -> bool:
    source_ok = all(source["ok"] for source in report["sources"])
    return source_ok and not report["knowledge"]["stale"] and not report["alignment_notes"]["stale"]


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
        if failed:
            print("Unhealthy source(s):")
            for item in failed:
                print(f" - {item['name']}: {item['status_code'] or item['error']}")
        print(f"knowledge_stale: {report['knowledge']['stale']}")
        print(f"alignment_notes_stale: {report['alignment_notes']['stale']}")

    return 0 if all_ok(report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
