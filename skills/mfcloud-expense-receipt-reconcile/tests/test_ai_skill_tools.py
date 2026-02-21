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
    env_keys: list[str] | None = None,
    runner_code: str | None = None,
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
        runner.write_text(runner_code or "print('ok')\n", encoding="utf-8")
    if env_keys:
        keys_block = "\n".join(f"    - {key}" for key in env_keys)
        (skill_dir / "skill.yaml").write_text(
            "\n".join(
                [
                    "version: 1",
                    f"name: {name}",
                    "kind: automation",
                    "",
                    "entrypoint:",
                    "  runtime: python",
                    "  command: python scripts/run.py",
                    "",
                    "secrets:",
                    "  env:",
                    keys_block,
                    "",
                ]
            ),
            encoding="utf-8",
        )


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


def test_execute_skill_injects_only_required_env_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "alpha",
        name="alpha",
        description="env inject test",
        with_runner=True,
        env_keys=["INJECT_ME"],
        runner_code=(
            "import json, os\n"
            "print(json.dumps({'inject': os.environ.get('INJECT_ME'), 'other': os.environ.get('OTHER')}))\n"
        ),
    )
    ax_home = tmp_path / "ax-home"
    secrets = ax_home / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "a.env").write_text("INJECT_ME=from_secret\nOTHER=should_not_be_injected\n", encoding="utf-8")

    monkeypatch.setenv("AX_HOME", str(ax_home))
    monkeypatch.setattr(ai_skill_tools, "_skills_root", lambda: skills_root)
    monkeypatch.delenv(ai_skill_tools.ALLOWLIST_ENV, raising=False)
    monkeypatch.delenv("INJECT_ME", raising=False)
    monkeypatch.delenv("OTHER", raising=False)

    result = ai_skill_tools.execute_skill("alpha")
    payload = result.get("stdout") or "{}"
    assert "\"inject\": \"from_secret\"" in payload
    assert "\"other\": null" in payload
    assert result["required_env_keys"] == ["INJECT_ME"]
    assert result["injected_env_keys"] == ["INJECT_ME"]


def test_execute_skill_does_not_override_existing_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "beta",
        name="beta",
        description="env override test",
        with_runner=True,
        env_keys=["EXISTING_KEY"],
        runner_code="import os\nprint(os.environ.get('EXISTING_KEY') or '')\n",
    )
    ax_home = tmp_path / "ax-home"
    secrets = ax_home / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "b.env").write_text("EXISTING_KEY=from_secret\n", encoding="utf-8")

    monkeypatch.setenv("AX_HOME", str(ax_home))
    monkeypatch.setenv("EXISTING_KEY", "from_env")
    monkeypatch.setattr(ai_skill_tools, "_skills_root", lambda: skills_root)
    monkeypatch.delenv(ai_skill_tools.ALLOWLIST_ENV, raising=False)

    result = ai_skill_tools.execute_skill("beta")
    assert str(result.get("stdout") or "").strip() == "from_env"
    assert result["required_env_keys"] == ["EXISTING_KEY"]
    assert result["injected_env_keys"] == []


def test_execute_skill_reads_ax_home_secrets_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "gamma",
        name="gamma",
        description="ax home secrets test",
        with_runner=True,
        env_keys=["AXHOME_KEY"],
        runner_code="import os\nprint(os.environ.get('AXHOME_KEY') or '')\n",
    )
    ax_home = tmp_path / "ax-home"
    secrets = ax_home / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "kintone.env").write_text("AXHOME_KEY=from_ax_home\n", encoding="utf-8")

    monkeypatch.setenv("AX_HOME", str(ax_home))
    monkeypatch.delenv("AXHOME_KEY", raising=False)
    monkeypatch.setattr(ai_skill_tools, "_skills_root", lambda: skills_root)
    monkeypatch.delenv(ai_skill_tools.ALLOWLIST_ENV, raising=False)

    result = ai_skill_tools.execute_skill("gamma")
    assert str(result.get("stdout") or "").strip() == "from_ax_home"
    assert result["required_env_keys"] == ["AXHOME_KEY"]
    assert result["injected_env_keys"] == ["AXHOME_KEY"]
