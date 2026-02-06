#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Any


def _which_any(candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


def _find_package_root(start_dir: Path) -> Path:
    current = start_dir.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "package.json").exists():
            return candidate
    return current


def _ensure_playwright_installed(*, package_root: Path, env: dict[str, str]) -> None:
    if (package_root / "node_modules" / "playwright" / "package.json").exists():
        return
    npm = _which_any(("npm.cmd", "npm.exe", "npm"))
    if not npm:
        raise FileNotFoundError("npm not found in PATH. Please install Node.js/npm.")
    install_cmd = [npm, "install", "--no-audit", "--no-fund"]
    res = subprocess.run(
        install_cmd,
        cwd=str(package_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            "Failed to install Node dependencies:\n"
            f"cmd: {install_cmd}\n"
            f"exit: {res.returncode}\n"
            f"stdout:\n{res.stdout}\n"
            f"stderr:\n{res.stderr}\n"
        )
    if not (package_root / "node_modules" / "playwright" / "package.json").exists():
        raise RuntimeError("playwright package is still missing after npm install.")


def run_node_playwright_script(
    *,
    script_path: Path,
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    package_root = _find_package_root(cwd)
    _ensure_playwright_installed(package_root=package_root, env=merged_env)
    node = _which_any(("node.exe", "node"))
    if not node:
        raise FileNotFoundError("node not found in PATH. Please install Node.js.")
    cmd = [node, str(script_path), *args]
    proc = subprocess.Popen(
        cmd,
        cwd=str(package_root),
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _drain(stream, sink, is_err: bool = False) -> None:
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            try:
                line = raw.decode("utf-8", errors="replace")
            except Exception:
                line = raw.decode(errors="replace")
            sink.append(line)
            if is_err:
                print(line.rstrip("\n"), file=sys.stderr, flush=True)
            else:
                print(line.rstrip("\n"), file=sys.stdout, flush=True)

    t_out = threading.Thread(target=_drain, args=(proc.stdout, stdout_lines))
    t_err = threading.Thread(target=_drain, args=(proc.stderr, stderr_lines, True))
    t_out.start()
    t_err.start()
    returncode = proc.wait()
    t_out.join()
    t_err.join()

    res_stdout = "".join(stdout_lines)
    res_stderr = "".join(stderr_lines)
    if returncode != 0:
        raise RuntimeError(
            "Node script failed:\n"
            f"cmd: {cmd}\n"
            f"exit: {returncode}\n"
            f"stdout:\n{res_stdout}\n"
            f"stderr:\n{res_stderr}\n"
        )
    stdout_str = res_stdout.strip()
    if not stdout_str:
        return {}
    lines = [ln for ln in stdout_str.splitlines() if ln.strip()]
    for candidate in reversed(lines):
        if candidate.lstrip().startswith("{") and candidate.rstrip().endswith("}"):
            try:
                return json.loads(candidate)
            except Exception:
                continue
    try:
        return json.loads(stdout_str)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Node script returned non-JSON stdout:\n{res_stdout}") from e
