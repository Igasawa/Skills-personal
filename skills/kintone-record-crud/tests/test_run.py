from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("kintone_record_crud_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_module_loads_without_axkit_dependency() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "axkit" not in text
    run = _load_module(SCRIPT_PATH)
    assert hasattr(run, "main")


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
    with pytest.raises(ValueError, match="Use either --record or --record-file"):
        run._load_record_arg(record_json='{"a":1}', record_file="x.json")


def test_load_record_arg_requires_one_source() -> None:
    run = _load_module(SCRIPT_PATH)
    with pytest.raises(ValueError, match="Missing --record or --record-file"):
        run._load_record_arg(record_json=None, record_file=None)


def test_load_record_arg_reject_non_object() -> None:
    run = _load_module(SCRIPT_PATH)
    with pytest.raises(ValueError, match="record must be a JSON object"):
        run._load_record_arg(record_json='["a"]', record_file=None)


def test_default_storage_state_path_sanitizes_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = _load_module(SCRIPT_PATH)
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    path = run._default_storage_state_path("ki nt/one")
    assert str(path).replace("\\", "/").endswith("/sessions/ki_nt_one.storage.json")


def test_auth_headers_from_env_password(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _load_module(SCRIPT_PATH)
    monkeypatch.setenv("KINTONE_USERNAME", "user")
    monkeypatch.setenv("KINTONE_PASSWORD", "pass")
    monkeypatch.setenv("KINTONE_API_TOKEN", "token")

    row = run._auth_headers_from_env()
    assert row is not None
    headers, mode = row
    assert mode == "password"
    assert "X-Cybozu-Authorization" in headers
    assert headers.get("X-Cybozu-API-Token") == "token"


def test_auth_headers_from_env_token_only(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _load_module(SCRIPT_PATH)
    monkeypatch.delenv("KINTONE_USERNAME", raising=False)
    monkeypatch.delenv("KINTONE_PASSWORD", raising=False)
    monkeypatch.setenv("KINTONE_API_TOKEN", "token")

    row = run._auth_headers_from_env()
    assert row is not None
    headers, mode = row
    assert mode == "api_token"
    assert headers.get("X-Cybozu-API-Token") == "token"
    assert "X-Cybozu-Authorization" not in headers


def test_auth_headers_from_env_none(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _load_module(SCRIPT_PATH)
    monkeypatch.delenv("KINTONE_USERNAME", raising=False)
    monkeypatch.delenv("KINTONE_PASSWORD", raising=False)
    monkeypatch.delenv("KINTONE_API_TOKEN", raising=False)
    assert run._auth_headers_from_env() is None
