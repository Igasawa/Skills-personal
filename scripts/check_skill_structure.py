#!/usr/bin/env python3
"""Repository structure check for skill directories.

Usage:
  python scripts/check_skill_structure.py
  python scripts/check_skill_structure.py --json
  python scripts/check_skill_structure.py --strict
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
GIT_CMD = ["git", "ls-files"]
TRACKED_FILES = None

REQUIRED_TOP = ("SKILL.md", "skill.yaml", "README.md")
OPTIONAL_TOP = ("assets", "scripts", "references", "tests", "dashboard", "docs")


@dataclass
class SkillReport:
    name: str
    ok: bool
    issues: list[str]
    metadata: list[str]
    optional_dirs: list[str]


def scan_skill(skill_dir: Path) -> SkillReport:
    issues: list[str] = []
    skill_prefix = skill_dir.relative_to(ROOT)
    tracked = [Path(p) for p in _tracked_files_by_prefix(skill_dir)]
    top_files = {p.name for p in tracked if p.parent == skill_prefix}
    metadata = sorted(name for name in REQUIRED_TOP if name in top_files)

    if not metadata:
        issues.append(
            "no metadata file at top level (expected one of: "
            + ", ".join(REQUIRED_TOP) + ")"
        )

    optional_dirs = sorted(d.name for d in skill_dir.iterdir() if d.is_dir() and d.name in OPTIONAL_TOP)

    # Encourage tests only if python scripts exist and no tests/ directory.
    has_python = any(
        p.suffix == ".py" and len(p.parts) >= 3 and p.parts[2] == "scripts"
        for p in tracked
    ) if (skill_dir / "scripts").exists() else False
    has_tests = (skill_dir / "tests").exists()
    if has_python and not has_tests:
        issues.append("has scripts/*.py but no tests/ directory")

    # Keep .pycache/.log artifacts out of repository.
    tmp_patterns = [
        "tmp_",
        "_tmp_",
        "workspace_",
        "ws.diff",
    ]
    for p in tracked:
        name = p.name
        if any(name.startswith(prefix) for prefix in tmp_patterns):
            issues.append(f"temporary artifact-like file detected: {p.relative_to(skill_prefix)}")
            break
        if p.name.endswith(".pyc"):
            issues.append(f"bytecode file should be gitignored: {p.relative_to(skill_prefix)}")
            break

    return SkillReport(skill_dir.name, not issues, issues, metadata, optional_dirs)


def _tracked_files_by_prefix(skill_dir: Path) -> list[str]:
    global TRACKED_FILES
    if TRACKED_FILES is None:
        result = subprocess.run(
            GIT_CMD,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
        TRACKED_FILES = result
    else:
        result = TRACKED_FILES

    prefix = str(skill_dir.relative_to(ROOT)).replace("\\", "/")
    return [p for p in result if p.startswith(prefix + "/")]


def collect_reports() -> list[SkillReport]:
    return [scan_skill(p) for p in sorted(SKILLS_DIR.iterdir()) if p.is_dir()]


def to_payload(reports: list[SkillReport]) -> dict:
    return {
        "skill_count": len(reports),
        "skills": [
            {
                "name": r.name,
                "ok": r.ok,
                "metadata": r.metadata,
                "optional_dirs": r.optional_dirs,
                "issues": r.issues,
            }
            for r in reports
        ],
        "violations": sum(1 for r in reports if r.issues),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check repository skill layout")
    parser.add_argument("--json", action="store_true", help="output machine-readable JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit with non-zero when violations exist",
    )
    args = parser.parse_args()

    if not SKILLS_DIR.is_dir():
        raise SystemExit("skills directory not found")

    reports = collect_reports()
    payload = to_payload(reports)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in payload["skills"]:
            icon = "OK" if item["ok"] else "NG"
            print(f"[{icon}] {item['name']}")
            if item["metadata"]:
                print("  metadata:", ", ".join(item["metadata"]))
            if item["optional_dirs"]:
                print("  optional dirs:", ", ".join(item["optional_dirs"]))
            if not item["ok"]:
                print("  issues:")
                for issue in item["issues"]:
                    print(f"   - {issue}")
            print()

        print(f"skills: {payload['skill_count']}  violations: {payload['violations']}")

    if args.strict and payload["violations"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
