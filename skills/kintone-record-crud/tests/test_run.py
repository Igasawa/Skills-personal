from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("kintone_record_crud_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blank_to_none() -> None:
    run = _load_module(SCRIPT_PATH)
    assert run._blank_to_none(None) is None
    assert run._blank_to_none("  ") is None
    assert run._blank_to_none("value") == "value"
    assert run._blank_to_none(0) == "0"


def test_to_kintone_record_wraps_values() -> None:
    run = _load_module(SCRIPT_PATH)
    assert run._to_kintone_record({"a": 1, "b": "text"}) == {
        "a": {"value": 1},
        "b": {"value": "text"},
    }


def test_load_record_arg_from_json() -> None:
    run = _load_module(SCRIPT_PATH)
    assert run._load_record_arg(record_json='{"a": 1}', record_file=None) == {"a": 1}


def test_load_record_arg_from_file(tmp_path: Path) -> None:
    run = _load_module(SCRIPT_PATH)
    record_file = tmp_path / "record.json"
    record_file.write_text(json.dumps({"k": "v"}, ensure_ascii=False), encoding="utf-8-sig")
    assert run._load_record_arg(record_json=None, record_file=str(record_file)) == {"k": "v"}


def test_load_record_arg_conflict() -> None:
    run = _load_module(SCRIPT_PATH)
    try:
        run._load_record_arg(record_json='{"a":1}', record_file="x.json")
    except ValueError as e:
        assert "Use either --record or --record-file" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_load_record_arg_requires_one_source() -> None:
    run = _load_module(SCRIPT_PATH)
    try:
        run._load_record_arg(record_json=None, record_file=None)
    except ValueError as e:
        assert "Missing --record or --record-file" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_load_record_arg_reject_non_object() -> None:
    run = _load_module(SCRIPT_PATH)
    try:
        run._load_record_arg(record_json='["a"]', record_file=None)
    except ValueError as e:
        assert "record must be a JSON object" in str(e)
    else:
        raise AssertionError("expected ValueError")
