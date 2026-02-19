from __future__ import annotations

import argparse
from pathlib import Path
import importlib.util
import os

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("kintone_thread_comment_cleanup_run", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coalesce_prefers_first_non_none() -> None:
    run = _load_module()
    assert run._coalesce(None, "", "x") == ""
    assert run._coalesce(None, 0, "x") == 0
    assert run._coalesce(None, None, "x") == "x"
    assert run._coalesce(None, None) is None


def test_blank_to_none() -> None:
    run = _load_module()
    assert run._blank_to_none(None) is None
    assert run._blank_to_none("   ") is None
    assert run._blank_to_none(123) == "123"
    assert run._blank_to_none("a") == "a"


def test_as_int_and_bool_parsers() -> None:
    run = _load_module()
    assert run._as_int("12", name="n") == 12
    assert run._as_int(12, name="n") == 12
    assert run._as_bool(True, name="flag") is True
    assert run._as_bool("true", name="flag") is True
    assert run._as_bool("off", name="flag") is False
    assert run._as_bool(0, name="flag") is False
    with pytest.raises(ValueError, match="Missing required integer: n"):
        run._as_int(None, name="n")
    with pytest.raises(ValueError, match="Invalid integer for n"):
        run._as_int("abc", name="n")
    with pytest.raises(ValueError, match="Invalid boolean"):
        run._as_bool("maybe", name="flag")


def test_extract_comment_id_and_select_targets() -> None:
    run = _load_module()
    assert run._extract_comment_id("ocean-ui-comments-post-id-123 abc") == "123"
    assert run._extract_comment_id("no-id") is None

    comments = [
        {"comment_id": "1", "text": "hello"},
        {"comment_id": "2", "text": "target keyword"},
        {"comment_id": "3", "text": "target keyword"},
    ]
    selected = run._select_targets(
        comments=comments,
        comment_ids=["2", "9"],
        match_texts=["keyword"],
        max_delete=2,
    )
    assert len(selected) == 2
    assert {"comment_id": "2", "text": "target keyword"} in selected
    assert {"comment_id": "9", "missing": True} in selected


def test_parse_thread_uses_args_and_defaults() -> None:
    run = _load_module()
    args = argparse.Namespace(
        subdomain=None,
        space_id=None,
        thread_id=None,
    )
    thread = run._parse_thread({"kintone": {"subdomain": "custom", "space_id": 10, "thread_id": 20}}, args)
    assert thread.subdomain == "custom"
    assert thread.space_id == 10
    assert thread.thread_id == 20


def test_parse_auth_with_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _load_module()
    monkeypatch.setenv("KINTONE_USERNAME", "user")
    monkeypatch.setenv("KINTONE_PASSWORD", "pass")
    args = argparse.Namespace(
        username=None,
        password=None,
        storage_state=None,
    )
    auth = run._parse_auth({}, args)
    assert auth.username == "user"
    assert auth.password == "pass"
    assert auth.storage_state_path is None


def test_is_sandbox_thread() -> None:
    run = _load_module()
    sandbox = run.KintoneThread(subdomain="5atx9", space_id=81, thread_id=131)
    assert run._is_sandbox_thread(sandbox)
