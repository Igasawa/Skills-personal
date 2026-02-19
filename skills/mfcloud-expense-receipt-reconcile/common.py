from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

SUPPORTED_DASHBOARD_UI_LOCALES = {"ja", "en"}


def ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def artifact_root() -> Path:
    return ax_home() / "artifacts" / "mfcloud-expense-receipt-reconcile"


def runs_root() -> Path:
    return artifact_root() / "_runs"


def ym_default(now: date | None = None) -> tuple[int, int]:
    d = now or date.today()
    if d.month == 1:
        return d.year - 1, 12
    return d.year, d.month - 1


def dashboard_ui_locale() -> str:
    raw = str(os.environ.get("DASHBOARD_UI_LOCALE") or "").strip().lower()
    if raw in SUPPORTED_DASHBOARD_UI_LOCALES:
        return raw
    if raw.startswith("ja"):
        return "ja"
    if raw.startswith("en"):
        return "en"
    return "ja"


def ym_to_dirname(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def parse_csv_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value).split(",") if s.strip()]


def as_int(value: Any, *, name: str) -> int:
    if value is None:
        raise ValueError(f"Missing required integer: {name}")
    try:
        return int(value)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid integer for {name}: {value!r}") from e


def safe_non_negative_int(value: Any, *, default: int = 0) -> int:
    try:
        n = int(value)
    except Exception:
        return default
    return n if n >= 0 else default


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_storage_state(name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in name)
    return ax_home() / "sessions" / f"{safe}.storage.json"


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return None


def read_jsonl(path: Path, *, required: bool = False, strict: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"JSONL not found: {path}")
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for i, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception as e:
                if strict:
                    raise ValueError(f"Invalid JSON on {path}:{i}") from e
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def load_order_exclusions(path: Path | str | None) -> set[tuple[str, str]]:
    if path is None:
        return set()
    p = path if isinstance(path, Path) else Path(path)
    data = read_json(p)
    if not isinstance(data, dict):
        return set()
    items = data.get("exclude")
    if not isinstance(items, list):
        return set()
    out: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        order_id = str(item.get("order_id") or "").strip()
        if not source or not order_id:
            continue
        out.add((source, order_id))
    return out


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
