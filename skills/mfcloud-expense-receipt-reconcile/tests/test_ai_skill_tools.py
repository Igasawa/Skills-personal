from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.services import ai_skill_tools


def _write_skill(
    root: Path,
    relative_dir: str,
    *,
    name: str,
    description: str,
    with_runner: bool = False,
) -> None:
    skill_dir = root / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f'description: "{description}"',
                "---",
                "",
                f"# {name}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    if with_runner:
        runner = skill_dir / "scripts" / "run.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text("print('ok')\n", encoding="utf-8")


def test_list_skills_includes_nested_skill_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "docs-knowledge-refresh",
        name="docs-knowledge-refresh",
        description="docs runner",
        with_runner=True,
    )
    _write_skill(
        skills_root,
        "portable-codex-skills/xlsx",
        name="xlsx",
        description="portable xlsx skill",
        with_runner=False,
    )
    _write_skill(
        skills_root,
        "portable-codex-skills/pptx",
        name="pptx",
        description="portable pptx skill",
        with_runner=False,
    )

    monkeypatch.setattr(ai_skill_tools, "_skills_root", lambda: skills_root)
    monkeypatch.delenv(ai_skill_tools.ALLOWLIST_ENV, raising=False)

    rows = ai_skill_tools.list_skills()
    by_id = {str(row.get("id")): row for row in rows}

    assert "docs-knowledge-refresh" in by_id
    assert "xlsx" in by_id
    assert "pptx" in by_id

    assert by_id["docs-knowledge-refresh"]["has_runner"] is True
    assert by_id["docs-knowledge-refresh"]["allowed"] is True

    assert by_id["xlsx"]["has_runner"] is False
    assert by_id["xlsx"]["allowed"] is False
    assert str(by_id["xlsx"]["skill_md"]).replace("\\", "/").endswith(
        "/portable-codex-skills/xlsx/SKILL.md"
    )

    assert by_id["pptx"]["has_runner"] is False
    assert by_id["pptx"]["allowed"] is False
    assert str(by_id["pptx"]["skill_md"]).replace("\\", "/").endswith(
        "/portable-codex-skills/pptx/SKILL.md"
    )


def test_list_skills_prefers_shallower_path_on_duplicate_skill_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "xlsx",
        name="xlsx",
        description="top-level xlsx",
        with_runner=True,
    )
    _write_skill(
        skills_root,
        "portable-codex-skills/xlsx",
        name="xlsx",
        description="nested xlsx",
        with_runner=False,
    )
    _write_skill(
        skills_root,
        ".system/internal-skill",
        name="internal-skill",
        description="must be ignored",
        with_runner=True,
    )

    monkeypatch.setattr(ai_skill_tools, "_skills_root", lambda: skills_root)
    monkeypatch.delenv(ai_skill_tools.ALLOWLIST_ENV, raising=False)

    rows = ai_skill_tools.list_skills()
    by_id = {str(row.get("id")): row for row in rows}

    assert "xlsx" in by_id
    assert "internal-skill" not in by_id
    assert by_id["xlsx"]["has_runner"] is True
    assert by_id["xlsx"]["allowed"] is True
    assert str(by_id["xlsx"]["skill_md"]).replace("\\", "/").endswith("/skills/xlsx/SKILL.md")


def test_list_skills_detects_nested_runner_script(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "portable-codex-skills/pptx",
        name="pptx",
        description="nested pptx",
        with_runner=True,
    )

    monkeypatch.setattr(ai_skill_tools, "_skills_root", lambda: skills_root)
    monkeypatch.delenv(ai_skill_tools.ALLOWLIST_ENV, raising=False)

    rows = ai_skill_tools.list_skills()
    by_id = {str(row.get("id")): row for row in rows}

    assert "pptx" in by_id
    assert by_id["pptx"]["has_runner"] is True
    assert by_id["pptx"]["allowed"] is True
