#!/usr/bin/env python3
"""
Periodic knowledge freshness audit for markdown documents.

Standard JSON interface:
Input (stdin or --input):
{
  "config": {
    "dry_run": true,
    "targets": {
      "paths": ["docs"],
      "extensions": [".md"],
      "exclude_dirs": [".git", "output", "node_modules", "__pycache__"]
    },
    "policy": {
      "default_max_age_days": 30,
      "warn_within_days": 7
    },
    "registry": {
      "path": "docs/knowledge_refresh_registry.json"
    },
    "report": {
      "write_markdown": false,
      "output_dir": null
    }
  },
  "params": {
    "scan_paths": ["docs"],
    "max_age_days": 30,
    "warn_within_days": 7,
    "fail_on_stale": false
  }
}
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


REVIEW_KEY_CANDIDATES = {
    "last_verified",
    "last_reviewed",
    "reviewed_at",
    "last_checked",
    "updated_at",
    "最終確認日",
    "最終更新日",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL)
DATE_TOKEN_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
URL_RE = re.compile(r"https?://[^\s<>()\"']+")

BODY_DATE_PATTERNS = [
    re.compile(r"^\s*最終確認日\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE),
    re.compile(r"^\s*最終更新日\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE),
    re.compile(r"^\s*Last\s+Verified\s*:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Last\s+Reviewed\s*:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE | re.IGNORECASE),
]


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _read_json_input(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            raise ValueError("Input JSON must be an object")

    if sys.stdin and not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        raise ValueError("Input JSON must be an object")

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


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _as_int(value: Any, *, name: str, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid integer for {name}: {value!r}") from e


def _as_string_list(value: Any, *, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else list(default)
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out or list(default)
    return list(default)


def _parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    s = str(value).strip().strip("'\"")
    if not s:
        return None
    m = DATE_TOKEN_RE.search(s)
    if not m:
        return None
    token = m.group(1)
    try:
        return dt.date.fromisoformat(token)
    except ValueError:
        return None


def _extract_frontmatter_date(text: str) -> tuple[dt.date | None, str | None]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, None
    frontmatter = m.group(1)
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = key.strip().lower()
        if normalized in REVIEW_KEY_CANDIDATES:
            d = _parse_date(value)
            if d:
                return d, key.strip()
    return None, None


def _extract_body_date(text: str) -> tuple[dt.date | None, str | None]:
    for pat in BODY_DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        d = _parse_date(m.group(1))
        if d:
            return d, "body_marker"
    return None, None


def _extract_review_date(text: str) -> tuple[dt.date | None, str | None]:
    d, src = _extract_frontmatter_date(text)
    if d:
        return d, src
    return _extract_body_date(text)


def _load_text(path: Path) -> tuple[str, str]:
    try:
        return path.read_text(encoding="utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        return path.read_text(encoding="cp932", errors="replace"), "cp932(replace)"


def _normalize_ext(ext: str) -> str:
    e = ext.strip().lower()
    if not e:
        return ""
    if not e.startswith("."):
        e = "." + e
    return e


def _discover_files(
    scan_paths: list[str],
    extensions: list[str],
    exclude_dirs: list[str],
) -> tuple[list[Path], list[str]]:
    exts = {_normalize_ext(e) for e in extensions if _normalize_ext(e)}
    exclude = {d.strip().lower() for d in exclude_dirs if d.strip()}
    found: dict[str, Path] = {}
    missing: list[str] = []

    for raw in scan_paths:
        target = Path(raw).expanduser()
        if not target.exists():
            missing.append(str(target))
            continue

        if target.is_file():
            suffix = target.suffix.lower()
            if suffix in exts:
                found[str(target.resolve())] = target
            continue

        for item in target.rglob("*"):
            if not item.is_file():
                continue
            if item.suffix.lower() not in exts:
                continue
            parts_lower = {p.lower() for p in item.parts}
            if parts_lower & exclude:
                continue
            found[str(item.resolve())] = item

    files = sorted(found.values(), key=lambda p: str(p).replace("\\", "/"))
    return files, missing


def _rel_posix(path: Path, base: Path) -> str:
    try:
        rel = path.resolve().relative_to(base.resolve())
        return rel.as_posix()
    except Exception:
        return path.as_posix()


def _load_registry(path: str | None) -> dict[str, Any]:
    if not path:
        return {"defaults": {}, "rules": []}
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Registry not found: {p}")
    with p.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("registry must be a JSON object")
    defaults = data.get("defaults")
    rules = data.get("rules")
    if defaults is None:
        defaults = {}
    if rules is None:
        rules = []
    if not isinstance(defaults, dict):
        raise ValueError("registry.defaults must be an object")
    if not isinstance(rules, list):
        raise ValueError("registry.rules must be an array")
    normalized_rules: list[dict[str, Any]] = []
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"registry.rules[{idx}] must be an object")
        pattern = _blank_to_none(_coalesce(rule.get("pattern"), rule.get("glob"), rule.get("path")))
        if not pattern:
            raise ValueError(f"registry.rules[{idx}] missing pattern/glob/path")
        normalized_rules.append(
            {
                "pattern": pattern.replace("\\", "/"),
                "max_age_days": rule.get("max_age_days"),
                "warn_within_days": rule.get("warn_within_days"),
                "require_source_urls": rule.get("require_source_urls"),
                "owner": _blank_to_none(rule.get("owner")),
            }
        )
    return {"defaults": defaults, "rules": normalized_rules, "path": str(p)}


def _select_rule(rel_path: str, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rule in rules:
        if fnmatch.fnmatch(rel_path, rule["pattern"]):
            return rule
    return None


def _build_report_markdown(
    *,
    generated_at: str,
    as_of: str,
    scan_paths: list[str],
    summary: dict[str, Any],
    stale_items: list[dict[str, Any]],
    warning_items: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append("# Knowledge Refresh Report")
    lines.append("")
    lines.append(f"- generated_at: `{generated_at}`")
    lines.append(f"- as_of: `{as_of}`")
    lines.append(f"- scan_paths: `{', '.join(scan_paths)}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- scanned: `{summary['scanned']}`")
    lines.append(f"- stale: `{summary['stale']}`")
    lines.append(f"- warning: `{summary['warning']}`")
    lines.append(f"- fresh: `{summary['fresh']}`")
    lines.append("")
    lines.append("## Stale Items")
    lines.append("")
    if not stale_items:
        lines.append("- none")
    else:
        for item in stale_items:
            age = item.get("age_days")
            max_age = item.get("max_age_days")
            lines.append(
                f"- [ ] `{item['path']}` (last={item.get('review_date')}, age={age}, max={max_age}, reasons={','.join(item.get('reasons') or [])})"
            )
    lines.append("")
    lines.append("## Warning Items")
    lines.append("")
    if not warning_items:
        lines.append("- none")
    else:
        for item in warning_items:
            age = item.get("age_days")
            max_age = item.get("max_age_days")
            lines.append(
                f"- [ ] `{item['path']}` (last={item.get('review_date')}, age={age}, max={max_age}, reasons={','.join(item.get('reasons') or [])})"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    _ensure_utf8_stdout()

    ap = argparse.ArgumentParser(description="knowledge freshness audit for markdown docs")
    ap.add_argument("--input", help="path to JSON input")
    ap.add_argument("--scan", action="append", help="scan path (repeatable)")
    ap.add_argument("--extension", action="append", help="file extension to include (default: .md)")
    ap.add_argument("--exclude-dir", action="append", help="directory names to exclude")
    ap.add_argument("--registry", help="policy registry JSON path")
    ap.add_argument("--max-age-days", type=int, help="default stale threshold")
    ap.add_argument("--warn-within-days", type=int, help="warning window before stale")
    ap.add_argument("--as-of", help="evaluation date (YYYY-MM-DD, default: today)")
    ap.add_argument("--fail-on-stale", action="store_true", help="exit non-zero when stale files exist")
    ap.add_argument("--write-report", action="store_true", help="write markdown report (requires --apply)")
    ap.add_argument("--report-dir", help="report output directory")
    ap.add_argument("--dry-run", action="store_true", default=None, help="do not write files (default)")
    ap.add_argument("--apply", action="store_true", help="allow file outputs (report write)")
    args = ap.parse_args()

    out: dict[str, Any] = {"status": "ok", "data": {}, "error": None}

    try:
        payload = _read_json_input(args.input)
        config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

        targets_cfg = config.get("targets") if isinstance(config.get("targets"), dict) else {}
        policy_cfg = config.get("policy") if isinstance(config.get("policy"), dict) else {}
        report_cfg = config.get("report") if isinstance(config.get("report"), dict) else {}
        registry_cfg = config.get("registry") if isinstance(config.get("registry"), dict) else {}

        scan_paths = (
            args.scan
            if args.scan
            else _as_string_list(
                _coalesce(params.get("scan_paths"), targets_cfg.get("paths")),
                default=["docs"],
            )
        )
        extensions = (
            args.extension
            if args.extension
            else _as_string_list(
                _coalesce(params.get("extensions"), targets_cfg.get("extensions")),
                default=[".md"],
            )
        )
        exclude_dirs = (
            args.exclude_dir
            if args.exclude_dir
            else _as_string_list(
                _coalesce(params.get("exclude_dirs"), targets_cfg.get("exclude_dirs")),
                default=[".git", "output", "node_modules", "__pycache__"],
            )
        )

        max_age_days = _as_int(
            _coalesce(args.max_age_days, params.get("max_age_days"), policy_cfg.get("default_max_age_days")),
            name="max_age_days",
            default=30,
        )
        warn_within_days = _as_int(
            _coalesce(args.warn_within_days, params.get("warn_within_days"), policy_cfg.get("warn_within_days")),
            name="warn_within_days",
            default=7,
        )
        if max_age_days <= 0:
            raise ValueError("max_age_days must be > 0")
        if warn_within_days < 0:
            raise ValueError("warn_within_days must be >= 0")

        as_of_raw = _blank_to_none(_coalesce(args.as_of, params.get("as_of"), policy_cfg.get("as_of")))
        as_of = dt.date.fromisoformat(as_of_raw) if as_of_raw else dt.date.today()

        dry_run = True
        if args.apply:
            dry_run = False
        elif args.dry_run:
            dry_run = True
        else:
            dry_run = _as_bool(_coalesce(config.get("dry_run"), params.get("dry_run")), default=True)

        fail_on_stale = _as_bool(_coalesce(args.fail_on_stale, params.get("fail_on_stale"), policy_cfg.get("fail_on_stale")), default=False)
        write_report_requested = _as_bool(_coalesce(args.write_report, params.get("write_report"), report_cfg.get("write_markdown")), default=False)
        write_report = bool(write_report_requested and not dry_run)

        report_dir_raw = _blank_to_none(_coalesce(args.report_dir, params.get("report_dir"), report_cfg.get("output_dir")))
        report_dir = Path(report_dir_raw).expanduser() if report_dir_raw else (_ax_home() / "reports" / "knowledge_refresh")

        registry_path = _blank_to_none(_coalesce(args.registry, params.get("registry_path"), registry_cfg.get("path")))
        registry = _load_registry(registry_path)
        reg_defaults = registry.get("defaults") if isinstance(registry.get("defaults"), dict) else {}
        reg_rules = registry.get("rules") if isinstance(registry.get("rules"), list) else []

        files, missing_paths = _discover_files(scan_paths=scan_paths, extensions=extensions, exclude_dirs=exclude_dirs)
        cwd = Path.cwd()

        items: list[dict[str, Any]] = []
        stale_items: list[dict[str, Any]] = []
        warning_items: list[dict[str, Any]] = []
        fresh_items: list[dict[str, Any]] = []

        default_max_age = _as_int(reg_defaults.get("max_age_days"), name="registry.defaults.max_age_days", default=max_age_days)
        default_warn = _as_int(reg_defaults.get("warn_within_days"), name="registry.defaults.warn_within_days", default=warn_within_days)
        default_require_sources = _as_bool(reg_defaults.get("require_source_urls"), default=False)

        for file_path in files:
            rel_path = _rel_posix(file_path, cwd)
            text, encoding_used = _load_text(file_path)
            review_date, review_source = _extract_review_date(text)
            source_urls = sorted(set(URL_RE.findall(text)))

            matched_rule = _select_rule(rel_path, reg_rules)
            eff_max_age = default_max_age
            eff_warn = default_warn
            eff_owner = None
            eff_require_sources = default_require_sources
            matched_pattern = None

            if matched_rule:
                matched_pattern = matched_rule.get("pattern")
                eff_max_age = _as_int(matched_rule.get("max_age_days"), name=f"rule({matched_pattern}).max_age_days", default=eff_max_age)
                eff_warn = _as_int(matched_rule.get("warn_within_days"), name=f"rule({matched_pattern}).warn_within_days", default=eff_warn)
                eff_owner = _blank_to_none(matched_rule.get("owner"))
                eff_require_sources = _as_bool(matched_rule.get("require_source_urls"), default=eff_require_sources)

            if eff_max_age <= 0:
                raise ValueError(f"Invalid max_age_days for {rel_path}: {eff_max_age}")
            if eff_warn < 0:
                raise ValueError(f"Invalid warn_within_days for {rel_path}: {eff_warn}")

            state = "fresh"
            reasons: list[str] = []
            age_days: int | None = None
            review_date_str: str | None = None

            if review_date is None:
                state = "stale"
                reasons.append("review_date_missing")
            else:
                review_date_str = review_date.isoformat()
                age_days = (as_of - review_date).days
                if age_days < 0:
                    state = "warning"
                    reasons.append("review_date_in_future")
                elif age_days > eff_max_age:
                    state = "stale"
                    reasons.append("age_over_limit")
                else:
                    warn_start = max(0, eff_max_age - eff_warn)
                    if age_days >= warn_start:
                        state = "warning"
                        reasons.append("due_soon")

            if eff_require_sources and len(source_urls) == 0:
                state = "stale"
                reasons.append("source_url_missing")

            item = {
                "path": rel_path,
                "review_date": review_date_str,
                "review_source": review_source,
                "age_days": age_days,
                "max_age_days": eff_max_age,
                "warn_within_days": eff_warn,
                "require_source_urls": eff_require_sources,
                "source_url_count": len(source_urls),
                "owner": eff_owner,
                "matched_rule": matched_pattern,
                "state": state,
                "reasons": reasons,
                "encoding_used": encoding_used,
            }
            items.append(item)

            if state == "stale":
                stale_items.append(item)
            elif state == "warning":
                warning_items.append(item)
            else:
                fresh_items.append(item)

        generated_at = _now_utc_iso()
        report_path: str | None = None
        if write_report:
            report_dir.mkdir(parents=True, exist_ok=True)
            filename = f"knowledge_refresh_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            path = report_dir / filename
            summary_for_report = {
                "scanned": len(items),
                "stale": len(stale_items),
                "warning": len(warning_items),
                "fresh": len(fresh_items),
            }
            report_md = _build_report_markdown(
                generated_at=generated_at,
                as_of=as_of.isoformat(),
                scan_paths=scan_paths,
                summary=summary_for_report,
                stale_items=stale_items,
                warning_items=warning_items,
            )
            path.write_text(report_md, encoding="utf-8", newline="\n")
            report_path = str(path)

        summary = {
            "scanned": len(items),
            "stale": len(stale_items),
            "warning": len(warning_items),
            "fresh": len(fresh_items),
            "missing_scan_paths": len(missing_paths),
        }

        out["data"] = {
            "generated_at": generated_at,
            "as_of": as_of.isoformat(),
            "planned": {
                "dry_run": dry_run,
                "scan_paths": scan_paths,
                "extensions": extensions,
                "exclude_dirs": exclude_dirs,
                "max_age_days": max_age_days,
                "warn_within_days": warn_within_days,
                "fail_on_stale": fail_on_stale,
                "write_report_requested": write_report_requested,
                "write_report": write_report,
                "registry_path": registry.get("path"),
            },
            "summary": summary,
            "missing_scan_paths": missing_paths,
            "items": items,
            "stale_items": stale_items,
            "warning_items": warning_items,
            "report": {
                "path": report_path,
                "written": bool(report_path),
                "report_dir": str(report_dir),
            },
        }

        if fail_on_stale and len(stale_items) > 0:
            out["status"] = "error"
            out["error"] = {"message": f"stale documents found: {len(stale_items)}"}
            print(json.dumps(out, ensure_ascii=False))
            return 1

        print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception as e:
        out["status"] = "error"
        out["error"] = {"message": str(e)}
        print(json.dumps(out, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
