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
from dashboard.services import ai_chat


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
