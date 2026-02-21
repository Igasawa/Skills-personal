from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from urllib import error as url_error

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from dashboard.routes import api as api_routes
from dashboard.routes import api_ai_chat_routes
from dashboard.services import ai_chat
from dashboard.services import ai_skill_router


class _FakeUrlResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "_FakeUrlResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _create_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(api_routes.create_api_router())
    return TestClient(app)


def _set_chat_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str | None,
    model: str | None = None,
    guardrail_mode: str | None = None,
) -> None:
    monkeypatch.setattr(ai_chat, "_SECRET_ENV_LOADED", True)
    if api_key is None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("KIL_GEMINI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GEMINI_API_KEY", api_key)
        monkeypatch.delenv("KIL_GEMINI_API_KEY", raising=False)
    if model is None:
        monkeypatch.delenv("KIL_GEMINI_MODEL", raising=False)
    else:
        monkeypatch.setenv("KIL_GEMINI_MODEL", model)
    if guardrail_mode is None:
        monkeypatch.delenv("KIL_AI_GUARDRAIL_MODE", raising=False)
    else:
        monkeypatch.setenv("KIL_AI_GUARDRAIL_MODE", guardrail_mode)


def _assistant_plan_message(
    *,
    token: str,
    skill: str = "alpha",
    args: list[str] | None = None,
    expires_at: str = "2099-01-01T00:00:00Z",
) -> str:
    payload = {
        "token": token,
        "skill": skill,
        "args": list(args or []),
        "args_json": json.dumps(list(args or []), ensure_ascii=False),
        "expires_at": expires_at,
        "write_intent": False,
    }
    return "\n".join(
        [
            "Execution plan is ready.",
            ai_skill_router.PLAN_BLOCK_BEGIN,
            json.dumps(payload, ensure_ascii=False),
            ai_skill_router.PLAN_BLOCK_END,
        ]
    )


def test_api_ai_chat_status_ready_true_when_key_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key", model="gemini-2.0-flash")

    res = client.get("/api/ai/chat/status")
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is True
    assert body["provider"] == "gemini"
    assert body["model"] == "gemini-2.0-flash"
    assert body["reason"] is None


def test_api_ai_chat_status_ready_false_when_key_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key=None)

    res = client.get("/api/ai/chat/status")
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is False
    assert body["provider"] == "gemini"
    assert body["model"] == "gemini-flash-latest"
    assert "not configured" in str(body["reason"]).lower()


def test_api_ai_chat_success_returns_reply_and_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key", model="gemini-2.0-flash")
    captured_payload: dict[str, Any] = {}

    def _fake_urlopen(req, timeout: int = 0):
        del timeout
        captured_payload.update(json.loads(req.data.decode("utf-8")))
        return _FakeUrlResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Answer A"},
                                {"text": " / Answer B"},
                            ]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 7,
                    "totalTokenCount": 19,
                },
            }
        )

    monkeypatch.setattr(ai_chat.url_request, "urlopen", _fake_urlopen)

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [
                {"role": "user", "content": "hello"},
            ],
            "page_context": {
                "path": "/workspace",
                "active_tab": "workspace",
                "title": "Automation Hub",
            },
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["provider"] == "gemini"
    assert body["model"] == "gemini-2.0-flash"
    assert body["reply"] == {"role": "assistant", "content": "Answer A / Answer B"}
    assert body["usage"] == {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}
    assert isinstance(captured_payload.get("contents"), list)
    assert len(captured_payload["contents"]) >= 2
    first_row = captured_payload["contents"][0]
    first_text = str(first_row.get("parts", [{}])[0].get("text") or "")
    assert "Response style guardrails" in first_text
    assert "Only use facts explicitly present in messages and page_context." in first_text


def test_api_ai_chat_enforce_mode_replaces_invalid_reply_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key", guardrail_mode="enforce")

    def _fake_urlopen(req, timeout: int = 0):
        del req, timeout
        return _FakeUrlResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "This answer does not follow the required section format."},
                            ]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 4,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 9,
                },
            }
        )

    monkeypatch.setattr(ai_chat.url_request, "urlopen", _fake_urlopen)

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [
                {"role": "user", "content": "確認したいです"},
            ],
            "page_context": {
                "path": "/workspace",
                "active_tab": "workspace",
                "title": "Automation Hub",
            },
        },
    )
    assert res.status_code == 200
    body = res.json()
    content = str((body.get("reply") or {}).get("content") or "")
    assert "回答:" in content
    assert "根拠:" in content
    assert "不足情報:" in content
    assert "messages[0]" in content


