from __future__ import annotations

from datetime import datetime
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SKILL_DOC_NAME = "SKILL.md"
MAX_ARGS = 40
MAX_ARG_CHARS = 200
MAX_OUTPUT_CHARS = 12000
DEFAULT_TIMEOUT_SECONDS = 120
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 600
ALLOWLIST_ENV = "AX_AI_CHAT_SKILL_ALLOWLIST"
PERMISSIONS_FILE_NAME = "skill_permissions.json"
MAX_PERMISSION_ITEMS = 500
IGNORED_SKILL_PATH_PARTS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
}


class SkillError(RuntimeError):
    """Base class for skill discovery/execution errors."""


class SkillNotFoundError(SkillError):
    """Raised when a skill id does not exist."""


class SkillNotExecutableError(SkillError):
    """Raised when a skill does not provide an executable runner."""


class SkillNotAllowedError(SkillError):
    """Raised when a skill is blocked by allowlist policy."""


class SkillExecutionTimeoutError(SkillError):
    """Raised when a skill command timed out."""


class SkillInvalidArgumentsError(SkillError):
    """Raised when skill execution arguments are invalid."""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    if len(path.parents) >= 5:
        return path.parents[4]
    return path.parents[len(path.parents) - 1]


def _skills_root() -> Path:
    return _repo_root() / "skills"


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _permissions_path() -> Path:
    return _ax_home() / "artifacts" / "mfcloud-expense-receipt-reconcile" / "_ai" / PERMISSIONS_FILE_NAME


def _normalize_skill_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except Exception:
        return path.read_text(encoding="utf-8", errors="ignore")


def _parse_front_matter(path: Path) -> dict[str, str]:
    raw = _read_text(path)
    if not raw.startswith("---"):
        return {}
    lines = raw.splitlines()
    out: dict[str, str] = {}
    in_front_matter = False
    for line in lines:
        text = str(line or "")
        if text.strip() == "---":
            if not in_front_matter:
                in_front_matter = True
                continue
            break
        if not in_front_matter:
            continue
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        out[str(key).strip().lower()] = str(value).strip().strip('"').strip("'")
    return out


