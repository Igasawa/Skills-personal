from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
from types import ModuleType
from typing import Any, Dict, Iterator, Tuple


PORTABLE_PPTX_SKILL_ROOT = (
    Path(__file__).resolve().parents[3]
    / "portable-codex-skills"
    / "pptx"
)
PORTABLE_INVENTORY_PATH = PORTABLE_PPTX_SKILL_ROOT / "scripts" / "inventory.py"
PORTABLE_REPLACE_PATH = PORTABLE_PPTX_SKILL_ROOT / "scripts" / "replace.py"


def _load_script_module(path: Path, module_name: str) -> ModuleType:
    if not path.is_file():
        raise FileNotFoundError(f"Missing script: {path}")
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _portable_pptx_modules() -> Iterator[tuple[ModuleType, ModuleType]]:
    script_dir = str(PORTABLE_REPLACE_PATH.parent)
    path_inserted = False
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
        path_inserted = True

    previous_inventory = sys.modules.get("inventory")
    previous_replace = sys.modules.get("replace")
    inventory_module = None
    replace_module = None
    try:
        inventory_module = _load_script_module(
            PORTABLE_INVENTORY_PATH,
            "_dashboard_portable_pptx_inventory",
        )
        sys.modules["inventory"] = inventory_module
        replace_module = _load_script_module(
            PORTABLE_REPLACE_PATH,
            "_dashboard_portable_pptx_replace",
        )
        yield inventory_module, replace_module
    finally:
        if previous_inventory is None:
            sys.modules.pop("inventory", None)
        else:
            sys.modules["inventory"] = previous_inventory
        if previous_replace is None:
            sys.modules.pop("replace", None)
        else:
            sys.modules["replace"] = previous_replace
        if path_inserted and script_dir in sys.path:
            try:
                sys.path.remove(script_dir)
            except ValueError:
                pass
        if previous_inventory is None and inventory_module:
            sys.modules.pop("_dashboard_portable_pptx_inventory", None)
        if previous_replace is None and replace_module:
            sys.modules.pop("_dashboard_portable_pptx_replace", None)


def _build_replacements_from_inventory(
    inventory: Any,
) -> tuple[Dict[str, Dict[str, object]], Dict[str, int]]:
    replacements: Dict[str, Dict[str, object]] = {}
    shape_count = 0
    paragraph_count = 0

    if not isinstance(inventory, dict):
        return replacements, {"shape_count": 0, "paragraph_count": 0}

    for slide_key, shapes in inventory.items():
        if not isinstance(shapes, dict):
            continue
        slide_payload: Dict[str, Any] = {}
        for shape_key, shape_data in shapes.items():
            paragraphs = getattr(shape_data, "paragraphs", [])
            if not paragraphs:
                continue

            raw_paragraphs = []
            shape_title = str(getattr(shape_data, "placeholder_type", "") or "").upper()
            for index, paragraph in enumerate(paragraphs):
                if not hasattr(paragraph, "to_dict"):
                    continue
                paragraph_payload = paragraph.to_dict()
                text = str(paragraph_payload.get("text", "")).strip()
                if not text:
                    continue
                if shape_title in {"TITLE", "CENTER_TITLE", "SUBTITLE"} and index == 0:
                    paragraph_payload["alignment"] = paragraph_payload.get("alignment", "CENTER")
                    paragraph_payload["bold"] = paragraph_payload.get("bold", True)
                raw_paragraphs.append(paragraph_payload)
                paragraph_count += 1

            if not raw_paragraphs:
                continue
            shape_payload = {"paragraphs": raw_paragraphs}
            slide_payload[str(shape_key)] = shape_payload
            shape_count += 1

        if slide_payload:
            replacements[str(slide_key)] = slide_payload

    return replacements, {"shape_count": shape_count, "paragraph_count": paragraph_count}


def polish_with_portable_skill(
    source: Path,
    output: Path,
) -> tuple[bool, dict]:
    if not PORTABLE_INVENTORY_PATH.is_file() or not PORTABLE_REPLACE_PATH.is_file():
        return (
            False,
            {
                "engine": "portable-pptx-skill",
                "reason": "portable skill scripts are missing",
            },
        )

    source = Path(source)
    output = Path(output)
    if not source.exists():
        return False, {"engine": "portable-pptx-skill", "reason": "input file not found"}
    if source.suffix.lower() != ".pptx":
        return False, {"engine": "portable-pptx-skill", "reason": "input is not a .pptx file"}

    try:
        with _portable_pptx_modules() as (inventory_module, replace_module):
            inventory = inventory_module.extract_text_inventory(source)  # type: ignore[attr-defined]
            replacements, stats = _build_replacements_from_inventory(inventory)
            if not replacements:
                return (
                    False,
                    {
                        "engine": "portable-pptx-skill",
                        "reason": "no text shapes found for replacement",
                    },
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as tmp_dir:
                replacement_path = Path(tmp_dir) / "replacement.json"
                with replacement_path.open("w", encoding="utf-8") as handle:
                    json.dump(replacements, handle, ensure_ascii=False, indent=2)
                replace_module.apply_replacements(  # type: ignore[attr-defined]
                    str(source),
                    str(replacement_path),
                    str(output),
                )

        return (
            True,
            {
                "engine": "portable-pptx-skill",
                "shape_count": int(stats.get("shape_count", 0)),
                "paragraph_count": int(stats.get("paragraph_count", 0)),
            },
        )
    except Exception as exc:
        return (
            False,
            {
                "engine": "portable-pptx-skill",
                "reason": f"{type(exc).__name__}: {exc}",
            },
        )
