from __future__ import annotations

from pathlib import Path
import importlib.util


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_flow.py"
RUN_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_flow_parser_has_scan_argument() -> None:
    flow = _load_module(SCRIPT_PATH, "docs_knowledge_run_flow")
    parser = flow._build_parser()
    args = parser.parse_args(["--scan", "README.md", "--max-age-days", "1", "--warn-within-days", "0", "--dry-run"])
    assert args.scan == ["README.md"]
    assert args.max_age_days == 1


def test_entrypoint_run_module_exposes_main() -> None:
    main_script = _load_module(RUN_PATH, "docs_knowledge_run")
    assert callable(main_script.main)
