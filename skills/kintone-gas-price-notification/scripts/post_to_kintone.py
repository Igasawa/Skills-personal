#!/usr/bin/env python3
"""
kintoneのスペーススレッドにコメントを投稿するスクリプト

注意: スペース/スレッドAPIはAPIトークン認証をサポートしていません。
通常はパスワード認証（ユーザーID + パスワード）を使用し、
認証情報が空の場合は保存済みログインセッション（storage_state）へフォールバックします。
"""

from __future__ import annotations

import base64
import getpass
import json
import os
from pathlib import Path
import sys
from typing import Any


REQUEST_TIMEOUT = 30
DEFAULT_SESSION_NAME = "kintone"


def _normalize_secret(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _default_storage_state_path(session_name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in session_name)
    return _ax_home() / "sessions" / f"{safe}.storage.json"


def _resolve_storage_state_path(storage_state_path: str | None, session_name: str) -> Path:
    if storage_state_path:
        return Path(storage_state_path).expanduser()
    return _default_storage_state_path(session_name)


def _load_storage_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(
            "セッションフォールバックに必要な storage_state が見つかりません: "
            f"{path}"
        )
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"storage_state の形式が不正です: {path}")
    return data


def _host_matches(cookie_domain: str, target_host: str) -> bool:
    left = cookie_domain.lstrip(".").lower()
    host = target_host.lower()
    return host == left or host.endswith(f".{left}")


def _attach_storage_cookies(session: Any, storage_state: dict[str, Any], target_host: str) -> int:
    cookies = storage_state.get("cookies")
    if not isinstance(cookies, list):
        return 0

    attached = 0
    for c in cookies:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain")
        path = c.get("path") or "/"
        if not isinstance(name, str) or not isinstance(value, str) or not isinstance(domain, str):
            continue
        if not _host_matches(domain, target_host):
            continue
        session.cookies.set(name, value, domain=domain, path=path)
        attached += 1
    return attached


def get_credentials(username: str = None, password: str = None) -> tuple[str | None, str | None]:
    """
    認証情報を取得（優先順位: 引数 → 環境変数 → 対話入力）
    """
    username = _normalize_secret(username) or _normalize_secret(os.environ.get("KINTONE_USERNAME"))
    if username is None:
        username = _normalize_secret(input("kintoneログイン名: "))

    password = _normalize_secret(password) or _normalize_secret(os.environ.get("KINTONE_PASSWORD"))
    if password is None:
        password = _normalize_secret(getpass.getpass("kintoneパスワード: "))

    return username, password


def _post_with_password_auth(
    subdomain: str,
    space_id: int,
    thread_id: int,
    comment_text: str,
    *,
    username: str,
    password: str,
) -> dict[str, Any]:
    import requests

    url = f"https://{subdomain}.cybozu.com/k/v1/space/thread/comment.json"
    auth_string = f"{username}:{password}"
    auth_base64 = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")

    headers = {
        "X-Cybozu-Authorization": auth_base64,
        "Content-Type": "application/json",
    }
    payload = {"space": space_id, "thread": thread_id, "comment": {"text": comment_text}}

    response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        data.setdefault("_auth", "password")
    return data


