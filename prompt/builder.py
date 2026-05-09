from __future__ import annotations

import logging
import os
import platform
from pathlib import Path

from tifacode.config.settings import Settings
from tifacode.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

_BASE_IDENTITY = """You are TifaCode, a coding agent that helps with software engineering tasks.
You have access to tools to read, write, edit files, and execute shell commands.
Work step by step, explain your reasoning, and use tools when needed.
Always use absolute paths when referencing files.
"""


def _find_claude_md_files(start_dir: Path) -> list[Path]:
    """从 start_dir 向上递归查找所有 CLAUDE.md 文件（靠近根目录的在前）。"""
    found: list[Path] = []
    current = start_dir.resolve()
    root = Path(current.root)
    while current != root.parent:
        candidate = current / "CLAUDE.md"
        if candidate.is_file():
            found.append(candidate)
        if current == root:
            break
        current = current.parent
    found.reverse()
    return found


def _resolve_includes(content: str, base_dir: Path, max_depth: int, _visited: set[str] | None = None) -> str:
    """递归解析 @include 指令。"""
    if _visited is None:
        _visited = set()
    if max_depth <= 0:
        return content

    lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("@include "):
            include_path = stripped[len("@include "):].strip().strip("\"'")
            resolved = (base_dir / include_path).resolve()
            key = str(resolved)
            if key in _visited:
                logger.warning("循环 @include 检测: %s", resolved)
                continue
            _visited.add(key)
            if resolved.is_file():
                try:
                    included = resolved.read_text(encoding="utf-8")
                    included = _resolve_includes(included, resolved.parent, max_depth - 1, _visited)
                    lines.append(included)
                except Exception:
                    logger.warning("无法读取 @include 文件: %s", resolved, exc_info=True)
            else:
                logger.warning("@include 文件不存在: %s", resolved)
        else:
            lines.append(line)
    return "\n".join(lines)


def _load_rules(settings: Settings) -> str:
    """加载 CLAUDE.md 和 @include 规则文件，返回合并后的文本。"""
    if not settings.claude_rules_enabled:
        return ""

    cwd = Path.cwd()
    files = _find_claude_md_files(cwd)
    if not files:
        return ""

    all_lines: list[str] = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
            content = _resolve_includes(content, f.parent, settings.claude_rules_max_depth)
            all_lines.append(f"<!-- {f} -->")
            all_lines.append(content)
        except Exception:
            logger.warning("无法读取规则文件: %s", f, exc_info=True)

    if not all_lines:
        return ""

    lines = "\n".join(all_lines).splitlines()
    if len(lines) > settings.claude_rules_max_lines:
        lines = lines[: settings.claude_rules_max_lines]
        lines.append(f"...(truncated, max {settings.claude_rules_max_lines} lines)")

    return "\n".join(lines)


def _build_tools_section(registry: ToolRegistry) -> str:
    """从 ToolRegistry 生成工具说明。"""
    tools = registry.get_schemas()
    if not tools:
        return ""
    lines = ["## Available Tools", ""]
    for t in tools:
        name = t.get("name", "unknown")
        desc = t.get("description", "")
        props = t.get("input_schema", {}).get("properties", {})
        required = t.get("input_schema", {}).get("required", [])
        lines.append(f"### {name}")
        lines.append(f"{desc}")
        if props:
            lines.append("")
            lines.append("Parameters:")
            for pname, pinfo in props.items():
                req_mark = " (required)" if pname in (required or []) else ""
                ptype = pinfo.get("type", "any")
                pdesc = pinfo.get("description", "")
                lines.append(f"  - `{pname}` ({ptype}){req_mark}: {pdesc}")
        lines.append("")
    return "\n".join(lines)


def _build_permission_section(settings: Settings) -> str:
    """生成当前权限模式说明。"""
    mode = settings.permission_mode
    allow = settings.permission_allow_tools or []
    deny = settings.permission_deny_tools or []
    allow_cmds = settings.permission_allow_commands or []
    deny_cmds = settings.permission_deny_commands or []

    lines = ["## Current Permission Mode", "", f"Mode: **{mode}**"]
    if allow:
        lines.append(f"Allowed tools: {', '.join(allow)}")
    if deny:
        lines.append(f"Denied tools: {', '.join(deny)}")
    if allow_cmds:
        lines.append(f"Allowed commands: {', '.join(allow_cmds)}")
    if deny_cmds:
        lines.append(f"Denied commands: {', '.join(deny_cmds)}")
    return "\n".join(lines)


def _build_workspace_section() -> str:
    """生成工作区上下文。"""
    cwd = Path.cwd()
    return "\n".join([
        "## Workspace",
        "",
        f"- Working directory: {cwd}",
        f"- Platform: {platform.system()} {platform.release()}",
        f"- Python: {platform.python_version()}",
    ])


class PromptBuilder:
    def __init__(self, registry: ToolRegistry, settings: Settings) -> None:
        self._registry = registry
        self._settings = settings

    def build(self) -> str:
        sections: list[str] = [_BASE_IDENTITY]

        tools = _build_tools_section(self._registry)
        if tools:
            sections.append(tools)

        permissions = _build_permission_section(self._settings)
        if permissions:
            sections.append(permissions)

        rules = _load_rules(self._settings)
        if rules:
            sections.append("## Project Rules (CLAUDE.md)")
            sections.append(rules)

        # 跨会话记忆注入
        if self._settings.cross_session_memory_enabled:
            try:
                from tifacode.agent.memory import get_memory_store
                memories = get_memory_store().inject_into_prompt()
                if memories:
                    sections.append(memories)
            except Exception:
                pass

        workspace = _build_workspace_section()
        sections.append(workspace)

        return "\n\n".join(sections)
