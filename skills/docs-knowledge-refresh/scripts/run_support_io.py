#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from .run_support_converters import _blank_to_none, _coalesce
except Exception:  # pragma: no cover - direct script execution fallback
    from run_support_converters import _blank_to_none, _coalesce  # type: ignore


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


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


def _candidate_paths(raw: Path) -> list[Path]:
    raw = raw.expanduser()
    paths: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path) -> None:
        p = p.expanduser()
        if p not in seen:
            paths.append(p)
            seen.add(p)

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent.parent

    _add(raw)
    if not raw.is_absolute():
        _add(Path.cwd() / raw)
        _add(script_dir / raw)
        _add(script_dir.parent / raw)
        _add(script_dir.parent.parent / raw)
        _add(repo_root / raw)
        if raw.anchor == "" and ( ".." in raw.parts or "." in raw.parts):
            _add((Path.cwd() / raw).resolve())

    return paths


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


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
        target = _candidate_existing_path(raw)
        if target is None:
            missing.append(str(Path(raw).expanduser()))
            continue
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


def _candidate_existing_path(raw: str) -> Path | None:
    candidates = _candidate_paths(Path(raw))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_text(path: Path) -> tuple[str, str]:
    try:
        return path.read_text(encoding="utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        return path.read_text(encoding="cp932", errors="replace"), "cp932"


def _normalize_encoding(encoding: str) -> str:
    return encoding.split("(")[0]


def _write_text(path: Path, text: str, encoding: str) -> None:
    path.write_text(text, encoding=_normalize_encoding(encoding))


def _rel_posix(path: Path, base: Path) -> str:
    try:
        rel = path.resolve().relative_to(base.resolve())
        return rel.as_posix()
    except Exception:
        return path.as_posix()


def _load_registry(path: str | None) -> dict[str, Any]:
    if not path:
        return {"defaults": {}, "rules": []}
    path_candidates = _candidate_paths(Path(path))
    p: Path | None = None
    for candidate in path_candidates:
        if candidate.exists():
            p = candidate
            break
    if p is None:
        raise FileNotFoundError(f"Registry not found: {path}. Checked: {', '.join(str(c) for c in path_candidates)}")
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
    bootstrap_items: list[dict[str, Any]] | None = None,
) -> str:
    bootstrap_items = bootstrap_items or []
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
    lines.append(f"- bootstrap_updates: `{len(bootstrap_items)}`")
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
    lines.append("## Bootstrap Updates")
    lines.append("")
    if not bootstrap_items:
        lines.append("- none")
    else:
        for item in bootstrap_items:
            age = item.get("age_days")
            date = item.get("review_date")
            reasons = ",".join(item.get("reasons") or [])
            lines.append(
                f"- [ ] `{item['path']}` (added={date}, age={age}, reasons={reasons}, source={item.get('review_source')})"
            )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "_ensure_utf8_stdout",
    "_read_json_input",
    "_ax_home",
    "_normalize_ext",
    "_discover_files",
    "_load_text",
    "_rel_posix",
    "_load_registry",
    "_select_rule",
    "_build_report_markdown",
    "_write_text",
]
