from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import os

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blank_to_none() -> None:
    run = _load_module(SCRIPT_PATH, "kintone_inventory_export_run")
    assert run._blank_to_none(None) is None
    assert run._blank_to_none("  ") is None
    assert run._blank_to_none("value") == "value"
    assert run._blank_to_none(0) == "0"


def test_ax_home_prefers_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = _load_module(SCRIPT_PATH, "kintone_inventory_export_run_home")
    monkeypatch.setenv("AX_HOME", str(tmp_path / "custom-ax-home"))
    assert run._ax_home() == Path(os.environ["AX_HOME"]).expanduser()


def test_default_storage_state_path() -> None:
    run = _load_module(SCRIPT_PATH, "kintone_inventory_export_run_storage")
    assert run._default_storage_state_path("abc-def").name == "abc-def.storage.json"
    assert run._default_storage_state_path("a b/c").name == "a_b_c.storage.json"


def test_host_matches() -> None:
    run = _load_module(SCRIPT_PATH, "kintone_inventory_export_run_host")
    assert run._host_matches("example.com", "example.com") is True
    assert run._host_matches(".example.com", "sub.example.com") is True
    assert run._host_matches("EXAMPLE.com", "api.example.com") is True
    assert run._host_matches("other.com", "api.example.com") is False


def test_parse_kintone_datetime() -> None:
    run = _load_module(SCRIPT_PATH, "kintone_inventory_export_run_datetime")
    assert run._parse_kintone_datetime(None) is None
    assert run._parse_kintone_datetime("  ") is None

    d = run._parse_kintone_datetime("2026-02-10T01:23:45.000Z")
    assert isinstance(d, datetime)
    assert d.tzinfo is not None and d.tzinfo.utcoffset(d) == timezone.utc.utcoffset(d)

    d2 = run._parse_kintone_datetime("2026-02-10T10:23:45+0900")
    assert isinstance(d2, datetime)
    assert str(d2.tzinfo) in {"+09:00", "UTC+09:00"}

    assert run._parse_kintone_datetime("not-a-date") is None


def test_record_helpers() -> None:
    run = _load_module(SCRIPT_PATH, "kintone_inventory_export_run_record")
    assert run._extract_record_id({"$id": {"value": 12}}) == "12"
    assert run._extract_record_id({"$id": {"value": "A-01"}}) == "A-01"
    assert run._extract_record_id({}) is None

    record = {"Updated_datetime": {"value": "2026-02-10T10:23:45+09:00"}}
    dt_val = run._extract_record_time(record, "Updated_datetime")
    assert isinstance(dt_val, datetime)
    assert str(dt_val.tzinfo) in {"+09:00", "UTC+09:00"}
