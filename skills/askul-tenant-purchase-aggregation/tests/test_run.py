from __future__ import annotations

from pathlib import Path
import importlib.util


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"

spec = importlib.util.spec_from_file_location("askul_run", SCRIPT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load askul run module")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def test_to_str_trims_and_stringifies() -> None:
    assert run._to_str(None) == ""
    assert run._to_str("  test ") == "test"
    assert run._to_str(12) == "12"


def test_normalize_column_removes_spaces_and_symbols() -> None:
    assert run._normalize_column(" Amount Total ") == "amounttotal"
    assert run._normalize_column("A B C") == "abc"


def test_as_bool_parsing() -> None:
    assert run._as_bool("yes", default=False) is True
    assert run._as_bool("0", default=True) is False


def test_build_parser_has_csv_required_argument() -> None:
    parser = run.build_parser()
    args = parser.parse_args(["--csv-path", "sample.csv"])
    assert args.csv_path == "sample.csv"


def test_parse_amount_with_negative_parenthesis() -> None:
    assert run._parse_amount("(123)") == -123.0
