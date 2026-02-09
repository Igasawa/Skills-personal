from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLES_DIR = ROOT / "dashboard" / "static" / "styles"

# Hardcoded color literals are disallowed in component/page/layout layers.
COLOR_LITERAL_PATTERNS = [
    re.compile(r"#[0-9a-fA-F]{3,8}\b"),
    re.compile(r"\b(?:rgba?|hsla?)\(\s*(?!var\()"),
]

# Styles that must stay token-driven and accessible.
LAYER_FILES = [
    STYLES_DIR / "layout.css",
    STYLES_DIR / "components.css",
    STYLES_DIR / "pages.css",
]
BASE_FILE = STYLES_DIR / "base.css"


def read_text(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def check_no_color_literals(path: Path, lines: list[str]) -> list[str]:
    errors: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("/*"):
            continue
        for pattern in COLOR_LITERAL_PATTERNS:
            if pattern.search(line):
                errors.append(
                    f"{path.relative_to(ROOT)}:{lineno}: hardcoded color literal is not allowed: {stripped}"
                )
                break
    return errors


def check_required_accessibility_contract(path: Path, lines: list[str]) -> list[str]:
    joined = "\n".join(lines)
    errors: list[str] = []
    if ":focus-visible" not in joined:
        errors.append(
            f"{path.relative_to(ROOT)}: missing ':focus-visible' rule required by dashboard design contract."
        )
    if "@media (prefers-reduced-motion: reduce)" not in joined:
        errors.append(
            f"{path.relative_to(ROOT)}: missing '@media (prefers-reduced-motion: reduce)' rule required by dashboard design contract."
        )
    return errors


def main() -> int:
    errors: list[str] = []

    for path in LAYER_FILES:
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)}: file is missing.")
            continue
        lines = read_text(path)
        errors.extend(check_no_color_literals(path, lines))

    if BASE_FILE.exists():
        base_lines = read_text(BASE_FILE)
        errors.extend(check_required_accessibility_contract(BASE_FILE, base_lines))
    else:
        errors.append(f"{BASE_FILE.relative_to(ROOT)}: file is missing.")

    if errors:
        print("Dashboard design contract check failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    print("Dashboard design contract check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
