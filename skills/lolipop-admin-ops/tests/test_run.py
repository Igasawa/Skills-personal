from __future__ import annotations

from pathlib import Path
import argparse
import importlib.util

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("lolipop_admin_ops_run", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sanitize_domain_and_paths() -> None:
    run = _load_module()
    assert run._sanitize_domain("example.com") == "example.com"
    assert run._sanitize_domain(" sub.example.com ") == "sub.example.com"
    with pytest.raises(ValueError, match="domain is required"):
        run._sanitize_domain("   ")
    with pytest.raises(ValueError, match="invalid domain format"):
        run._sanitize_domain("invalid-domain")

    assert run._safe_path("abc/def") == "abc_def"
    assert run._safe_path("a b_c-1.2") == "a_b_c-1.2"


def test_normalize_url_variants() -> None:
    run = _load_module()
    assert run._normalize_url("https://secure.lolipop.jp", "path/to") == "https://secure.lolipop.jp/path/to"
    assert run._normalize_url("https://secure.lolipop.jp", "/path/to") == "https://secure.lolipop.jp/path/to"
    assert run._normalize_url("https://secure.lolipop.jp", "https://other.example.com") == "https://other.example.com"


def test_is_production() -> None:
    run = _load_module()
    assert run._is_production(None) is True
    assert run._is_production("production") is True
    assert run._is_production("staging") is False


def test_load_playbook_variants_and_errors() -> None:
    run = _load_module()
    assert run._load_playbook([{"type": "goto"}])["steps"] == [{"type": "goto"}]
    with pytest.raises(ValueError, match="playbook must be an object or a step array"):
        run._load_playbook("not-playbook")

    with pytest.raises(ValueError, match="playbook.steps is required"):
        run._load_playbook({})


def test_normalize_step_validation() -> None:
    run = _load_module()
    normalized = run._normalize_step({"type": "click", "selector": "#id", "timeout": "5000", "delay_ms": "200"}, index=1)
    assert normalized["type"] == "click"
    assert normalized["selector"] == "#id"
    assert normalized["timeout"] == 5000
    assert normalized["delay_ms"] == 200
    assert normalized["state"] == "visible"

    with pytest.raises(ValueError, match="step\\[1\\] unsupported type"):
        run._normalize_step({"type": "unsupported"}, index=1)


def test_read_playbook_from_path(tmp_path: Path) -> None:
    run = _load_module()
    playbook_path = tmp_path / "playbook.json"
    playbook_path.write_text('{"name":"x","steps":[]}', encoding="utf-8")
    assert run._read_playbook_from_path(str(playbook_path)) == {"name": "x", "steps": []}

    with pytest.raises(FileNotFoundError):
        run._read_playbook_from_path(str(tmp_path / "missing.json"))


def test_default_session_state_path(tmp_path: Path, monkeypatch) -> None:
    run = _load_module()
    monkeypatch.setenv("AX_HOME", str(tmp_path / "axhome"))
    path = run._default_session_state_path("my-session")
    assert str(path).endswith("axhome/sessions/my-session.storage.json")


def test_blank_and_coalesce_helpers() -> None:
    run = _load_module()
    assert run._blank_to_none("  abc ") == "abc"
    assert run._blank_to_none("   ") is None
    assert run._coalesce(None, None, 5) == 5
    assert run._coalesce(None, None) is None
