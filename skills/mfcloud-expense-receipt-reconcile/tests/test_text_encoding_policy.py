from __future__ import annotations

import codecs
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKIP_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
}
TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".tsx",
    ".json",
    ".jsonl",
    ".yml",
    ".yaml",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".ps1",
    ".sh",
    ".bat",
    ".cmd",
}
TEXT_FILENAMES = {".editorconfig", ".gitattributes", ".gitignore", "README.md"}
KNOWN_MOJIBAKE_MARKERS = {
    "�",
    "ぁE",
    "�E",
    "、E{",
    "候裁E",
    "作�E",
    "完亁E",
    "取征E",
    "重褁E",
    "失敁E",
    "アチE",
}


def _iter_text_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            suffix = path.suffix.lower()
            if suffix in TEXT_EXTENSIONS or filename in TEXT_FILENAMES:
                yield path


def test_repository_text_files_are_utf8_without_bom() -> None:
    invalid_utf8: list[str] = []
    utf8_bom: list[str] = []

    for path in _iter_text_files(REPO_ROOT):
        relative = path.relative_to(REPO_ROOT).as_posix()
        raw = path.read_bytes()

        if raw.startswith(codecs.BOM_UTF8):
            utf8_bom.append(relative)

        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            invalid_utf8.append(relative)

    assert not invalid_utf8, f"non-utf8 files found: {invalid_utf8}"
    assert not utf8_bom, f"utf8 bom files found: {utf8_bom}"


def test_repository_text_files_have_no_known_mojibake_markers() -> None:
    findings: list[str] = []
    self_path = Path(__file__).resolve()

    for path in _iter_text_files(REPO_ROOT):
        if path.resolve() == self_path:
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for marker in KNOWN_MOJIBAKE_MARKERS:
                if marker in line:
                    findings.append(f"{relative}:{lineno}: contains marker {marker!r}")
                    break

    assert not findings, f"mojibake markers found: {findings}"
