from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import importlib.util
import os

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mf_accounting_csv_export_run", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coalesce_and_blank_to_none() -> None:
    run = _load_module()
    assert run._coalesce(None, "", 0) == ""
    assert run._coalesce() is None
    assert run._blank_to_none(None) is None
    assert run._blank_to_none("  ") is None
    assert run._blank_to_none(12) == "12"


def test_parse_int_float_bool() -> None:
    run = _load_module()
    assert run._as_int("7", name="n") == 7
    assert run._as_float("1.5", name="r") == 1.5
    assert run._as_bool(True, name="b") is True
    assert run._as_bool("off", name="b") is False
    with pytest.raises(ValueError, match="Missing required integer"):
        run._as_int(None, name="n")
    with pytest.raises(ValueError, match="Invalid float"):
        run._as_float("x", name="r")


def test_normalize_and_optional_helpers() -> None:
    run = _load_module()
    assert run._normalize_list([" A ", "", None, "A", "B ", "B"]) == ["A", "B"]
    assert run._normalize_list(None) == []
    assert run._normalize_list(3) == ["3"]
    assert run._normalize_optional_header("none") is None
    assert run._normalize_optional_header("  value ") == "value"


def test_safe_name_and_default_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = _load_module()
    monkeypatch.setenv("AX_HOME", str(tmp_path / "axhome"))
    assert run._safe_name("a b/c") == "a_b_c"
    assert run._ax_home() == Path(os.environ["AX_HOME"]).expanduser()
    assert run._default_output_dir() == run._ax_home() / "reports" / "mf_accounting_csv"
    assert run._default_download_dir() == run._ax_home() / "downloads" / "mf_accounting"
    assert str(run._default_storage_state_path("session.name")) == str(
        run._ax_home() / "sessions" / "session.name.storage.json"
    )


def test_preset_and_delimiter() -> None:
    run = _load_module()
    name, spec = run._resolve_preset(None)
    assert name == run.DEFAULT_PRESET_NAME
    assert "required_columns" in spec

    with pytest.raises(ValueError, match="Unsupported preset"):
        run._resolve_preset("does-not-exist")

    payload = run._list_presets_payload()
    assert "default_preset" in payload
    assert run.DEFAULT_PRESET_NAME in payload["presets"]

    assert run._resolve_delimiter(",", "a,b,c") == ","
    assert run._resolve_delimiter("\\t", "a\tb\tc") == "\t"
    with pytest.raises(ValueError, match="Unsupported delimiter"):
        run._resolve_delimiter("bad", "a,b")


def test_date_and_amount_parse_and_decimal_str() -> None:
    run = _load_module()
    assert run._parse_flexible_date("2026-02-10") == date(2026, 2, 10)
    assert run._parse_flexible_date("2026/02/10 11:22:33") == date(2026, 2, 10)
    assert run._parse_flexible_date("   ") is None

    assert run._parse_amount("1,234") == Decimal("1234")
    assert run._parse_amount("(1,234)") == Decimal("-1234")
    assert run._parse_amount("  ") is None

    assert run._decimal_str(Decimal("12.30")) == "12.30"


def test_detect_encoding_and_delimiter_prefers_override(tmp_path: Path) -> None:
    run = _load_module()
    tmp_csv = tmp_path / "sample.csv"
    tmp_csv.write_text("a\tb\n1\t2\n", encoding="utf-8")
    enc, delimiter = run._detect_encoding_and_delimiter(
        tmp_csv,
        encoding_pref="utf-8",
        delimiter_pref="auto",
    )
    assert enc == "utf-8"
    assert delimiter in ("\t", ",")
