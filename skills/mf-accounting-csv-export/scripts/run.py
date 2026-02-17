#!/usr/bin/env python3
"""
Validate and normalize Money Forward Cloud Accounting CSV exports.

Standard JSON interface:
Input (stdin or --input):
{
  "config": {
    "dry_run": true,
    "csv": {
      "preset": "journal_standard",
      "required_columns": ["取引No", "取引日", "金額(円)"],
      "non_empty_columns": ["取引No", "取引日", "金額(円)"],
      "date_column": "取引日",
      "amount_columns": ["金額(円)"],
      "encoding": "auto",
      "delimiter": "auto",
      "write_normalized": true
    },
    "paths": {
      "download_url": null,
      "watch_dir": null,
      "download_dir": null,
      "output_dir": null
    },
    "playwright": {
      "session_name": "mf-accounting",
      "storage_state_path": null
    }
  },
  "params": {
    "mode": "validate|watch|download",
    "csv_path": "C:/work/mf/journal.csv",
    "min_date": "2026-01-01",
    "max_date": "2026-01-31"
  }
}
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any


DEFAULT_REQUIRED_COLUMNS = [
    "取引No",
    "取引日",
    "勘定科目",
    "補助科目",
    "部門",
    "取引先",
    "税区分",
    "インボイス",
    "金額(円)",
    "摘要",
    "タグ",
    "メモ",
]
DEFAULT_NON_EMPTY_COLUMNS = ["取引No", "取引日", "金額(円)"]
DEFAULT_DATE_COLUMN = "取引日"
DEFAULT_AMOUNT_COLUMNS = ["金額(円)"]
DEFAULT_PRESET_NAME = "journal_standard"
DEFAULT_MODE = "validate"
DEFAULT_WATCH_PATTERN = "*.csv"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_SAMPLE_ROWS = 3
DEFAULT_SESSION_NAME = "mf-accounting"
DEFAULT_DOWNLOAD_FILE_PREFIX = "mf_export"
MAX_EXAMPLE_ROWS = 20

# Sources were checked on 2026-02-17.
PRESET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "journal_standard": {
        "description": "クラウド会計 仕訳帳（単式金額列）",
        "required_columns": [
            "取引No",
            "取引日",
            "勘定科目",
            "補助科目",
            "部門",
            "取引先",
            "税区分",
            "インボイス",
            "金額(円)",
            "摘要",
            "タグ",
            "メモ",
        ],
        "non_empty_columns": ["取引No", "取引日", "金額(円)"],
        "date_column": "取引日",
        "amount_columns": ["金額(円)"],
        "key_columns": ["取引No"],
        "sources": [
            "https://biz.moneyforward.com/support/account/guide/books2/bo01.html",
        ],
    },
    "journal_plus": {
        "description": "クラウド会計Plus 仕訳帳（借方/貸方の複式列）",
        "required_columns": [
            "取引No",
            "取引日",
            "借方勘定科目コード",
            "借方勘定科目",
            "借方補助科目コード",
            "借方補助科目",
            "借方税区分",
            "借方金額(円)",
            "貸方勘定科目コード",
            "貸方勘定科目",
            "貸方補助科目コード",
            "貸方補助科目",
            "貸方税区分",
            "貸方金額(円)",
            "摘要",
            "タグ",
            "メモ",
        ],
        "non_empty_columns": ["取引No", "取引日", "借方金額(円)", "貸方金額(円)"],
        "date_column": "取引日",
        "amount_columns": ["借方金額(円)", "貸方金額(円)"],
        "key_columns": ["取引No"],
        "sources": [
            "https://biz.moneyforward.com/support/ac-plus/news/20230331.html",
        ],
    },
    "general_ledger_plus": {
        "description": "クラウド会計Plus 総勘定元帳/補助元帳/現金出納帳",
        "required_columns": [
            "勘定科目コード",
            "勘定科目",
            "補助科目コード",
            "補助科目",
            "取引No",
            "取引日",
            "借方勘定科目コード",
            "借方勘定科目",
            "借方補助科目コード",
            "借方補助科目",
            "借方税区分",
            "借方金額(円)",
            "貸方勘定科目コード",
            "貸方勘定科目",
            "貸方補助科目コード",
            "貸方補助科目",
            "貸方税区分",
            "貸方金額(円)",
            "残高",
            "摘要",
            "タグ",
            "メモ",
        ],
        "non_empty_columns": ["取引No", "取引日"],
        "date_column": "取引日",
        "amount_columns": ["借方金額(円)", "貸方金額(円)", "残高"],
        "key_columns": ["勘定科目コード", "補助科目コード", "取引No"],
        "sources": [
            "https://biz.moneyforward.com/support/ac-plus/news/20230331.html",
        ],
    },
    "trial_balance_plus_core": {
        "description": "クラウド会計Plus 残高試算表（コア列）",
        "required_columns": ["勘定科目コード", "勘定科目", "補助科目コード", "補助科目"],
        "non_empty_columns": ["勘定科目コード", "勘定科目"],
        "date_column": None,
        "amount_columns": [],
        "key_columns": ["勘定科目コード", "補助科目コード"],
        "sources": [
            "https://biz.moneyforward.com/support/ac-plus/news/20240307.html",
        ],
    },
    "transition_plus_core": {
        "description": "クラウド会計Plus 推移表（コア列）",
        "required_columns": ["勘定科目コード", "勘定科目", "補助科目コード", "補助科目"],
        "non_empty_columns": ["勘定科目コード", "勘定科目"],
        "date_column": None,
        "amount_columns": [],
        "key_columns": ["勘定科目コード", "補助科目コード"],
        "sources": [
            "https://biz.moneyforward.com/support/ac-plus/news/20240307.html",
        ],
    },
}


def _ensure_utf8_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")


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
    s = str(value).strip()
    return s or None


def _as_int(value: Any, *, name: str) -> int:
    if value is None:
        raise ValueError(f"Missing required integer: {name}")
    try:
        return int(value)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid integer for {name}: {value!r}") from e


def _as_float(value: Any, *, name: str) -> float:
    if value is None:
        raise ValueError(f"Missing required float: {name}")
    try:
        return float(value)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid float for {name}: {value!r}") from e


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


def _normalize_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, int, float)):
        values = [values]
    if not isinstance(values, list):
        values = list(values)
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        s = _blank_to_none(v)
        if s is None:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _resolve_preset(name: str | None) -> tuple[str, dict[str, Any]]:
    preset_name = _blank_to_none(name) or DEFAULT_PRESET_NAME
    if preset_name not in PRESET_DEFINITIONS:
        raise ValueError(f"Unsupported preset: {preset_name!r}")
    return preset_name, PRESET_DEFINITIONS[preset_name]


def _list_presets_payload() -> dict[str, Any]:
    items: dict[str, Any] = {}
    for name, spec in PRESET_DEFINITIONS.items():
        items[name] = {
            "description": spec.get("description"),
            "required_columns": list(spec.get("required_columns") or []),
            "non_empty_columns": list(spec.get("non_empty_columns") or []),
            "date_column": spec.get("date_column"),
            "amount_columns": list(spec.get("amount_columns") or []),
            "key_columns": list(spec.get("key_columns") or []),
            "sources": list(spec.get("sources") or []),
        }
    return {"default_preset": DEFAULT_PRESET_NAME, "presets": items}


def _ax_home() -> Path:
    configured = _blank_to_none(os.environ.get("AX_HOME"))
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _default_output_dir() -> Path:
    return _ax_home() / "reports" / "mf_accounting_csv"


def _default_download_dir() -> Path:
    return _ax_home() / "downloads" / "mf_accounting"


def _safe_name(value: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)
    return out or "default"


def _default_storage_state_path(session_name: str) -> Path:
    return _ax_home() / "sessions" / f"{_safe_name(session_name)}.storage.json"


def _load_playwright_sync() -> Any:
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "playwright が未導入です。以下を実行してください:\n"
            "  python -m pip install --user playwright\n"
            "  python -m playwright install chromium"
        ) from e


def _download_csv_via_playwright(
    *,
    download_url: str,
    download_dir: Path,
    timeout_seconds: int,
    session_name: str,
    storage_state_path: str | None,
    headless: bool,
    trigger_selector: str | None,
) -> dict[str, Any]:
    sync_playwright = _load_playwright_sync()
    state_path = Path(storage_state_path).expanduser() if storage_state_path else _default_storage_state_path(session_name)
    if not state_path.exists():
        raise ValueError(
            f"storage_state not found: {state_path}\n"
            "先に以下でログイン状態を保存してください:\n"
            "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 playwright login --name mf-accounting --url \"https://biz.moneyforward.com/\""
        )

    download_dir.mkdir(parents=True, exist_ok=True)
    timeout_ms = max(1, timeout_seconds) * 1000

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(state_path), accept_downloads=True)
        page = context.new_page()

        page.goto(download_url, wait_until="domcontentloaded", timeout=60_000)

        with page.expect_download(timeout=timeout_ms) as dl_info:
            if trigger_selector:
                page.locator(trigger_selector).first.click()
            else:
                # Semi-auto mode: user clicks export/download in the opened browser.
                page.wait_for_timeout(timeout_ms)

        download = dl_info.value
        suggested = _safe_name(download.suggested_filename or f"{DEFAULT_DOWNLOAD_FILE_PREFIX}.csv")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_path = download_dir / f"{stamp}_{suggested}"
        download.save_as(str(saved_path))

        final_url = page.url
        context.close()
        browser.close()

    return {
        "downloaded_csv_path": str(saved_path),
        "suggested_filename": download.suggested_filename,
        "source_page_url": final_url,
        "storage_state_path": str(state_path),
        "headless": headless,
        "trigger_selector": trigger_selector,
    }


def _parse_iso_date(value: str | None, *, name: str) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"{name} must be YYYY-MM-DD: {value!r}") from e


def _parse_flexible_date(value: str | None) -> date | None:
    raw = _blank_to_none(value)
    if raw is None:
        return None
    patterns = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y%m%d",
        "%Y年%m月%d日",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ]
    for p in patterns:
        try:
            return datetime.strptime(raw, p).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _parse_amount(value: str | None) -> Decimal | None:
    raw = _blank_to_none(value)
    if raw is None:
        return None

    s = raw.replace(",", "").replace(" ", "").replace("\u3000", "")
    s = s.replace("円", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if s.startswith("+"):
        s = s[1:]
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _decimal_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _resolve_delimiter(value: str | None, sample_text: str) -> str:
    raw = _blank_to_none(value)
    if raw is None or raw.lower() == "auto":
        try:
            sniffed = csv.Sniffer().sniff(sample_text, delimiters=[",", "\t", ";", "|"])
            return sniffed.delimiter
        except csv.Error:
            if sample_text.count("\t") > sample_text.count(","):
                return "\t"
            return ","

    low = raw.lower()
    if low in ("tab", "\\t"):
        return "\t"
    if len(raw) == 1:
        return raw
    raise ValueError(f"Unsupported delimiter: {raw!r}")


def _detect_encoding_and_delimiter(path: Path, *, encoding_pref: str | None, delimiter_pref: str | None) -> tuple[str, str]:
    pref = _blank_to_none(encoding_pref)
    candidates = []
    if pref is not None and pref.lower() != "auto":
        candidates.append(pref)
    else:
        candidates.extend(["utf-8-sig", "utf-8", "cp932", "shift_jis"])

    seen: set[str] = set()
    tried: list[str] = []
    for enc in candidates:
        if enc in seen:
            continue
        seen.add(enc)
        tried.append(enc)
        try:
            with path.open("r", encoding=enc, newline="") as f:
                sample = f.read(65_536)
            delimiter = _resolve_delimiter(delimiter_pref, sample)
            return enc, delimiter
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Unable to decode CSV with tried encodings: {tried}")


def _watch_for_new_csv(
    *,
    watch_dir: Path,
    pattern: str,
    timeout_seconds: int,
    poll_seconds: float,
    started_at: float,
) -> Path:
    if not watch_dir.exists() or not watch_dir.is_dir():
        raise ValueError(f"watch_dir not found: {watch_dir}")

    deadline = time.time() + timeout_seconds
    size_history: dict[str, int] = {}

    while time.time() <= deadline:
        files = sorted(
            [p for p in watch_dir.glob(pattern) if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for p in files:
            stat = p.stat()
            if stat.st_mtime < started_at:
                continue

            key = str(p.resolve())
            size_now = stat.st_size
            prev_size = size_history.get(key)
            size_history[key] = size_now

            if prev_size is not None and prev_size == size_now:
                return p

        time.sleep(max(0.1, poll_seconds))

    raise TimeoutError(
        f"No stable CSV detected in watch_dir within timeout: dir={watch_dir}, pattern={pattern}, timeout={timeout_seconds}s"
    )


def _build_sample_row(
    row: dict[str, Any],
    *,
    headers: list[str],
    sample_columns: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in sample_columns:
        out[c] = row.get(c)
    # Keep fallback visibility if sampled columns are all empty.
    if not any(_blank_to_none(v) is not None for v in out.values()):
        for c in headers[: min(6, len(headers))]:
            out[c] = row.get(c)
    return out


def _analyze_csv(
    *,
    csv_path: Path,
    encoding: str,
    delimiter: str,
    required_columns: list[str],
    non_empty_columns: list[str],
    key_columns: list[str],
    date_column: str | None,
    amount_columns: list[str],
    min_date: date | None,
    max_date: date | None,
    sample_rows: int,
    allow_empty_file: bool,
) -> dict[str, Any]:
    with csv_path.open("r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        raw_headers = reader.fieldnames or []
        headers = [str(h).strip() for h in raw_headers if h is not None]

        if not headers:
            raise ValueError("CSV header is empty")

        missing_required = [c for c in required_columns if c not in headers]
        missing_non_empty_headers = [c for c in non_empty_columns if c not in headers]
        missing_key_headers = [c for c in key_columns if c not in headers]

        non_empty_targets = [c for c in non_empty_columns if c in headers]
        key_targets = [c for c in key_columns if c in headers]
        date_enabled = date_column in headers if date_column else False
        amount_targets = [c for c in amount_columns if c in headers]
        missing_amount_headers = [c for c in amount_columns if c not in headers]

        non_empty_failures: dict[str, int] = {c: 0 for c in non_empty_targets}

        valid_date_count = 0
        observed_min_date: date | None = None
        observed_max_date: date | None = None
        invalid_date_examples: list[dict[str, Any]] = []
        out_of_range_date_examples: list[dict[str, Any]] = []

        amount_stats: dict[str, dict[str, Any]] = {}
        for c in amount_targets:
            amount_stats[c] = {
                "non_empty_rows": 0,
                "sum": Decimal("0"),
                "min": None,
                "max": None,
                "invalid_examples": [],
            }

        duplicate_key_count = 0
        duplicate_key_examples: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, ...]] = set()

        sample_columns = _normalize_list(
            required_columns
            + ([date_column] if date_column else [])
            + amount_columns
        )
        sample_columns = [c for c in sample_columns if c in headers]
        samples: list[dict[str, Any]] = []

        row_count = 0
        for line_no, row in enumerate(reader, start=2):
            row_count += 1

            if len(samples) < sample_rows:
                samples.append(_build_sample_row(row, headers=headers, sample_columns=sample_columns))

            for c in non_empty_targets:
                if _blank_to_none(row.get(c)) is None:
                    non_empty_failures[c] += 1

            if date_enabled and date_column is not None:
                raw_date = _blank_to_none(row.get(date_column))
                if raw_date is not None:
                    parsed = _parse_flexible_date(raw_date)
                    if parsed is None:
                        if len(invalid_date_examples) < MAX_EXAMPLE_ROWS:
                            invalid_date_examples.append({"line": line_no, "value": raw_date})
                    else:
                        valid_date_count += 1
                        if observed_min_date is None or parsed < observed_min_date:
                            observed_min_date = parsed
                        if observed_max_date is None or parsed > observed_max_date:
                            observed_max_date = parsed
                        if (min_date and parsed < min_date) or (max_date and parsed > max_date):
                            if len(out_of_range_date_examples) < MAX_EXAMPLE_ROWS:
                                out_of_range_date_examples.append({"line": line_no, "value": raw_date})

            for amount_column in amount_targets:
                raw_amount = _blank_to_none(row.get(amount_column))
                if raw_amount is None:
                    continue
                amount_stats[amount_column]["non_empty_rows"] += 1
                parsed_amount = _parse_amount(raw_amount)
                if parsed_amount is None:
                    invalid_examples = amount_stats[amount_column]["invalid_examples"]
                    if len(invalid_examples) < MAX_EXAMPLE_ROWS:
                        invalid_examples.append({"line": line_no, "value": raw_amount})
                    continue

                amount_stats[amount_column]["sum"] += parsed_amount
                prev_min = amount_stats[amount_column]["min"]
                prev_max = amount_stats[amount_column]["max"]
                if prev_min is None or parsed_amount < prev_min:
                    amount_stats[amount_column]["min"] = parsed_amount
                if prev_max is None or parsed_amount > prev_max:
                    amount_stats[amount_column]["max"] = parsed_amount

            if key_targets:
                key = tuple((_blank_to_none(row.get(c)) or "") for c in key_targets)
                if any(v != "" for v in key):
                    if key in seen_keys:
                        duplicate_key_count += 1
                        if len(duplicate_key_examples) < MAX_EXAMPLE_ROWS:
                            duplicate_key_examples.append({"line": line_no, "key": key})
                    else:
                        seen_keys.add(key)

    violations: list[str] = []
    warnings: list[str] = []

    if missing_required:
        violations.append(f"missing_required_columns: {missing_required}")
    if missing_non_empty_headers:
        violations.append(f"missing_non_empty_columns: {missing_non_empty_headers}")
    if row_count == 0 and not allow_empty_file:
        violations.append("csv_has_no_data_rows")

    for c, count in non_empty_failures.items():
        if count > 0:
            violations.append(f"non_empty_column_has_empty_values: column={c}, rows={count}")

    if invalid_date_examples:
        violations.append(f"invalid_date_values: count={len(invalid_date_examples)}")
    if out_of_range_date_examples:
        violations.append(f"date_out_of_range: count={len(out_of_range_date_examples)}")
    for amount_column in amount_targets:
        invalid_examples = amount_stats[amount_column]["invalid_examples"]
        if invalid_examples:
            violations.append(f"invalid_amount_values: column={amount_column}, count={len(invalid_examples)}")

    if missing_key_headers:
        warnings.append(f"missing_key_columns: {missing_key_headers}")
    if missing_amount_headers:
        warnings.append(f"missing_amount_columns: {missing_amount_headers}")
    if duplicate_key_count > 0:
        warnings.append(f"duplicate_keys_detected: count={duplicate_key_count}, key_columns={key_targets}")

    amount_summary: dict[str, Any] = {}
    for amount_column in amount_targets:
        st = amount_stats[amount_column]
        amount_summary[amount_column] = {
            "non_empty_rows": st["non_empty_rows"],
            "sum": _decimal_str(st["sum"]),
            "min": _decimal_str(st["min"]),
            "max": _decimal_str(st["max"]),
            "invalid_count": len(st["invalid_examples"]),
        }

    invalid_amount_examples: list[dict[str, Any]] = []
    for amount_column in amount_targets:
        for item in amount_stats[amount_column]["invalid_examples"]:
            invalid_amount_examples.append({"column": amount_column, **item})

    return {
        "csv": {
            "path": str(csv_path),
            "encoding": encoding,
            "delimiter": delimiter,
            "row_count": row_count,
            "column_count": len(headers),
            "columns": headers,
        },
        "validation": {
            "ok": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "missing_required_columns": missing_required,
            "missing_non_empty_columns": missing_non_empty_headers,
            "missing_key_columns": missing_key_headers,
            "missing_amount_columns": missing_amount_headers,
            "non_empty_failures": non_empty_failures,
            "invalid_date_examples": invalid_date_examples,
            "out_of_range_date_examples": out_of_range_date_examples,
            "invalid_amount_examples": invalid_amount_examples,
            "duplicate_key_count": duplicate_key_count,
            "duplicate_key_examples": duplicate_key_examples,
        },
        "summary": {
            "date_column": date_column,
            "valid_date_count": valid_date_count,
            "observed_min_date": observed_min_date.isoformat() if observed_min_date else None,
            "observed_max_date": observed_max_date.isoformat() if observed_max_date else None,
            "date_range_filter": {
                "min_date": min_date.isoformat() if min_date else None,
                "max_date": max_date.isoformat() if max_date else None,
            },
            "amount_columns": amount_columns,
            "amount_stats": amount_summary,
        },
        "samples": samples,
    }


def _write_normalized_utf8_csv(
    *,
    source_path: Path,
    source_encoding: str,
    source_delimiter: str,
    output_dir: Path,
) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"{source_path.stem}_{stamp}.utf8.csv"

    with source_path.open("r", encoding=source_encoding, newline="") as src, out_path.open(
        "w", encoding="utf-8", newline=""
    ) as dst:
        reader = csv.reader(src, delimiter=source_delimiter)
        writer = csv.writer(dst, delimiter=",", lineterminator="\n")
        for row in reader:
            writer.writerow(row)
    return str(out_path)


def _write_report_json(payload: dict[str, Any], *, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"mf_accounting_csv_report_{stamp}.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(report_path)


def _normalize_optional_header(value: Any) -> str | None:
    s = _blank_to_none(value)
    if s is None:
        return None
    if s.lower() in ("none", "null", "-"):
        return None
    return s


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()

    ap = argparse.ArgumentParser(description="MF Cloud Accounting CSV validator")
    ap.add_argument("--input", help="path to input JSON (otherwise stdin)")
    ap.add_argument("--mode", choices=["validate", "watch", "download"], default=None)
    ap.add_argument("--list-presets", action="store_true", help="print preset definitions and exit")
    ap.add_argument("--preset", default=None, help=f"column preset (default: {DEFAULT_PRESET_NAME})")

    ap.add_argument("--csv-path", help="target CSV path for validate mode")
    ap.add_argument("--watch-dir", help="directory to watch for newly downloaded CSV")
    ap.add_argument("--download-url", default=None, help="Money Forward page URL for manual/semi-auto CSV download")
    ap.add_argument("--download-dir", default=None, help="directory to save downloaded CSV in download mode")
    ap.add_argument("--watch-pattern", default=None, help="glob pattern for watch mode (default: *.csv)")
    ap.add_argument("--timeout-seconds", type=int, default=None, help="watch/download timeout (default: 300)")
    ap.add_argument("--poll-seconds", type=float, default=None, help="watch poll interval (default: 1.0)")
    ap.add_argument("--download-trigger-selector", default=None, help="optional selector to auto-click before waiting download")
    ap.add_argument("--session-name", default=None, help=f"Playwright session name (default: {DEFAULT_SESSION_NAME})")
    ap.add_argument("--storage-state", default=None, help="override Playwright storage_state path")
    ap.add_argument("--headless", action="store_true", default=None, help="run browser headless in download mode")
    ap.add_argument(
        "--skip-validate-after-download",
        action="store_true",
        default=None,
        help="download mode: skip CSV validation/normalization after saving file",
    )

    ap.add_argument("--encoding", default=None, help="CSV encoding (auto/utf-8/cp932/...)")
    ap.add_argument("--delimiter", default=None, help="CSV delimiter (auto/comma/tab/;)")
    ap.add_argument("--required-column", action="append", default=None, help="required header (repeatable)")
    ap.add_argument("--non-empty-column", action="append", default=None, help="non-empty check target (repeatable)")
    ap.add_argument("--key-column", action="append", default=None, help="duplicate key check target (repeatable)")
    ap.add_argument("--date-column", default=None, help=f"date column (default: {DEFAULT_DATE_COLUMN})")
    ap.add_argument("--amount-column", action="append", default=None, help="amount column (repeatable)")
    ap.add_argument("--min-date", default=None, help="min date YYYY-MM-DD")
    ap.add_argument("--max-date", default=None, help="max date YYYY-MM-DD")
    ap.add_argument("--sample-rows", type=int, default=None, help=f"sample rows in output (default: {DEFAULT_SAMPLE_ROWS})")
    ap.add_argument("--allow-empty-file", action="store_true", default=None, help="allow CSV with no data rows")

    ap.add_argument("--disable-normalize-write", action="store_true", help="disable normalized UTF-8 CSV output")
    ap.add_argument("--output-dir", default=None, help="artifact output directory")
    ap.add_argument("--no-report-write", action="store_true", help="disable report JSON output")

    ap.add_argument("--dry-run", action="store_true", default=None, help="read/plan only (default)")
    ap.add_argument("--apply", action="store_true", help="enable write/watch side effects")
    args = ap.parse_args(argv)

    raw = _read_json_input(args.input)
    config = raw.get("config") if isinstance(raw, dict) else None
    params = raw.get("params") if isinstance(raw, dict) else None
    config = config if isinstance(config, dict) else {}
    params = params if isinstance(params, dict) else {}

    csv_cfg = config.get("csv") if isinstance(config.get("csv"), dict) else {}
    paths_cfg = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    pw_cfg = config.get("playwright") if isinstance(config.get("playwright"), dict) else {}

    if args.list_presets:
        print(json.dumps({"status": "success", "data": _list_presets_payload(), "error": None}, ensure_ascii=False, indent=2))
        return 0

    dry_run_cfg = _as_bool(config.get("dry_run", True), name="dry_run")
    dry_run = dry_run_cfg if args.dry_run is None else bool(args.dry_run)
    if args.apply:
        dry_run = False

    mode = _blank_to_none(_coalesce(args.mode, params.get("mode"), config.get("mode"), DEFAULT_MODE))
    if mode not in ("validate", "watch", "download"):
        raise ValueError(f"Unsupported mode: {mode!r}")

    preset_name_raw = _blank_to_none(_coalesce(args.preset, params.get("preset"), csv_cfg.get("preset"), DEFAULT_PRESET_NAME))
    preset_name, preset = _resolve_preset(preset_name_raw)
    preset_explicit = args.preset is not None or params.get("preset") is not None

    encoding_pref = _blank_to_none(_coalesce(args.encoding, params.get("encoding"), csv_cfg.get("encoding"), "auto"))
    delimiter_pref = _blank_to_none(_coalesce(args.delimiter, params.get("delimiter"), csv_cfg.get("delimiter"), "auto"))

    preset_required = _normalize_list(preset.get("required_columns"))
    preset_non_empty = _normalize_list(preset.get("non_empty_columns"))
    preset_key_columns = _normalize_list(preset.get("key_columns"))
    preset_date_column = _normalize_optional_header(preset.get("date_column"))
    preset_amount_columns = _normalize_list(preset.get("amount_columns"))

    if preset_explicit:
        required_source = _coalesce(
            args.required_column,
            params.get("required_columns"),
            preset_required,
            csv_cfg.get("required_columns"),
            DEFAULT_REQUIRED_COLUMNS,
        )
        non_empty_source = _coalesce(
            args.non_empty_column,
            params.get("non_empty_columns"),
            preset_non_empty,
            csv_cfg.get("non_empty_columns"),
            DEFAULT_NON_EMPTY_COLUMNS,
        )
        key_source = _coalesce(
            args.key_column,
            params.get("key_columns"),
            preset_key_columns,
            csv_cfg.get("key_columns"),
            [],
        )
        date_source = _coalesce(
            args.date_column,
            params.get("date_column"),
            preset_date_column,
            csv_cfg.get("date_column"),
            DEFAULT_DATE_COLUMN,
        )
        amount_source = _coalesce(
            args.amount_column,
            params.get("amount_columns"),
            params.get("amount_column"),
            preset_amount_columns,
            csv_cfg.get("amount_columns"),
            csv_cfg.get("amount_column"),
            DEFAULT_AMOUNT_COLUMNS,
        )
    else:
        required_source = _coalesce(
            args.required_column,
            params.get("required_columns"),
            csv_cfg.get("required_columns"),
            preset_required,
            DEFAULT_REQUIRED_COLUMNS,
        )
        non_empty_source = _coalesce(
            args.non_empty_column,
            params.get("non_empty_columns"),
            csv_cfg.get("non_empty_columns"),
            preset_non_empty,
            DEFAULT_NON_EMPTY_COLUMNS,
        )
        key_source = _coalesce(
            args.key_column,
            params.get("key_columns"),
            csv_cfg.get("key_columns"),
            preset_key_columns,
            [],
        )
        date_source = _coalesce(
            args.date_column,
            params.get("date_column"),
            csv_cfg.get("date_column"),
            preset_date_column,
            DEFAULT_DATE_COLUMN,
        )
        amount_source = _coalesce(
            args.amount_column,
            params.get("amount_columns"),
            csv_cfg.get("amount_columns"),
            params.get("amount_column"),
            csv_cfg.get("amount_column"),
            preset_amount_columns,
            DEFAULT_AMOUNT_COLUMNS,
        )

    required_columns = _normalize_list(required_source)
    non_empty_columns = _normalize_list(non_empty_source)
    key_columns = _normalize_list(key_source)
    date_column = _normalize_optional_header(date_source)
    amount_columns = _normalize_list(amount_source)

    min_date = _parse_iso_date(_blank_to_none(_coalesce(args.min_date, params.get("min_date"))), name="min_date")
    max_date = _parse_iso_date(_blank_to_none(_coalesce(args.max_date, params.get("max_date"))), name="max_date")
    if min_date and max_date and min_date > max_date:
        raise ValueError("min_date must be <= max_date")

    sample_rows = _as_int(
        _coalesce(args.sample_rows, params.get("sample_rows"), DEFAULT_SAMPLE_ROWS),
        name="sample_rows",
    )
    if sample_rows < 0:
        raise ValueError("sample_rows must be >= 0")

    allow_empty_file = _as_bool(
        _coalesce(args.allow_empty_file, params.get("allow_empty_file"), False),
        name="allow_empty_file",
    )

    write_normalized_cfg = _as_bool(
        _coalesce(params.get("write_normalized"), csv_cfg.get("write_normalized"), True),
        name="write_normalized",
    )
    write_normalized = (not args.disable_normalize_write) and write_normalized_cfg

    output_dir_raw = _blank_to_none(_coalesce(args.output_dir, params.get("output_dir"), paths_cfg.get("output_dir")))
    output_dir = Path(output_dir_raw).expanduser() if output_dir_raw else _default_output_dir()

    timeout_seconds = _as_int(
        _coalesce(args.timeout_seconds, params.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS),
        name="timeout_seconds",
    )
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    poll_seconds = _as_float(
        _coalesce(args.poll_seconds, params.get("poll_seconds"), DEFAULT_POLL_SECONDS),
        name="poll_seconds",
    )
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be > 0")

    watch_pattern = _blank_to_none(_coalesce(args.watch_pattern, params.get("watch_pattern"), DEFAULT_WATCH_PATTERN))
    if watch_pattern is None:
        raise ValueError("watch_pattern is empty")

    csv_path_raw = _blank_to_none(_coalesce(args.csv_path, params.get("csv_path")))
    watch_dir_raw = _blank_to_none(_coalesce(args.watch_dir, params.get("watch_dir"), paths_cfg.get("watch_dir")))
    watch_dir = Path(watch_dir_raw).expanduser() if watch_dir_raw else (Path.home() / "Downloads")

    download_url = _blank_to_none(_coalesce(args.download_url, params.get("download_url"), paths_cfg.get("download_url")))
    download_dir_raw = _blank_to_none(_coalesce(args.download_dir, params.get("download_dir"), paths_cfg.get("download_dir")))
    download_dir = Path(download_dir_raw).expanduser() if download_dir_raw else _default_download_dir()

    session_name = _blank_to_none(_coalesce(args.session_name, params.get("session_name"), pw_cfg.get("session_name"), DEFAULT_SESSION_NAME))
    if session_name is None:
        raise ValueError("session_name is empty")
    storage_state_path = _blank_to_none(
        _coalesce(args.storage_state, params.get("storage_state_path"), pw_cfg.get("storage_state_path"))
    )
    download_trigger_selector = _blank_to_none(
        _coalesce(args.download_trigger_selector, params.get("download_trigger_selector"), pw_cfg.get("download_trigger_selector"))
    )
    headless = _as_bool(_coalesce(args.headless, params.get("headless"), pw_cfg.get("headless"), False), name="headless")
    skip_validate_after_download = _as_bool(
        _coalesce(args.skip_validate_after_download, params.get("skip_validate_after_download"), False),
        name="skip_validate_after_download",
    )

    out: dict[str, Any] = {
        "status": "success",
        "data": {
            "mode": mode,
            "dry_run": dry_run,
            "settings": {
                "preset": preset_name,
                "preset_explicit": preset_explicit,
                "preset_description": preset.get("description"),
                "preset_sources": list(preset.get("sources") or []),
                "encoding_pref": encoding_pref,
                "delimiter_pref": delimiter_pref,
                "required_columns": required_columns,
                "non_empty_columns": non_empty_columns,
                "key_columns": key_columns,
                "date_column": date_column,
                "amount_columns": amount_columns,
                "min_date": min_date.isoformat() if min_date else None,
                "max_date": max_date.isoformat() if max_date else None,
                "watch_dir": str(watch_dir),
                "download_url": download_url,
                "download_dir": str(download_dir),
                "download_trigger_selector": download_trigger_selector,
                "session_name": session_name,
                "storage_state_path": storage_state_path,
                "headless": headless,
                "skip_validate_after_download": skip_validate_after_download,
                "watch_pattern": watch_pattern,
                "timeout_seconds": timeout_seconds,
                "poll_seconds": poll_seconds,
                "output_dir": str(output_dir),
                "write_normalized": write_normalized and not dry_run,
                "write_report": (not args.no_report_write) and (not dry_run),
            },
        },
        "error": None,
    }

    if mode == "watch" and dry_run and csv_path_raw is None:
        out["data"]["planned"] = {
            "action": "watch_for_new_csv",
            "note": "dry-runのため監視待ちは実行しません。--apply で実行してください。",
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if mode == "download" and dry_run:
        out["data"]["planned"] = {
            "action": "download_csv_via_playwright",
            "note": "dry-runのためブラウザ起動とダウンロード待機は実行しません。--apply で実行してください。",
            "requires_storage_state": True,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if mode == "download":
        if not download_url:
            raise ValueError("download mode requires --download-url (or config.paths.download_url)")
        download_result = _download_csv_via_playwright(
            download_url=download_url,
            download_dir=download_dir,
            timeout_seconds=timeout_seconds,
            session_name=session_name,
            storage_state_path=storage_state_path,
            headless=headless,
            trigger_selector=download_trigger_selector,
        )
        out["data"]["download_result"] = download_result
        csv_path = Path(download_result["downloaded_csv_path"])
        if skip_validate_after_download:
            out["data"]["artifacts"] = {
                "normalized_utf8_csv_path": None,
                "report_path": None,
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
    elif csv_path_raw:
        csv_path = Path(csv_path_raw).expanduser()
    elif mode == "watch":
        started_at = time.time()
        csv_path = _watch_for_new_csv(
            watch_dir=watch_dir,
            pattern=watch_pattern,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            started_at=started_at,
        )
        out["data"]["watch_result"] = {"detected_csv_path": str(csv_path)}
    else:
        raise ValueError("csv_path is required in validate mode")

    if not csv_path.exists() or not csv_path.is_file():
        raise ValueError(f"CSV file not found: {csv_path}")

    detected_encoding, detected_delimiter = _detect_encoding_and_delimiter(
        csv_path,
        encoding_pref=encoding_pref,
        delimiter_pref=delimiter_pref,
    )

    analysis = _analyze_csv(
        csv_path=csv_path,
        encoding=detected_encoding,
        delimiter=detected_delimiter,
        required_columns=required_columns,
        non_empty_columns=non_empty_columns,
        key_columns=key_columns,
        date_column=date_column,
        amount_columns=amount_columns,
        min_date=min_date,
        max_date=max_date,
        sample_rows=sample_rows,
        allow_empty_file=allow_empty_file,
    )
    out["data"].update(analysis)

    normalized_path = None
    report_path = None

    if not dry_run and write_normalized:
        normalized_path = _write_normalized_utf8_csv(
            source_path=csv_path,
            source_encoding=detected_encoding,
            source_delimiter=detected_delimiter,
            output_dir=output_dir,
        )

    if not dry_run and not args.no_report_write:
        report_path = _write_report_json(out, output_dir=output_dir)

    out["data"]["artifacts"] = {
        "normalized_utf8_csv_path": normalized_path,
        "report_path": report_path,
    }

    valid = bool(out["data"]["validation"]["ok"])
    if not valid:
        out["status"] = "error"
        out["error"] = {
            "type": "ValidationError",
            "message": "CSV validation failed",
            "violations": out["data"]["validation"]["violations"],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001
        debug = _blank_to_none(os.environ.get("AX_DEBUG"))
        out_err: dict[str, Any] = {"status": "error", "error": {"type": type(e).__name__, "message": str(e)}}
        if debug and debug.lower() in ("1", "true", "yes", "on"):
            out_err["error"]["traceback"] = traceback.format_exc()
        print(json.dumps(out_err, ensure_ascii=False, indent=2), file=sys.stdout)
        raise SystemExit(1)
