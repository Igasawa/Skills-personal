from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts import run_core_playwright as rp


def _write(path: Path, text: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_find_package_root_walks_up(tmp_path: Path) -> None:
    package_root = tmp_path / "skill"
    _write(package_root / "package.json")
    nested = package_root / "scripts" / "nested"
    nested.mkdir(parents=True, exist_ok=True)

    resolved = rp._find_package_root(nested)
    assert resolved == package_root


def test_ensure_playwright_installed_skips_when_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package_root = tmp_path / "skill"
    _write(package_root / "node_modules" / "playwright" / "package.json")

    called = {"run": False}

    def _unexpected_run(*args, **kwargs):  # noqa: ANN001, ANN002
        called["run"] = True
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

    monkeypatch.setattr(rp.subprocess, "run", _unexpected_run)
    rp._ensure_playwright_installed(package_root=package_root, env={})
    assert called["run"] is False


def test_ensure_playwright_installed_runs_npm_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package_root = tmp_path / "skill"
    _write(package_root / "package.json")

    monkeypatch.setattr(rp, "_which_any", lambda _: "npm")

    def _fake_run(*args, **kwargs):  # noqa: ANN001, ANN002
        _write(package_root / "node_modules" / "playwright" / "package.json")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rp.subprocess, "run", _fake_run)
    rp._ensure_playwright_installed(package_root=package_root, env={})


def test_ensure_playwright_installed_requires_npm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package_root = tmp_path / "skill"
    _write(package_root / "package.json")
    monkeypatch.setattr(rp, "_which_any", lambda _: None)

    with pytest.raises(FileNotFoundError):
        rp._ensure_playwright_installed(package_root=package_root, env={})