def test_api_ai_chat_rejects_model_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")

    res = client.post(
        "/api/ai/chat",
        json={
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "test"}],
            "page_context": {},
        },
    )
    assert res.status_code == 400
    assert "model field is not allowed" in str(res.json().get("detail") or "")


def test_api_ai_chat_rejects_invalid_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "system", "content": "test"}],
            "page_context": {},
        },
    )
    assert res.status_code == 400
    assert "must be user or assistant" in str(res.json().get("detail") or "")


def test_api_ai_chat_returns_503_when_key_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key=None)

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "test"}],
            "page_context": {},
        },
    )
    assert res.status_code == 503
    assert "not configured" in str(res.json().get("detail") or "").lower()


def test_api_ai_chat_returns_502_on_upstream_http_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")

    def _fake_urlopen(*args: Any, **kwargs: Any):
        del args, kwargs
        raise url_error.HTTPError(
            url="https://example.invalid",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"upstream"}'),
        )

    monkeypatch.setattr(ai_chat.url_request, "urlopen", _fake_urlopen)

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "test"}],
            "page_context": {},
        },
    )
    assert res.status_code == 502
    assert "Gemini API error" in str(res.json().get("detail") or "")


def test_api_ai_chat_returns_504_on_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")

    def _fake_urlopen(*args: Any, **kwargs: Any):
        del args, kwargs
        raise url_error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(ai_chat.url_request, "urlopen", _fake_urlopen)

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "test"}],
            "page_context": {},
        },
    )
    assert res.status_code == 504
    assert "timed out" in str(res.json().get("detail") or "").lower()


def test_api_ai_chat_natural_language_returns_skill_propose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "list_skills",
        lambda: [
            {
                "id": "alpha",
                "name": "alpha",
                "description": "runner skill",
                "skill_md": "x",
                "has_runner": True,
                "runner": "x",
                "allowed": True,
            }
        ],
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router,
        "_select_skill_with_model",
        lambda latest_user_text, messages, page_context, skills: {
            "skill_id": "alpha",
            "args": ["--help"],
            "write_intent": False,
            "reason": "matched",
        },
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_chat,
        "chat",
        lambda messages, page_context, policy_profile="": (_ for _ in ()).throw(RuntimeError("must not call chat")),
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "alpha を実行して"}],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "propose"
    assert body["tool_result"]["skill"] == "alpha"
    assert body["tool_result"]["args"] == ["--help"]
    assert str(body["tool_result"]["token"] or "")


def test_api_ai_chat_normalizes_playwright_self_check_arg_on_propose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "list_skills",
        lambda: [
            {
                "id": "playwright",
                "name": "playwright",
                "description": "browser automation",
                "skill_md": "x",
                "has_runner": True,
                "runner": "x",
                "allowed": True,
            }
        ],
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router,
        "_select_skill_with_model",
        lambda latest_user_text, messages, page_context, skills: {
            "skill_id": "playwright",
            "args": ["self-check"],
            "write_intent": False,
            "reason": "matched",
        },
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_chat,
        "chat",
        lambda messages, page_context, policy_profile="": (_ for _ in ()).throw(RuntimeError("must not call chat")),
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "playwright の self-check を実行して"}],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "propose"
    assert body["tool_result"]["skill"] == "playwright"
    assert body["tool_result"]["args"] == ["--self-check"]


def test_api_ai_chat_normalizes_playwright_test_arg_to_self_check_on_propose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "list_skills",
        lambda: [
            {
                "id": "playwright",
                "name": "playwright",
                "description": "browser automation",
                "skill_md": "x",
                "has_runner": True,
                "runner": "x",
                "allowed": True,
            }
        ],
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router,
        "_select_skill_with_model",
        lambda latest_user_text, messages, page_context, skills: {
            "skill_id": "playwright",
            "args": ["test"],
            "write_intent": False,
            "reason": "matched",
        },
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_chat,
        "chat",
        lambda messages, page_context, policy_profile="": (_ for _ in ()).throw(RuntimeError("must not call chat")),
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "playwright の self-check を実行して"}],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "propose"
    assert body["tool_result"]["skill"] == "playwright"
    assert body["tool_result"]["args"] == ["--self-check"]


def test_api_ai_chat_confirm_executes_pending_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    token = "tok_confirm_001"
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "execute_skill",
        lambda skill_id, args=None, timeout_seconds=None: {
            "skill": skill_id,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 5,
        },
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [
                {"role": "assistant", "content": _assistant_plan_message(token=token, skill="alpha", args=["--help"])},
                {"role": "user", "content": f"/confirm {token}"},
            ],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "execute"
    assert body["tool_result"]["skill"] == "alpha"
    assert body["tool_result"]["token"] == token


