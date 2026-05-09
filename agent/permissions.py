from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from typing import Any

from tifacode.config.settings import Settings

PERMISSION_MODES = ("default", "plan", "acceptEdits", "bypassPermissions", "dontAsk")

TOOL_RISK = {
    "read": "read",
    "write": "write",
    "edit": "write",
    "bash": "execute",
    "list": "read",
    "grep": "read",
    "glob": "read",
    "tree": "read",
    "todo": "read",
    "diagnostics": "read",
    "git_status": "read",
    "git_diff": "read",
    "read_many": "read",
}


@dataclass
class PermissionDecision:
    allowed: bool
    needs_confirmation: bool = False
    reason: str = ""


def describe_tool_call(name: str, tool_input: dict[str, Any]) -> str:
    if name == "bash":
        return str(tool_input.get("command", ""))[:200]
    if name in ("read", "write", "edit"):
        return str(tool_input.get("file_path", ""))[:200]
    return ", ".join(f"{k}={v!r}" for k, v in tool_input.items())[:200]


def permission_cache_key(name: str, tool_input: dict[str, Any]) -> str:
    raw = json.dumps({"name": name, "input": tool_input}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _matches_command_rule(command: str, rules: list[str] | None) -> str | None:
    normalized = " ".join(command.strip().split())
    for rule in rules or []:
        rule = rule.strip()
        if not rule:
            continue
        if rule == normalized or rule in normalized:
            return rule
        try:
            argv = shlex.split(normalized)
        except ValueError:
            argv = normalized.split()
        if argv and argv[0] == rule:
            return rule
    return None


def decide_tool_permission(settings: Settings, name: str, tool_input: dict[str, Any]) -> PermissionDecision:
    if name == "bash":
        command = str(tool_input.get("command", ""))
        deny_rule = _matches_command_rule(command, settings.permission_deny_commands)
        if deny_rule:
            return PermissionDecision(False, reason=f"命令匹配 deny 规则: {deny_rule}")
        allow_rule = _matches_command_rule(command, settings.permission_allow_commands)
        if allow_rule:
            return PermissionDecision(True)

    if name in settings.permission_deny_tools:
        return PermissionDecision(False, reason=f"工具 '{name}' 被 deny 规则拒绝")

    if name in settings.permission_allow_tools:
        return PermissionDecision(True)

    risk = TOOL_RISK.get(name, "write")
    mode = settings.permission_mode

    if risk == "read":
        return PermissionDecision(True)

    if mode == "bypassPermissions":
        return PermissionDecision(True)

    if mode == "plan":
        return PermissionDecision(False, reason=f"plan 模式禁止执行 {risk} 类工具 '{name}'")

    if mode == "dontAsk":
        return PermissionDecision(False, reason=f"dontAsk 模式禁止需要确认的工具 '{name}'")

    if mode == "acceptEdits" and risk == "write":
        return PermissionDecision(True)

    return PermissionDecision(True, needs_confirmation=True, reason=f"{risk} 类工具需要用户确认")
