from __future__ import annotations

from pathlib import Path
import importlib.util

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("kintone_gas_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_utility_parsers_handle_empty() -> None:
    run = _load_module(SCRIPT_PATH)

    assert run._blank_to_none(None) is None
    assert run._blank_to_none("  ") is None
    assert run._blank_to_none("abc") == "abc"

    assert run._as_int("12", name="x") == 12
    assert run._as_float("12.5", name="price") == 12.5


def test_coalesce_and_parser_defaults() -> None:
    run = _load_module(SCRIPT_PATH)

    assert run._coalesce(None, "fallback", 10) == "fallback"
    assert run._coalesce(None, None, "final") == "final"