def test_api_ai_chat_confirm_normalizes_playwright_self_check_arg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    token = "tok_confirm_alias_001"
    captured: dict[str, Any] = {}

    def _fake_execute(skill_id: str, args: list[str] | None = None, timeout_seconds: int | None = None) -> dict[str, Any]:
        del timeout_seconds
        captured["skill_id"] = skill_id
        captured["args"] = list(args or [])
        return {
            "skill": skill_id,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 5,
        }

    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "execute_skill",
        _fake_execute,
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [
                {
                    "role": "assistant",
                    "content": _assistant_plan_message(token=token, skill="playwright", args=["self-check"]),
                },
                {"role": "user", "content": f"/confirm {token}"},
            ],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "execute"
    assert body["tool_result"]["skill"] == "playwright"
    assert body["tool_result"]["token"] == token
    assert captured["args"] == ["--self-check"]


def test_api_ai_chat_cancel_pending_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    token = "tok_cancel_001"
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "execute_skill",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("must not execute")),
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [
                {"role": "assistant", "content": _assistant_plan_message(token=token, skill="alpha")},
                {"role": "user", "content": f"/cancel {token}"},
            ],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "cancel"
    assert body["tool_result"]["token"] == token


def test_api_ai_chat_rejects_expired_confirm_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    token = "tok_expired_001"
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "execute_skill",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("must not execute")),
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [
                {
                    "role": "assistant",
                    "content": _assistant_plan_message(
                        token=token,
                        skill="alpha",
                        expires_at="2000-01-01T00:00:00Z",
                    ),
                },
                {"role": "user", "content": f"/confirm {token}"},
            ],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "cancel"
    assert body["tool_result"]["reason"] == "expired"


def test_api_ai_chat_japanese_confirm_word_executes_pending_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    token = "tok_ja_confirm_001"
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "execute_skill",
        lambda skill_id, args=None, timeout_seconds=None: {
            "skill": skill_id,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 5,
        },
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [
                {"role": "assistant", "content": _assistant_plan_message(token=token, skill="alpha")},
                {"role": "user", "content": "\u5b9f\u884c\u3057\u3066"},
            ],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "execute"
    assert body["tool_result"]["token"] == token


def test_api_ai_chat_runnerless_selection_returns_advice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    skill_md = tmp_path / "skills" / "runnerless" / "SKILL.md"
    skill_md.parent.mkdir(parents=True, exist_ok=True)
    skill_md.write_text(
        "\n".join(
            [
                "---",
                "name: runnerless",
                "---",
                "# runnerless",
                "## How to use",
                "1. Open portal page",
                "2. Export pending records as CSV",
                "- Paste the data into chat",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router.ai_skill_tools,
        "list_skills",
        lambda: [
            {
                "id": "runnerless",
                "name": "runnerless",
                "description": "no runner",
                "skill_md": str(skill_md),
                "has_runner": False,
                "runner": None,
                "allowed": False,
            },
            {
                "id": "runnerless-helper",
                "name": "runnerless-helper",
                "description": "helper",
                "skill_md": "x",
                "has_runner": True,
                "runner": "x",
                "allowed": True,
            }
        ],
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_skill_router,
        "_select_skill_with_model",
        lambda latest_user_text, messages, page_context, skills: {
            "skill_id": "runnerless",
            "args": [],
            "write_intent": False,
            "reason": "runner missing",
        },
    )
    monkeypatch.setattr(
        api_ai_chat_routes.ai_chat,
        "chat",
        lambda messages, page_context, policy_profile="": (_ for _ in ()).throw(RuntimeError("must not call chat")),
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "runnerless を実行"}],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "local-skill"
    assert body["tool_result"]["command"] == "advise_runnerless"
    assert body["tool_result"]["skill"] == "runnerless"
    content = str((body.get("reply") or {}).get("content") or "")
    assert "Suggested manual steps (from SKILL.md):" in content
    assert "1. Open portal page" in content
    assert "2. Export pending records as CSV" in content
    assert "3. Paste the data into chat" in content
    assert "runnerless-helper" in content


def test_api_ai_chat_router_fallback_calls_standard_chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_chat_env(monkeypatch, api_key="test-key")
    monkeypatch.setattr(api_ai_chat_routes.ai_skill_router, "route_chat", lambda messages, page_context: None)
    monkeypatch.setattr(
        api_ai_chat_routes.ai_chat,
        "chat",
        lambda messages, page_context, policy_profile="": {
            "provider": "gemini",
            "model": "gemini-test",
            "reply": {"role": "assistant", "content": "fallback"},
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )

    res = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "page_context": {"path": "/", "active_tab": "workspace", "title": "x"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "gemini"
    assert body["reply"]["content"] == "fallback"
