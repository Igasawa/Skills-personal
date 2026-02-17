#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULTS = {
    "mode": "aggregate",
    "csv": {
        "encoding": "auto",
        "delimiter": "auto",
        "amount_column": "税込小計",
        "date_column": None,
        "date_column_candidates": ["受付日", "伝票日付", "注文日"],
        "item_column_candidates": ["商品名", "商品情報"],
        "comment_column_candidates": ["備考", "コメント"],
        "tenant_column": None,
        "tenant_default": "UNKNOWN",
        "tenant_rules": [],
        "tenant_map": None,
        "min_tenant_confidence": 0.6,
        "allow_negative": True,
    },
    "filters": {
        "min_date": None,
        "max_date": None,
    },
    "reporting": {
        "output_dir": None,
        "include_item_breakdown": True,
    },
    "dry_run": True,
}


DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y%m%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y.%m.%d %H:%M:%S",
)


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"invalid boolean: {value!r}")


def _read_payload(path: str | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload: dict[str, Any] = {}
    if path:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("Input JSON must be an object")

    if not payload and not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Input JSON must be an object")

    config = payload.get("config", {}) if isinstance(payload, dict) else {}
    params = payload.get("params", {}) if isinstance(payload, dict) else {}
    if not isinstance(config, dict) or not isinstance(params, dict):
        raise ValueError("config and params must be objects")
    return payload, config, params


def _detect_encoding(path: Path, configured: str) -> str:
    candidates = [configured]
    if configured == "auto":
        candidates = ["utf-8-sig", "utf-8", "cp932", "shift_jis"]
    for encoding in candidates:
        try:
            with path.open("r", encoding=encoding, errors="strict") as f:
                f.read(1024)
            return encoding
        except Exception:
            continue
    return "utf-8-sig"


def _detect_delimiter(path: Path, configured: str, encoding: str) -> str:
    if configured != "auto":
        return configured
    with path.open("r", encoding=encoding, errors="replace") as f:
        sample = f.read(4096)
    for delimiter in (",", "\t", ";"):
        try:
            csv.Sniffer().sniff(sample, delimiters=[delimiter])
            return delimiter
        except Exception:
            pass
    return ","


def _normalize_column(value: str) -> str:
    return value.strip().lower().replace(" ", "").replace("　", "")


def _guess_column(headers: list[str], candidates: list[str]) -> str | None:
    normalized = {_normalize_column(h): h for h in headers if h is not None}
    for candidate in candidates:
        if candidate in headers:
            return candidate
        found = normalized.get(_normalize_column(candidate))
        if found:
            return found
    return None


def _parse_amount(value: Any) -> float:
    text = _to_str(value)
    if not text:
        raise ValueError("empty amount")
    text = (
        text.replace(",", "")
        .replace("¥", "")
        .replace("￥", "")
        .replace("（", "-")
        .replace("）", "")
        .replace("−", "-")
        .replace("－", "-")
        .replace(" ", "")
    )
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if not re.search(r"\d", text):
        raise ValueError(f"invalid amount: {value!r}")
    return float(text)


def _parse_date(value: Any) -> dt.date | None:
    text = _to_str(value).replace("/", "-").replace(".", "-")
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except Exception:
            pass
    return None


def _build_tenant_rules(raw_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for raw in raw_rules:
        if not isinstance(raw, dict):
            continue
        tenant = _to_str(raw.get("tenant"))
        pattern = _to_str(raw.get("pattern"))
        if not tenant or not pattern:
            continue
        fields = raw.get("fields", [])
        if fields is None:
            fields = []
        if not isinstance(fields, list):
            raise ValueError("tenant rule fields must be an array")
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        rules.append(
            {
                "tenant": tenant,
                "pattern": pattern,
                "fields": [_to_str(f) for f in fields if _to_str(f)],
                "regex": regex,
            }
        )
    return rules


def _load_csv_rows(path: Path, encoding: str, delimiter: str) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding=encoding, newline="", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = [h for h in (reader.fieldnames or [])]
        rows = [row for row in reader]
    return headers, rows


def _resolve_tenant(
    row: dict[str, str],
    *,
    tenant_column: str | None,
    tenant_default: str,
    tenant_rules: list[dict[str, Any]],
    item_column: str | None,
    comment_column: str | None,
) -> tuple[str, float]:
    if tenant_column and _to_str(row.get(tenant_column)):
        return _to_str(row.get(tenant_column)), 1.0

    target_fields = []
    if item_column and _to_str(row.get(item_column)):
        target_fields.append(_to_str(row.get(item_column)))
    if comment_column and _to_str(row.get(comment_column)):
        target_fields.append(_to_str(row.get(comment_column)))

    for rule in tenant_rules:
        values = []
        if rule["fields"]:
            for field in rule["fields"]:
                if _to_str(row.get(field)):
                    values.append(_to_str(row.get(field)))
        else:
            values.extend(target_fields)
        if not values:
            continue
        text = " ".join(values)
        if rule["regex"].search(text):
            return rule["tenant"], 0.92

    return tenant_default, 0.0


def _aggregate_rows(rows: list[dict[str, str]], headers: list[str], options: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    date_col = options["date_column"]
    amount_col = options["amount_column"]
    item_col = options["item_column"]
    comment_col = options["comment_column"]

    if not amount_col:
        raise ValueError("amount column not specified and cannot be detected")
    if _normalize_column(amount_col) not in {_normalize_column(h) for h in headers}:
        raise ValueError(f"amount column not found: {amount_col}")

    min_date = _parse_date(options["min_date"]) if options["min_date"] else None
    max_date = _parse_date(options["max_date"]) if options["max_date"] else None
    min_conf = float(options["min_tenant_confidence"])
    allow_negative = bool(options["allow_negative"])

    totals: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    rows_total = len(rows)
    rows_aggregated = 0
    rows_skipped = 0
    unclassified = 0

    for idx, row in enumerate(rows, 1):
        try:
            amount = _parse_amount(row.get(amount_col))
        except Exception:
            rows_skipped += 1
            warnings.append(f"row {idx}: amount parse failed")
            continue

        if amount < 0 and not allow_negative:
            rows_skipped += 1
            warnings.append(f"row {idx}: negative amount skipped")
            continue

        if date_col:
            date_value = _parse_date(row.get(date_col))
            if date_value is None:
                if min_date or max_date:
                    rows_skipped += 1
                    warnings.append(f"row {idx}: date parse failed")
                    continue
            else:
                if min_date and date_value < min_date:
                    rows_skipped += 1
                    continue
                if max_date and date_value > max_date:
                    rows_skipped += 1
                    continue

        tenant, conf = _resolve_tenant(
            row,
            tenant_column=options["tenant_column"],
            tenant_default=options["tenant_default"],
            tenant_rules=options["tenant_rules"],
            item_column=item_col,
            comment_column=comment_col,
        )
        if conf < min_conf:
            tenant = options["tenant_default"]
            unclassified += 1

        bucket = totals.setdefault(
            tenant,
            {
                "tenant": tenant,
                "rows": 0,
                "classified_rows": 0,
                "unclassified_rows": 0,
                "total_amount": 0.0,
                "items": defaultdict(float),
            },
        )
        bucket["rows"] += 1
        bucket["total_amount"] += amount
        if conf >= min_conf:
            bucket["classified_rows"] += 1
        else:
            bucket["unclassified_rows"] += 1
        item_name = _to_str(row.get(item_col)) if item_col else ""
        bucket["items"][item_name or "(不明)"] += amount
        rows_aggregated += 1

    summary_rows = []
    for tenant_name, value in totals.items():
        summary_rows.append(
            {
                "tenant": tenant_name,
                "rows": value["rows"],
                "classified_rows": value["classified_rows"],
                "unclassified_rows": value["unclassified_rows"],
                "total_amount": round(float(value["total_amount"]), 2),
            }
        )
    summary_rows.sort(key=lambda x: (x["total_amount"], x["rows"]), reverse=True)

    metadata = {
        "rows_total": rows_total,
        "rows_aggregated": rows_aggregated,
        "rows_skipped": rows_skipped,
        "unclassified_rows": unclassified,
        "tenant_count": len(summary_rows),
    }

    return summary_rows, totals, metadata, warnings


def _write_reports(output_dir: Path, summary_rows: list[dict[str, Any]], totals: dict[str, Any], include_item_breakdown: bool) -> dict[str, str | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_csv = output_dir / f"tenant_summary_{stamp}.csv"
    summary_json = output_dir / f"tenant_summary_{stamp}.json"

    with summary_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["tenant", "rows", "classified_rows", "unclassified_rows", "total_amount"],
        )
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    with summary_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": dt.datetime.now().isoformat(),
                "summary": summary_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    item_csv: Path | None = None
    if include_item_breakdown:
        item_csv = output_dir / f"tenant_item_breakdown_{stamp}.csv"
        with item_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["tenant", "item", "total_amount"])
            writer.writeheader()
            for tenant_name, entry in totals.items():
                for item_name, amount in entry["items"].items():
                    writer.writerow(
                        {
                            "tenant": tenant_name,
                            "item": item_name,
                            "total_amount": round(float(amount), 2),
                        }
                    )

    return {
        "summary_csv": str(summary_csv),
        "summary_json": str(summary_json),
        "item_breakdown_csv": str(item_csv) if item_csv else None,
    }


def _validate_only(rows: list[dict[str, str]], headers: list[str], options: dict[str, Any]) -> dict[str, Any]:
    required_amount = options["amount_column"]
    required_amount_found = (
        _normalize_column(required_amount) in {_normalize_column(h) for h in headers}
    )
    required_date_found = True
    if options["date_column"]:
        required_date_found = _normalize_column(options["date_column"]) in {_normalize_column(h) for h in headers}

    amount_ok = 0
    date_ok = 0
    for row in rows:
        try:
            _parse_amount(row.get(required_amount))
            amount_ok += 1
        except Exception:
            pass
        if options["date_column"]:
            if _parse_date(row.get(options["date_column"])):
                date_ok += 1

    return {
        "rows": len(rows),
        "headers": headers,
        "required": {
            "amount_found": required_amount_found,
            "date_found": required_date_found,
        },
        "rows_amount_parseable": amount_ok,
        "rows_date_parseable": date_ok if options["date_column"] else None,
    }


def _build_options(
    args: argparse.Namespace,
    config: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    csv_cfg = _coalesce(params.get("csv"), config.get("csv"), DEFAULTS["csv"])
    if not isinstance(csv_cfg, dict):
        raise ValueError("csv config must be an object")
    filter_cfg = _coalesce(params.get("filters"), config.get("filters"), DEFAULTS["filters"])
    report_cfg = _coalesce(params.get("reporting"), config.get("reporting"), DEFAULTS["reporting"])
    if not isinstance(filter_cfg, dict) or not isinstance(report_cfg, dict):
        raise ValueError("filters/reporting config must be objects")

    csv_path = _coalesce(args.csv_path, params.get("csv_path"), config.get("csv_path"), "")
    if not csv_path:
        raise ValueError("csv_path is required")

    amount_column = _coalesce(
        args.amount_column,
        params.get("amount_column"),
        csv_cfg.get("amount_column"),
    )
    date_column = _coalesce(
        args.date_column,
        params.get("date_column"),
        csv_cfg.get("date_column"),
    )
    item_column = _coalesce(
        args.item_column,
        params.get("item_column"),
        csv_cfg.get("item_column"),
    )
    comment_column = _coalesce(
        args.comment_column,
        params.get("comment_column"),
        csv_cfg.get("comment_column"),
    )

    tenant_map_path = _coalesce(args.tenant_map, params.get("tenant_map"), csv_cfg.get("tenant_map"))
    tenant_map = {}
    if tenant_map_path:
        tenant_map = _read_json(tenant_map_path) if isinstance(tenant_map_path, str) else {}
        if not isinstance(tenant_map, dict):
            raise ValueError("tenant map must be an object")

    tenant_default = _coalesce(
        args.tenant_default,
        tenant_map.get("tenant_default"),
        params.get("tenant_default"),
        csv_cfg.get("tenant_default"),
    )
    tenant_column = _coalesce(
        args.tenant_column,
        tenant_map.get("tenant_column"),
        params.get("tenant_column"),
        csv_cfg.get("tenant_column"),
    )
    tenant_rules = []
    for raw in tenant_map.get("rules", []):
        if isinstance(raw, dict):
            tenant_rules.append(raw)
    for raw in csv_cfg.get("tenant_rules", []):
        if isinstance(raw, dict):
            tenant_rules.append(raw)
    for text in args.tenant_rule:
        if ":" not in text:
            raise ValueError(f"invalid tenant rule: {text}")
        tenant, pattern, *_rest = text.split(":", 2)
        fields = []
        if _rest:
            fields = [_s for _s in _rest[0].split(",") if _s.strip()]
        tenant_rules.append(
            {
                "tenant": tenant.strip(),
                "pattern": pattern.strip(),
                "fields": fields,
            }
        )
    rules = _build_tenant_rules(tenant_rules)

    return {
        "mode": _coalesce(args.mode, params.get("mode"), config.get("mode"), DEFAULTS["mode"]),
        "csv_path": csv_path,
        "encoding": _coalesce(args.encoding, csv_cfg.get("encoding"), DEFAULTS["csv"]["encoding"]),
        "delimiter": _coalesce(args.delimiter, csv_cfg.get("delimiter"), DEFAULTS["csv"]["delimiter"]),
        "amount_column": _coalesce(amount_column, DEFAULTS["csv"]["amount_column"]),
        "date_column": date_column,
        "item_column": item_column,
        "comment_column": comment_column,
        "tenant_column": tenant_column,
        "tenant_default": tenant_default or "UNKNOWN",
        "tenant_rules": rules,
        "min_tenant_confidence": float(
            _coalesce(args.min_tenant_confidence, csv_cfg.get("min_tenant_confidence"), DEFAULTS["csv"]["min_tenant_confidence"])
        ),
        "allow_negative": _as_bool(_coalesce(args.allow_negative, csv_cfg.get("allow_negative"), DEFAULTS["csv"]["allow_negative"]), default=True),
        "date_column_candidates": _coalesce(
            csv_cfg.get("date_column_candidates"), DEFAULTS["csv"]["date_column_candidates"]
        ),
        "item_column_candidates": _coalesce(
            csv_cfg.get("item_column_candidates"), DEFAULTS["csv"]["item_column_candidates"]
        ),
        "comment_column_candidates": _coalesce(
            csv_cfg.get("comment_column_candidates"), DEFAULTS["csv"]["comment_column_candidates"]
        ),
        "min_date": _coalesce(args.min_date, filter_cfg.get("min_date"), DEFAULTS["filters"]["min_date"]),
        "max_date": _coalesce(args.max_date, filter_cfg.get("max_date"), DEFAULTS["filters"]["max_date"]),
        "output_dir": _coalesce(args.output_dir, report_cfg.get("output_dir"), DEFAULTS["reporting"]["output_dir"]),
        "include_item_breakdown": _as_bool(
            _coalesce(
                args.include_item_breakdown,
                report_cfg.get("include_item_breakdown"),
                DEFAULTS["reporting"]["include_item_breakdown"],
            ),
            default=True,
        ),
        "dry_run": _as_bool(_coalesce(config.get("dry_run"), params.get("dry_run"), DEFAULTS["dry_run"]), default=True),
    }


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("tenant map must be an object")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="aggregate askul csv by tenant")
    p.add_argument("--input", help="JSON input file")
    p.add_argument("--mode", choices=("aggregate", "validate"))
    p.add_argument("--csv-path")
    p.add_argument("--amount-column")
    p.add_argument("--date-column")
    p.add_argument("--item-column")
    p.add_argument("--comment-column")
    p.add_argument("--tenant-column")
    p.add_argument("--tenant-default")
    p.add_argument("--tenant-rule", action="append", default=[])
    p.add_argument("--tenant-map")
    p.add_argument("--min-tenant-confidence", type=float)
    p.add_argument("--encoding", choices=("auto", "utf-8", "utf-8-sig", "cp932", "shift_jis"))
    p.add_argument("--delimiter", choices=("auto", ",", "\t", ";"))
    p.add_argument("--allow-negative", action="store_true")
    p.add_argument("--min-date")
    p.add_argument("--max-date")
    p.add_argument("--output-dir")
    p.add_argument("--include-item-breakdown", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    payload, config, params = _read_payload(args.input)
    options = _build_options(args, config, params)

    if args.apply and args.dry_run:
        raise ValueError("--apply and --dry-run cannot be set together")
    if args.apply:
        options["dry_run"] = False
    elif args.dry_run:
        options["dry_run"] = True

    path = Path(str(options["csv_path"]))
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    encoding = _detect_encoding(path, options["encoding"])
    delimiter = _detect_delimiter(path, options["delimiter"], encoding)

    headers, rows = _load_csv_rows(path, encoding, delimiter)
    header_map = {_normalize_column(h): h for h in headers if _normalize_column(h)}

    date_candidates = options["date_column_candidates"] if isinstance(options["date_column_candidates"], list) else []
    item_candidates = options["item_column_candidates"] if isinstance(options["item_column_candidates"], list) else []
    comment_candidates = options["comment_column_candidates"] if isinstance(options["comment_column_candidates"], list) else []

    options["amount_column"] = _guess_column(headers, [options["amount_column"]] if options["amount_column"] else [])
    if options["date_column"] and _normalize_column(options["date_column"]) not in header_map:
        options["date_column"] = _guess_column(headers, date_candidates)
    if options["item_column"] and _normalize_column(options["item_column"]) not in header_map:
        options["item_column"] = _guess_column(headers, item_candidates)
    if options["comment_column"] and _normalize_column(options["comment_column"]) not in header_map:
        options["comment_column"] = _guess_column(headers, comment_candidates)
    if options["tenant_column"] and _normalize_column(options["tenant_column"]) in header_map:
        options["tenant_column"] = header_map[_normalize_column(options["tenant_column"])]
    else:
        options["tenant_column"] = None

    if options["amount_column"]:
        options["amount_column"] = header_map.get(_normalize_column(options["amount_column"]), options["amount_column"])
    if options["date_column"]:
        options["date_column"] = header_map.get(_normalize_column(options["date_column"]), options["date_column"])
    if options["item_column"]:
        options["item_column"] = header_map.get(_normalize_column(options["item_column"]), options["item_column"])
    if options["comment_column"]:
        options["comment_column"] = header_map.get(_normalize_column(options["comment_column"]), options["comment_column"])

    if options["mode"] == "validate":
        validation = _validate_only(rows, headers, options)
        out = {
            "status": "ok",
            "data": {
                "mode": "validate",
                "validation": validation,
                "input": {
                    "csv_path": str(path),
                    "encoding": encoding,
                    "delimiter": delimiter,
                },
                "dry_run": options["dry_run"],
                "applied": False,
            },
            "error": None,
        }
        print(json.dumps(out, ensure_ascii=False))
        return 0

    summary_rows, item_totals, metadata, warnings = _aggregate_rows(rows, headers, options)

    reports: dict[str, Any] = {"written": False}
    if not options["dry_run"]:
        base_dir = _coalesce(options["output_dir"], None)
        if base_dir:
            report_dir = Path(str(base_dir))
        else:
            base_dir = os.environ.get("AX_HOME", str(Path.home() / ".ax"))
            report_dir = Path(base_dir) / "reports" / "askul_tenant_purchase"
        reports = _write_reports(
            report_dir,
            summary_rows,
            item_totals,
            include_item_breakdown=options["include_item_breakdown"],
        )
        reports["written"] = True
        reports["output_dir"] = str(report_dir)

    out = {
        "status": "ok",
        "data": {
            "mode": "aggregate",
            "input": {
                "csv_path": str(path),
                "encoding": encoding,
                "delimiter": delimiter,
                "min_date": options["min_date"],
                "max_date": options["max_date"],
            },
            "summary": {
                **metadata,
                "tenant_default": options["tenant_default"],
            },
            "rows": summary_rows,
            "warnings": warnings,
            "dry_run": options["dry_run"],
            "applied": not options["dry_run"],
            "reports": reports,
        },
        "error": None,
    }

    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        out = {
            "status": "error",
            "data": {},
            "error": {"message": str(e)},
        }
        print(json.dumps(out, ensure_ascii=False))
        raise SystemExit(1)