def _fetch_csrf_token(session: Any, base_url: str) -> str:
    token_url = f"{base_url}/k/v1/csrfToken.json"
    headers = {"X-Requested-With": "XMLHttpRequest"}
    response = session.get(token_url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("CSRFトークン取得レスポンスが不正です")

    token = (
        data.get("token")
        or data.get("csrfToken")
        or data.get("__REQUEST_TOKEN__")
    )
    token = _normalize_secret(token if isinstance(token, str) else None)
    if token is None:
        raise ValueError("CSRFトークンを取得できませんでした")
    return token


def _post_with_session_fallback(
    subdomain: str,
    space_id: int,
    thread_id: int,
    comment_text: str,
    *,
    session_name: str,
    storage_state_path: str | None,
) -> dict[str, Any]:
    import requests

    base_url = f"https://{subdomain}.cybozu.com"
    target_host = f"{subdomain}.cybozu.com"
    state_path = _resolve_storage_state_path(storage_state_path, session_name)
    state = _load_storage_state(state_path)

    with requests.Session() as sess:
        attached = _attach_storage_cookies(sess, state, target_host)
        if attached == 0:
            raise ValueError(
                "storage_state に対象ドメインのCookieが見つかりません。"
                f"session_name={session_name}, file={state_path}"
            )

        token = _fetch_csrf_token(sess, base_url)
        headers = {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-Cybozu-Request-Token": token,
        }
        payload = {"space": space_id, "thread": thread_id, "comment": {"text": comment_text}}
        url = f"{base_url}/k/v1/space/thread/comment.json"
        response = sess.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            data.setdefault("_auth", "session")
            data.setdefault("_session_name", session_name)
            data.setdefault("_storage_state", str(state_path))
        return data


def post_thread_comment(
    subdomain: str,
    space_id: int,
    thread_id: int,
    comment_text: str,
    username: str = None,
    password: str = None,
    interactive: bool = True,
    allow_session_fallback: bool = True,
    session_name: str = DEFAULT_SESSION_NAME,
    storage_state_path: str | None = None,
) -> dict:
    """
    kintoneのスレッドにコメントを投稿。

    認証優先順位:
    1. username/password（引数 or 環境変数）
    2. 保存済みログインセッション（storage_state）
    3. interactive=True の場合のみ対話入力
    """
    import requests

    try:
        if interactive:
            username, password = get_credentials(username, password)
        else:
            username = _normalize_secret(username) or _normalize_secret(os.environ.get("KINTONE_USERNAME"))
            password = _normalize_secret(password) or _normalize_secret(os.environ.get("KINTONE_PASSWORD"))

        username = _normalize_secret(username)
        password = _normalize_secret(password)

        if username and password:
            return _post_with_password_auth(
                subdomain,
                space_id,
                thread_id,
                comment_text,
                username=username,
                password=password,
            )

        if allow_session_fallback:
            return _post_with_session_fallback(
                subdomain,
                space_id,
                thread_id,
                comment_text,
                session_name=session_name,
                storage_state_path=storage_state_path,
            )

        raise ValueError(
            "認証情報が設定されていません。"
            "環境変数 KINTONE_USERNAME と KINTONE_PASSWORD を設定するか、"
            "allow_session_fallback=True でセッションフォールバックを有効にしてください。"
        )
    except requests.RequestException as e:
        raise Exception(f"kintoneへの投稿に失敗しました: {e}") from e


def main():
    """メイン処理"""
    if len(sys.argv) < 5:
        print("使用方法: post_to_kintone.py <subdomain> <space_id> <thread_id> <comment>")
        print("例: post_to_kintone.py 5atx9 24 36 'テストコメント'")
        print()
        print("認証情報の優先順位:")
        print("  1. 環境変数 KINTONE_USERNAME, KINTONE_PASSWORD")
        print("  2. 保存済みログインセッション (~/.ax/sessions/kintone.storage.json)")
        print("  3. 対話入力（環境変数がない場合）")
        sys.exit(1)

    subdomain = sys.argv[1]
    space_id = int(sys.argv[2])
    thread_id = int(sys.argv[3])
    comment = sys.argv[4]

    has_username = bool(_normalize_secret(os.environ.get("KINTONE_USERNAME")))
    has_password = bool(_normalize_secret(os.environ.get("KINTONE_PASSWORD")))
    if has_username and has_password:
        print("✓ 認証情報を環境変数から取得します")
    else:
        print("環境変数が未設定のため、セッションフォールバックまたは対話入力を使用します")

    try:
        result = post_thread_comment(subdomain, space_id, thread_id, comment)
        auth_mode = result.get("_auth")
        if auth_mode:
            print(f"✓ 認証方式: {auth_mode}")
        print(f"✓ 投稿成功: コメントID = {result.get('id')}")
    except Exception as e:
        print(f"✗ エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
