"""Prompt templates and helpers for KIL commit analysis."""

import json
from typing import Any, Dict, List


def _to_bulleted_list(values: List[str], max_items: int = 20) -> str:
    if not values:
        return "- (none)\n"
    limited = values[:max_items]
    return "\n".join(f"- {v}" for v in limited) + ("\n" if limited else "")


def build_kil_prompt(context: Dict[str, Any]) -> str:
    commit = context.get("commit", {})
    files = context.get("changed_files", [])
    patch = context.get("patch_excerpt", "")
    confidence_hint = context.get("confidence_hint", "normal")

    changed = "\n".join(
        f"- {item.get('status', '?')} {item.get('path', '(unknown)')}"
        for item in files
    )
    if not changed:
        changed = "- (no path changes detected)"

    patch_lines = patch.splitlines()
    patch_preview = "\n".join(patch_lines[:420])
    if len(patch_lines) > 420:
        patch_preview += "\n... (truncated ...)"

    return (
        "あなたは Knowledge Integration Loop (KIL) のコミット知識抽出エージェントです。\n"
        "この差分から、エージェントが次回の判断に再利用できる\n"
        "運用知識（再利用方針・制約・未解決事項）だけを抽出してください。\n\n"
        "インプット:\n"
        f"- Commit: {commit.get('hash','unknown')}\n"
        f"- Author: {commit.get('author','unknown')} <{commit.get('email','unknown')}>\n"
        f"- Date: {commit.get('date','unknown')}\n"
        f"- Message: {commit.get('subject','')}\n"
        "- Message body:\n"
        f"{json.dumps(commit.get('body',''), ensure_ascii=False)}\n"
        "- Changed files:\n"
        f"{changed}\n"
        "- Patch excerpt:\n"
        "```diff\n"
        f"{patch_preview}\n"
        "```\n\n"
        f"- 優先度ヒント: {confidence_hint}\n\n"
        "出力ルール:\n"
        "厳密に JSON のみを返してください。説明文・Markdown・前置きは不要です。\n"
        "値のテキストは日本語（自然文）で出力してください。\n"
        "キーは固定で以下を必ず含めてください。\n"
        '{\n'
        '  "summary": "string",\n'
        '  "intent": "string",\n'
        '  "new_rules": ["string", "..."],\n'
        '  "anti_patterns": ["string", "..."],\n'
        '  "debt": ["string", "..."],\n'
        '  "scope": ["string", "..."],\n'
        '  "confidence": 0.0,\n'
        '  "risk": "low|medium|high",\n'
        '  "review_deadline": "YYYY-MM-DD または null"\n'
        "}\n"
    )