def _iter_skill_dirs(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for skill_md in root.rglob(SKILL_DOC_NAME):
        if not skill_md.is_file():
            continue
        try:
            rel = skill_md.relative_to(root)
        except Exception:
            continue
        rel_parts = [str(part) for part in rel.parts[:-1]]
        if not rel_parts:
            continue
        lowered = [part.lower() for part in rel_parts]
        if any(part.startswith(".") for part in rel_parts):
            continue
        if any(part in IGNORED_SKILL_PATH_PARTS for part in lowered):
            continue
        candidates.append(skill_md.parent)

    unique = {path.resolve(): path for path in candidates}
    ordered = sorted(
        unique.values(),
        key=lambda p: (
            len(p.relative_to(root).parts),
            str(p.relative_to(root)).replace("\\", "/").lower(),
        ),
    )
    return ordered


def _detect_runner(skill_dir: Path) -> Path | None:
    candidates = [
        skill_dir / "scripts" / "run.py",
        skill_dir / "scripts" / "run.ps1",
        skill_dir / "scripts" / "run.mjs",
        skill_dir / "scripts" / "run.js",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _parse_allowlist() -> set[str] | None:
    raw = str(os.environ.get(ALLOWLIST_ENV) or "").strip()
    if not raw:
        return None
    out: set[str] = set()
    for token in raw.split(","):
        key = _normalize_skill_id(token)
        if key:
            out.add(key)
    return out if out else None


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(value)


def _normalize_permission_overrides(value: Any) -> dict[str, bool]:
    rows = value if isinstance(value, dict) else {}
    out: dict[str, bool] = {}
    for key, raw_enabled in rows.items():
        skill_id = _normalize_skill_id(key)
        if not skill_id:
            continue
        out[skill_id] = _coerce_bool(raw_enabled)
        if len(out) >= MAX_PERMISSION_ITEMS:
            break
    return out


def get_permission_settings() -> dict[str, Any]:
    path = _permissions_path()
    raw = _read_json(path)
    src = raw if isinstance(raw, dict) else {}
    overrides = _normalize_permission_overrides(src.get("overrides"))
    updated_at = str(src.get("updated_at") or "").strip() or None
    allowlist = _parse_allowlist()
    return {
        "overrides": overrides,
        "updated_at": updated_at,
        "path": str(path),
        "env_allowlist_enabled": allowlist is not None,
        "env_allowlist": sorted(allowlist) if allowlist is not None else [],
    }


def _is_env_allowed(skill_id: str, has_runner: bool, allowlist: set[str] | None) -> bool:
    if not has_runner:
        return False
    if allowlist is None:
        return True
    return skill_id in allowlist


def _is_allowed(
    *,
    skill_id: str,
    has_runner: bool,
    allowlist: set[str] | None,
    admin_enabled: bool,
) -> bool:
    if not admin_enabled:
        return False
    return _is_env_allowed(skill_id, has_runner, allowlist)


def _build_execution_capabilities(*, has_runner: bool) -> dict[str, Any]:
    if has_runner:
        return {
            "api_executable": True,
            "agent_executable": True,
            "api_unavailable_reason": None,
        }
    return {
        "api_executable": False,
        "agent_executable": True,
        "api_unavailable_reason": "runner_missing",
    }


def list_skills() -> list[dict[str, Any]]:
    root = _skills_root()
    allowlist = _parse_allowlist()
    settings = get_permission_settings()
    overrides = (
        settings.get("overrides")
        if isinstance(settings, dict) and isinstance(settings.get("overrides"), dict)
        else {}
    )
    if not root.exists():
        return []

    out: list[dict[str, Any]] = []
    seen_skill_ids: set[str] = set()
    for skill_dir in _iter_skill_dirs(root):
        skill_md = skill_dir / SKILL_DOC_NAME
        metadata = _parse_front_matter(skill_md)
        skill_id = _normalize_skill_id(metadata.get("name") or skill_dir.name)
        if not skill_id:
            continue
        if skill_id in seen_skill_ids:
            continue
        seen_skill_ids.add(skill_id)
        runner = _detect_runner(skill_dir)
        has_runner = runner is not None
        admin_enabled = bool(overrides.get(skill_id, True))
        env_allowed = _is_env_allowed(skill_id, has_runner, allowlist)
        capabilities = _build_execution_capabilities(has_runner=has_runner)
        allowed = _is_allowed(
            skill_id=skill_id,
            has_runner=has_runner,
            allowlist=allowlist,
            admin_enabled=admin_enabled,
        )
        out.append(
            {
                "id": skill_id,
                "name": metadata.get("name") or skill_dir.name,
                "description": metadata.get("description") or "",
                "skill_md": str(skill_md),
                "has_runner": has_runner,
                "runner": str(runner) if runner else None,
                "api_executable": bool(capabilities["api_executable"]),
                "agent_executable": bool(capabilities["agent_executable"]),
                "api_unavailable_reason": capabilities["api_unavailable_reason"],
                "env_allowed": env_allowed,
                "admin_enabled": admin_enabled,
                "allowed": allowed,
            }
        )
    return out


def _coerce_timeout(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = DEFAULT_TIMEOUT_SECONDS
    if parsed < MIN_TIMEOUT_SECONDS:
        return MIN_TIMEOUT_SECONDS
    if parsed > MAX_TIMEOUT_SECONDS:
        return MAX_TIMEOUT_SECONDS
    return parsed


def _normalize_args(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parsed = shlex.split(value)
        return _normalize_args(parsed)
    if not isinstance(value, list):
        raise SkillInvalidArgumentsError("args must be an array of strings.")
    if len(value) > MAX_ARGS:
        raise SkillInvalidArgumentsError(f"args exceeds max items ({MAX_ARGS}).")

    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise SkillInvalidArgumentsError(f"args[{index}] must be a string.")
        arg = str(item).strip()
        if len(arg) > MAX_ARG_CHARS:
            raise SkillInvalidArgumentsError(f"args[{index}] exceeds {MAX_ARG_CHARS} chars.")
        if "\n" in arg or "\r" in arg:
            raise SkillInvalidArgumentsError(f"args[{index}] must not contain line breaks.")
        out.append(arg)
    return out


def _resolve_skill(skill_id: str) -> dict[str, Any]:
    wanted = _normalize_skill_id(skill_id)
    if not wanted:
        raise SkillNotFoundError("skill id is required.")
    for row in list_skills():
        if _normalize_skill_id(row.get("id")) == wanted:
            return row
    raise SkillNotFoundError(f"skill not found: {skill_id}")


def set_skill_permission(skill_id: str, enabled: Any) -> dict[str, Any]:
    row = _resolve_skill(skill_id)
    resolved_skill_id = _normalize_skill_id(row.get("id"))
    if not resolved_skill_id:
        raise SkillNotFoundError("skill id is required.")
    normalized_enabled = _coerce_bool(enabled)

    settings = get_permission_settings()
    overrides = (
        settings.get("overrides")
        if isinstance(settings, dict) and isinstance(settings.get("overrides"), dict)
        else {}
    )
    merged = dict(overrides)
    merged[resolved_skill_id] = normalized_enabled
    updated_at = _now_iso()
    _write_json(
        _permissions_path(),
        {
            "overrides": merged,
            "updated_at": updated_at,
        },
    )
    return {
        "skill": resolved_skill_id,
        "enabled": normalized_enabled,
        "updated_at": updated_at,
        "path": str(_permissions_path()),
    }


def _trim_output(value: str) -> tuple[str, bool]:
    text = str(value or "")
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS] + "\n...[truncated]...", True


def _build_command(runner: Path, args: list[str]) -> list[str]:
    suffix = runner.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(runner), *args]
    if suffix == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner), *args]
    if suffix in {".mjs", ".js"}:
        return ["node", str(runner), *args]
    raise SkillNotExecutableError(f"Unsupported runner extension: {suffix}")


