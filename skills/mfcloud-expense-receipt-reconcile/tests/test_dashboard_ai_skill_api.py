from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from dashboard.routes import api as api_routes
from dashboard.routes import api_ai_chat_routes, api_ai_skill_routes
from dashboard.services import ai_chat


def _create_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(api_routes.create_api_router())
    return TestClient(app)


def test_api_ai_skills_list_returns_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api_ai_skill_routes.ai_skill_tools,
        "list_skills",
        lambda: [
            {
                "id": "alpha",
                "name": "alpha",
                "description": "test",
                "skill_md": "x",
                "has_runner": True,
                "runner": "x",
                "allowed": True,
            }
        ],
    )

    res = client.get("/api/ai/skills")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["count"] == 1
    assert body["skills"][0]["id"] == "alpha"


def test_api_ai_skills_permissions_get_returns_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api_ai_skill_routes.ai_skill_tools,
        "get_permission_settings",
        lambda: {
            "overrides": {"alpha": False},
            "updated_at": "2026-02-19T12:00:00",
            "path": "C:/tmp/skill_permissions.json",
            "env_allowlist_enabled": True,
            "env_allowlist": ["alpha"],
        },
    )

    res = client.get("/api/ai/skills/permissions")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["overrides"]["alpha"] is False
    assert body["env_allowlist_enabled"] is True


def test_api_ai_skills_permissions_update_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api_ai_skill_routes.ai_skill_tools,
        "set_skill_permission",
        lambda skill_id, enabled: {
            "skill": skill_id,
            "enabled": bool(enabled),
            "updated_at": "2026-02-19T12:00:00",
            "path": "C:/tmp/skill_permissions.json",
        },
    )
    monkeypatch.setattr(
        api_ai_skill_routes.ai_skill_tools,
        "list_skills",
        lambda: [
            {
                "id": "alpha",
                "name": "alpha",
                "description": "desc",
                "has_runner": True,
                "runner": "x",
                "env_allowed": True,
                "admin_enabled": False,
                "allowed": False,
            }
        ],
    )

    res = client.post(
        "/api/ai/skills/permissions",
        json={"skill": "alpha", "enabled": False},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["permission"]["skill"] == "alpha"
    assert body["permission"]["enabled"] is False
    assert body["skill"]["id"] == "alpha"


def test_api_ai_skills_permissions_update_rejects_non_bool_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/ai/skills/permissions",
        json={"skill": "alpha", "enabled": "true"},
    )
    assert res.status_code == 400
    assert "boolean" in str(res.json().get("detail") or "").lower()


def test_api_ai_skills_permissions_update_not_found_maps_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    def _raise_not_found(skill_id, enabled):  # noqa: ARG001
        raise api_ai_skill_routes.ai_skill_tools.SkillNotFoundError("missing")

    monkeypatch.setattr(api_ai_skill_routes.ai_skill_tools, "set_skill_permission", _raise_not_found)
    res = client.post(
        "/api/ai/skills/permissions",
        json={"skill": "missing", "enabled": True},
    )
    assert res.status_code == 404
    assert "missing" in str(res.json().get("detail") or "")


def test_api_ai_skills_execute_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api_ai_skill_routes.ai_skill_tools,
        "execute_skill",
        lambda skill_id, args=None, timeout_seconds=None: {
            "skill": skill_id,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 10,
        },
    )

    res = client.post(
        "/api/ai/skills/execute",
        json={"skill": "alpha", "args": ["--help"], "timeout_seconds": 30},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["result"]["skill"] == "alpha"
    assert body["result"]["returncode"] == 0


def test_api_ai_skills_execute_error_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)

    def _raise_not_found(skill_id, args=None, timeout_seconds=None):  # noqa: ARG001
        raise api_ai_skill_routes.ai_skill_tools.SkillNotFoundError("missing")

    monkeypatch.setattr(api_ai_skill_routes.ai_skill_tools, "execute_skill", _raise_not_found)
    res = client.post("/api/ai/skills/execute", json={"skill": "missing"})
    assert res.status_code == 404
    assert "missing" in str(res.json().get("detail") or "")


def test_api_ai_skills_execute_not_executable_includes_skill_md_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    def _raise_not_executable(skill_id, args=None, timeout_seconds=None):  # noqa: ARG001
        raise api_ai_skill_routes.ai_skill_tools.SkillNotExecutableError(
            "Skill has no API runner: alpha. The skill can still run via SKILL.md-based agent execution."
        )

    monkeypatch.setattr(api_ai_skill_routes.ai_skill_tools, "execute_skill", _raise_not_executable)
    res = client.post("/api/ai/skills/execute", json={"skill": "alpha"})
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "SKILL.md-based agent execution" in detail


def test_api_ai_chat_skill_list_command_uses_local_skill_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_tools,
        "list_skills",
        lambda: [
            {
                "id": "alpha",
                "name": "alpha",
                "description": "desc",
                "skill_md": "x",
                "has_runner": True,
                "runner": "x",
                "allowed": True,
            }
        ],
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_chat,
        "chat",
        lambda messages, page_context: (_ for _ in ()).throw(RuntimeError("must not call")),
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "/skill list"}],
            "page_context": {"path": "/", "active_tab": "wizard", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["model"] == "local-skill"
    assert "alpha" in str(body["reply"]["content"])


def test_api_ai_chat_skill_list_mentions_runnerless_skill_guidance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_tools,
        "list_skills",
        lambda: [
            {
                "id": "runnerless",
                "name": "runnerless",
                "description": "desc",
                "skill_md": "x",
                "has_runner": False,
                "runner": None,
                "allowed": False,
            }
        ],
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_chat,
        "chat",
        lambda messages, page_context: (_ for _ in ()).throw(RuntimeError("must not call")),
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "/skill list"}],
            "page_context": {"path": "/", "active_tab": "wizard", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    text = str(body["reply"]["content"] or "")
    assert "No API-executable skills were found." in text
    assert "SKILL.md-based agent execution" in text
    assert "/skill run" in text


def test_api_ai_chat_skill_run_command_executes_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_tools,
        "execute_skill",
        lambda skill_id, args=None, timeout_seconds=None: {
            "skill": skill_id,
            "returncode": 0,
            "stdout": "runner ok",
            "stderr": "",
            "duration_ms": 5,
        },
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "/skill run alpha --help"}],
            "page_context": {"path": "/", "active_tab": "wizard", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert "runner ok" in str(body["reply"]["content"])
    assert body["tool_result"]["command"] == "run"
    assert body["tool_result"]["skill"] == "alpha"
