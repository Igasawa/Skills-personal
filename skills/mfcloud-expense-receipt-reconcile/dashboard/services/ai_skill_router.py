from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import secrets
from typing import Any

from services import ai_chat
from services import ai_skill_tools

PLAN_BLOCK_BEGIN = "[AX_SKILL_PLAN]"
PLAN_BLOCK_END = "[/AX_SKILL_PLAN]"
PLAN_TTL_MINUTES = 30

MAX_ROUTER_HISTORY = 12
MAX_ROUTER_SKILLS = 60
MAX_ARGS = 40
MAX_ARG_CHARS = 200
MAX_RUNNERLESS_GUIDANCE_STEPS = 6

_CONTROL_CONFIRM_PREFIX = "/confirm"
_CONTROL_CANCEL_PREFIX = "/cancel"
_CONTROL_CONFIRM_JA = {
    "\u5b9f\u884c",  # 実行
    "\u5b9f\u884c\u3057\u3066",  # 実行して
    "\u5b9f\u884c\u3057\u3066\u304f\u3060\u3055\u3044",  # 実行してください
    "\u5b9f\u65bd",  # 実施
}
_CONTROL_CANCEL_JA = {
    "\u30ad\u30e3\u30f3\u30bb\u30eb",  # キャンセル
    "\u53d6\u308a\u6d88\u3057",  # 取り消し
    "\u4e2d\u6b62",  # 中止
}
_SKILL_HINTS = (
    "skill",
    "run",
    "execute",
    "playwright",
    "kintone",
    "runner",
    "\u30b9\u30ad\u30eb",
    "\u5b9f\u884c",
    "\u8d77\u52d5",
)
_WRITE_INTENT_HINTS = (
    "--apply",
    "--post",
    "--delete",
    "--remove",
    "--update",
    "--upsert",
    "--action",
    "\u66f4\u65b0",  # 更新
    "\u767b\u9332",  # 登録
    "\u524a\u9664",  # 削除
)
_ARG_ALIASES_BY_SKILL: dict[str, dict[str, str]] = {
    "playwright": {
        "self-check": "--self-check",
        "self_check": "--self-check",
        "selfcheck": "--self-check",
        "test": "--self-check",
    }
}
_SKILL_STEP_PATTERN = re.compile(r"^\s*(?:[-*+]|[0-9]{1,2}[.)])\s+(.*\S)\s*$")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_local_skill_response(text: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "provider": "local-skill",
        "model": "local-skill",
        "reply": {"role": "assistant", "content": text},
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    if metadata:
        payload["tool_result"] = metadata
    return payload


def _format_skill_result(result: dict[str, Any]) -> str:
    lines = [
        f"skill: {result.get('skill')}",
        f"returncode: {result.get('returncode')}",
        f"duration_ms: {result.get('duration_ms')}",
    ]
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    if stdout:
        lines.append("stdout:")
        lines.append(stdout)
    if stderr:
        lines.append("stderr:")
        lines.append(stderr)
    if not stdout and not stderr:
        lines.append("(no output)")
    return "\n".join(lines)


def _normalize_args(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        arg = str(item).strip()
        if not arg or len(arg) > MAX_ARG_CHARS or "\n" in arg or "\r" in arg:
            continue
        out.append(arg)
        if len(out) >= MAX_ARGS:
            break
    return out


def _normalize_skill_args(*, skill_id: str, args: list[str]) -> list[str]:
    sid = str(skill_id or "").strip().lower()
    aliases = _ARG_ALIASES_BY_SKILL.get(sid)
    if not aliases:
        return args
    out: list[str] = []
    for arg in args:
        lowered = str(arg or "").strip().lower()
        out.append(aliases.get(lowered, arg))
    return out


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except Exception:
        return path.read_text(encoding="utf-8", errors="ignore")


def _strip_front_matter(raw: str) -> str:
    lines = str(raw or "").splitlines()
    if not lines or lines[0].strip() != "---":
        return str(raw or "")
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[idx + 1 :])
    return str(raw or "")


def _extract_skill_md_steps(skill_md: str) -> list[str]:
    path = Path(str(skill_md or "").strip())
    if not str(path) or not path.exists() or not path.is_file():
        return []
    body = _strip_front_matter(_read_text(path))
    out: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        m = _SKILL_STEP_PATTERN.match(line)
        if not m:
            continue
        text = re.sub(r"\s+", " ", str(m.group(1) or "")).strip()
        if not text:
            continue
        if len(text) > 180:
            text = text[:177] + "..."
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= MAX_RUNNERLESS_GUIDANCE_STEPS:
            break
    return out


def _safe_json_load(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text.strip())
    try:
        parsed = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except Exception:
            return None
    return parsed if isinstance(parsed, dict) else None


def _parse_iso_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_plan_payload(text: str) -> dict[str, Any] | None:
    raw = str(text or "")
    start = raw.find(PLAN_BLOCK_BEGIN)
    if start < 0:
        return None
    end = raw.find(PLAN_BLOCK_END, start + len(PLAN_BLOCK_BEGIN))
    if end < 0:
        return None
    inner = raw[start + len(PLAN_BLOCK_BEGIN) : end].strip()
    parsed = _safe_json_load(inner)
    if not parsed:
        return None
    token = str(parsed.get("token") or "").strip()
    skill = str(parsed.get("skill") or "").strip().lower()
    args = _normalize_args(parsed.get("args"))
    if not args and isinstance(parsed.get("args_json"), str):
        try:
            args = _normalize_args(json.loads(str(parsed.get("args_json"))))
        except Exception:
            args = []
    expires_at = str(parsed.get("expires_at") or "").strip()
    if not token or not skill or not expires_at:
        return None
    return {
        "token": token,
        "skill": skill,
        "args": args,
        "expires_at": expires_at,
        "write_intent": bool(parsed.get("write_intent")),
    }


def _collect_pending_plans(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for row in messages:
        if str(row.get("role") or "").strip().lower() != "assistant":
            continue
        payload = _extract_plan_payload(str(row.get("content") or ""))
        if payload:
            plans.append(payload)
    return plans


def _parse_control_intent(text: str) -> tuple[str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return None, None
    lowered = raw.lower()
    if lowered.startswith(_CONTROL_CONFIRM_PREFIX):
        tokens = raw.split(maxsplit=1)
        token = tokens[1].strip() if len(tokens) == 2 else None
        return "confirm", token or None
    if lowered.startswith(_CONTROL_CANCEL_PREFIX):
        tokens = raw.split(maxsplit=1)
        token = tokens[1].strip() if len(tokens) == 2 else None
        return "cancel", token or None
    if raw in _CONTROL_CONFIRM_JA:
        return "confirm", None
    if raw in _CONTROL_CANCEL_JA:
        return "cancel", None
    return None, None


def _find_latest_plan(plans: list[dict[str, Any]], token: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not plans:
        return None, "No pending skill proposal was found."
    if token:
        wanted = str(token).strip()
        for row in reversed(plans):
            if str(row.get("token") or "").strip() == wanted:
                return row, None
        return None, f"Proposal token was not found: {wanted}"
    if len(plans) > 1:
        return None, "Multiple proposals are pending. Please specify token: /confirm <token> or /cancel <token>."
    return plans[-1], None


def _infer_write_intent(*, latest_user_text: str, args: list[str], selected_skill_id: str, model_flag: Any) -> bool:
    if bool(model_flag):
        return True
    if selected_skill_id.startswith("kintone-record-crud"):
        return True
    lowered_user = str(latest_user_text or "").lower()
    lowered_args = [str(item or "").lower() for item in args]
    if any(hint in lowered_user for hint in _WRITE_INTENT_HINTS):
        return True
    if any(arg in {"add", "update", "upsert", "--apply", "--post", "--delete"} for arg in lowered_args):
        return True
    return any(hint in " ".join(lowered_args) for hint in _WRITE_INTENT_HINTS)


def _skill_catalog(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in skills[:MAX_ROUTER_SKILLS]:
        out.append(
            {
                "id": str(row.get("id") or "").strip().lower(),
                "description": str(row.get("description") or "").strip()[:220],
                "has_runner": bool(row.get("has_runner")),
                "allowed": bool(row.get("allowed")),
            }
        )
    return out


def _build_selector_prompt(
    *,
    latest_user_text: str,
    messages: list[dict[str, str]],
    page_context: dict[str, str],
    skills: list[dict[str, Any]],
) -> str:
    history = [
        {"role": str(row.get("role") or ""), "content": str(row.get("content") or "")[:500]}
        for row in messages[-MAX_ROUTER_HISTORY:]
    ]
    prompt = {
        "task": "Select exactly one skill and args when the request is executable; otherwise fallback.",
        "output_schema": {
            "mode": "select|fallback",
            "skill_id": "string",
            "args": ["string"],
            "write_intent": "boolean",
            "reason": "string",
        },
        "rules": [
            "Return one JSON object only.",
            "If request is ambiguous or cannot be safely mapped, use mode='fallback'.",
            "Do not invent unavailable skills.",
            "If selected skill has has_runner=false or allowed=false, still return mode='select' with that skill_id.",
            "Keep args concise and valid for CLI use.",
        ],
        "latest_user_message": latest_user_text,
        "recent_messages": history,
        "page_context": page_context,
        "skills": _skill_catalog(skills),
    }
    return json.dumps(prompt, ensure_ascii=False)


def _select_skill_with_model(
    *,
    latest_user_text: str,
    messages: list[dict[str, str]],
    page_context: dict[str, str],
    skills: list[dict[str, Any]],
) -> dict[str, Any] | None:
    prompt = _build_selector_prompt(
        latest_user_text=latest_user_text,
        messages=messages,
        page_context=page_context,
        skills=skills,
    )
    try:
        model_result = ai_chat.chat(
            messages=[{"role": "user", "content": prompt}],
            page_context=page_context,
            policy_profile=ai_chat.POLICY_PROFILE_STRUCTURED_JSON,
        )
    except Exception:
        return None
    decision = _safe_json_load((model_result.get("reply") or {}).get("content"))
    if not decision:
        return None
    mode = str(decision.get("mode") or "").strip().lower()
    if mode != "select":
        return None
    skill_id = str(decision.get("skill_id") or "").strip().lower()
    if not skill_id:
        return None
    return {
        "skill_id": skill_id,
        "args": _normalize_args(decision.get("args")),
        "write_intent": bool(decision.get("write_intent")),
        "reason": str(decision.get("reason") or "").strip(),
    }


def _find_skill(skills: list[dict[str, Any]], skill_id: str) -> dict[str, Any] | None:
    wanted = str(skill_id or "").strip().lower()
    for row in skills:
        if str(row.get("id") or "").strip().lower() == wanted:
            return row
    return None


def _suggest_alternatives(skill_id: str, skills: list[dict[str, Any]]) -> list[str]:
    wanted = str(skill_id or "").strip().lower()
    family = wanted.split("-", 1)[0] if "-" in wanted else wanted
    suggestions: list[str] = []
    for row in skills:
        sid = str(row.get("id") or "").strip().lower()
        if not sid or sid == wanted:
            continue
        if not bool(row.get("has_runner")) or not bool(row.get("allowed")):
            continue
        if family and family in sid:
            suggestions.append(sid)
    if suggestions:
        return suggestions[:5]
    for row in skills:
        sid = str(row.get("id") or "").strip().lower()
        if sid and bool(row.get("has_runner")) and bool(row.get("allowed")):
            suggestions.append(sid)
        if len(suggestions) >= 5:
            break
    return suggestions


def _build_runnerless_advice(
    *,
    selected_skill: dict[str, Any],
    skills: list[dict[str, Any]],
    reason: str | None = None,
) -> dict[str, Any]:
    sid = str(selected_skill.get("id") or "").strip().lower()
    skill_md = str(selected_skill.get("skill_md") or "").strip()
    lines = [
        f"Selected skill cannot be auto-executed: {sid}",
        "Reason: this skill has no API runner (scripts/run.py|run.ps1|run.mjs|run.js).",
        "Use SKILL.md-based guidance for this skill, or run one of the alternatives below.",
    ]
    if skill_md:
        lines.append(f"SKILL.md: {skill_md}")
    steps = _extract_skill_md_steps(skill_md)
    if steps:
        lines.append("Suggested manual steps (from SKILL.md):")
        for idx, step in enumerate(steps, start=1):
            lines.append(f"{idx}. {step}")
    else:
        lines.append("Manual guidance was not extracted. Open SKILL.md and follow its usage/workflow sections.")
    if reason:
        lines.append(f"Router reason: {reason}")
    alternatives = _suggest_alternatives(sid, skills)
    if alternatives:
        lines.append("Alternatives:")
        for alt in alternatives:
            lines.append(f"- {alt}")
    return _build_local_skill_response(
        "\n".join(lines),
        metadata={"command": "advise_runnerless", "skill": sid, "alternatives": alternatives},
    )


def _build_not_allowed_response(*, selected_skill: dict[str, Any]) -> dict[str, Any]:
    sid = str(selected_skill.get("id") or "").strip().lower()
    return _build_local_skill_response(
        f"Skill is currently blocked by permission policy: {sid}",
        metadata={"command": "cancel", "skill": sid, "reason": "not_allowed"},
    )


def _build_proposal_response(*, selected_skill: dict[str, Any], args: list[str], write_intent: bool) -> dict[str, Any]:
    token = secrets.token_hex(8)
    expires_at = (_now_utc() + timedelta(minutes=PLAN_TTL_MINUTES)).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    skill_id = str(selected_skill.get("id") or "").strip().lower()
    plan_payload = {
        "token": token,
        "skill": skill_id,
        "args": args,
        "args_json": json.dumps(args, ensure_ascii=False),
        "expires_at": expires_at,
        "write_intent": bool(write_intent),
    }
    lines = [
        "実行計画を作成しました。",
        f"対象スキル: {skill_id}",
        f"実行引数: {json.dumps(args, ensure_ascii=False)}",
        f"有効期限: {expires_at}",
        f"実行: /confirm {token} (\u5b9f\u884c / \u5b9f\u884c\u3057\u3066)",
        f"キャンセル: /cancel {token} (\u30ad\u30e3\u30f3\u30bb\u30eb)",
        PLAN_BLOCK_BEGIN,
        json.dumps(plan_payload, ensure_ascii=False),
        PLAN_BLOCK_END,
    ]
    return _build_local_skill_response(
        "\n".join(lines),
        metadata={
            "command": "propose",
            "skill": skill_id,
            "args": args,
            "token": token,
            "expires_at": expires_at,
            "write_intent": bool(write_intent),
        },
    )


def _build_cancel_response(*, token: str, reason: str | None = None) -> dict[str, Any]:
    lines = [f"実行計画をキャンセルしました。 token={token}"]
    if reason:
        lines.append(f"理由: {reason}")
    return _build_local_skill_response(
        "\n".join(lines),
        metadata={"command": "cancel", "token": token, "reason": reason},
    )


def _build_confirm_error_response(message: str) -> dict[str, Any]:
    return _build_local_skill_response(message)


def _should_try_skill_routing(*, latest_user_text: str, skills: list[dict[str, Any]]) -> bool:
    raw = str(latest_user_text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    if lowered.startswith("/"):
        return False
    if any(hint in lowered for hint in _SKILL_HINTS):
        return True
    skill_ids = [str(row.get("id") or "").strip().lower() for row in skills]
    return any(skill_id and skill_id in lowered for skill_id in skill_ids)


def _handle_control_flow(*, messages: list[dict[str, str]], latest_user_text: str) -> dict[str, Any] | None:
    action, token = _parse_control_intent(latest_user_text)
    if not action:
        return None

    plans = _collect_pending_plans(messages)
    plan, error = _find_latest_plan(plans, token)
    if error:
        return _build_confirm_error_response(error)
    if not plan:
        return _build_confirm_error_response("No pending skill proposal was found.")

    resolved_token = str(plan.get("token") or "")
    if action == "cancel":
        return _build_cancel_response(token=resolved_token)

    expires_at = _parse_iso_utc(str(plan.get("expires_at") or ""))
    if not expires_at or _now_utc() > expires_at:
        return _build_cancel_response(token=resolved_token, reason="expired")

    skill_id = str(plan.get("skill") or "").strip().lower()
    args = _normalize_args(plan.get("args"))
    args = _normalize_skill_args(skill_id=skill_id, args=args)
    try:
        result = ai_skill_tools.execute_skill(skill_id=skill_id, args=args)
    except ai_skill_tools.SkillNotExecutableError:
        all_skills = ai_skill_tools.list_skills()
        selected = _find_skill(all_skills, skill_id) or {"id": skill_id, "has_runner": False, "allowed": False}
        return _build_runnerless_advice(selected_skill=selected, skills=all_skills, reason="runner_missing")
    except ai_skill_tools.SkillNotFoundError as exc:
        return _build_confirm_error_response(str(exc))
    except ai_skill_tools.SkillNotAllowedError as exc:
        return _build_confirm_error_response(str(exc))
    except ai_skill_tools.SkillExecutionTimeoutError as exc:
        return _build_confirm_error_response(str(exc))
    except ai_skill_tools.SkillInvalidArgumentsError as exc:
        return _build_confirm_error_response(str(exc))
    except ai_skill_tools.SkillError as exc:
        return _build_confirm_error_response(str(exc))

    return _build_local_skill_response(
        _format_skill_result(result),
        metadata={
            "command": "execute",
            "skill": skill_id,
            "returncode": result.get("returncode"),
            "token": resolved_token,
        },
    )


def _route_proposal(*, messages: list[dict[str, str]], page_context: dict[str, str], latest_user_text: str) -> dict[str, Any] | None:
    skills = ai_skill_tools.list_skills()
    if not skills:
        return None
    if not _should_try_skill_routing(latest_user_text=latest_user_text, skills=skills):
        return None

    decision = _select_skill_with_model(
        latest_user_text=latest_user_text,
        messages=messages,
        page_context=page_context,
        skills=skills,
    )
    if not decision:
        return None
    selected = _find_skill(skills, str(decision.get("skill_id") or ""))
    if not selected:
        return None
    if not bool(selected.get("has_runner")):
        return _build_runnerless_advice(
            selected_skill=selected,
            skills=skills,
            reason=str(decision.get("reason") or "").strip() or None,
        )
    if not bool(selected.get("allowed")):
        return _build_not_allowed_response(selected_skill=selected)

    args = _normalize_args(decision.get("args"))
    args = _normalize_skill_args(skill_id=str(selected.get("id") or ""), args=args)
    write_intent = _infer_write_intent(
        latest_user_text=latest_user_text,
        args=args,
        selected_skill_id=str(selected.get("id") or ""),
        model_flag=decision.get("write_intent"),
    )
    return _build_proposal_response(selected_skill=selected, args=args, write_intent=write_intent)


def route_chat(*, messages: list[dict[str, str]], page_context: dict[str, str]) -> dict[str, Any] | None:
    if not messages:
        return None
    latest = messages[-1]
    latest_user_text = str(latest.get("content") or "").strip()
    if not latest_user_text:
        return None

    control_response = _handle_control_flow(messages=messages, latest_user_text=latest_user_text)
    if control_response is not None:
        return control_response
    return _route_proposal(messages=messages, page_context=page_context, latest_user_text=latest_user_text)