def execute_skill(skill_id: str, args: Any = None, timeout_seconds: Any = None) -> dict[str, Any]:
    skill = _resolve_skill(skill_id)
    if not bool(skill.get("has_runner")):
        raise SkillNotExecutableError(
            "Skill has no API runner: "
            f"{skill_id}. API execution requires one of scripts/run.py, scripts/run.ps1, "
            "scripts/run.mjs, or scripts/run.js. The skill can still run via SKILL.md-based "
            "agent execution."
        )
    if not bool(skill.get("allowed")):
        raise SkillNotAllowedError(f"Skill execution is not allowed: {skill_id}")

    runner_raw = str(skill.get("runner") or "").strip()
    if not runner_raw:
        raise SkillNotExecutableError(f"Skill runner path is missing: {skill_id}")
    runner = Path(runner_raw)
    if not runner.exists():
        raise SkillNotExecutableError(f"Skill runner not found: {runner}")

    normalized_args = _normalize_args(args)
    timeout = _coerce_timeout(timeout_seconds)
    cmd = _build_command(runner, normalized_args)
    cwd = str(runner.parent.parent if runner.parent.name == "scripts" else runner.parent)

    started = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise SkillExecutionTimeoutError(
            f"Skill execution timed out after {int(exc.timeout or timeout)} seconds."
        ) from exc
    except FileNotFoundError as exc:
        raise SkillNotExecutableError(f"Runtime command was not found: {exc}") from exc
    except Exception as exc:
        raise SkillError(f"Skill execution failed: {exc}") from exc

    ended = time.time()
    stdout, stdout_truncated = _trim_output(result.stdout or "")
    stderr, stderr_truncated = _trim_output(result.stderr or "")
    return {
        "skill": skill.get("id"),
        "name": skill.get("name"),
        "runner": str(runner),
        "command": cmd,
        "cwd": cwd,
        "timeout_seconds": timeout,
        "duration_ms": int((ended - started) * 1000),
        "returncode": int(result.returncode),
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
