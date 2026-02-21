from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
SPEC = importlib.util.spec_from_file_location("playwright_run", MODULE_PATH)
assert SPEC and SPEC.loader
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


def test_has_session_arg_detects_both_forms() -> None:
    assert RUN._has_session_arg(["open", "--session", "abc"])
    assert RUN._has_session_arg(["open", "--session=abc"])
    assert not RUN._has_session_arg(["open", "--headed"])


def test_resolve_timeout_clamps_min_and_max() -> None:
    assert RUN._resolve_timeout(None) == RUN.DEFAULT_TIMEOUT_SECONDS
    assert RUN._resolve_timeout(1) == RUN.MIN_TIMEOUT_SECONDS
    assert RUN._resolve_timeout(999999) == RUN.MAX_TIMEOUT_SECONDS


def test_normalize_cli_args_drops_double_dash_prefix() -> None:
    assert RUN._normalize_cli_args(["--", "open", "http://localhost"]) == ["open", "http://localhost"]
    assert RUN._normalize_cli_args(["snapshot"]) == ["snapshot"]
