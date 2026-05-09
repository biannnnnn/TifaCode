from __future__ import annotations

from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult


class ListTool(Tool):
    name = "list"
    description = "列出目录内容，支持递归深度控制和 glob 过滤。"
    required_parameters = ["path"]
    parameters = {
        "path": {
            "type": "string",
            "description": "要列出的目录绝对路径",
        },
        "recursive": {
            "type": "boolean",
            "description": "是否递归列出子目录（默认 false）",
        },
        "max_depth": {
            "type": "integer",
            "description": "递归最大深度（默认 3，仅 recursive=true 时生效）",
        },
        "glob_pattern": {
            "type": "string",
            "description": "glob 过滤模式，如 '*.py' 或 '**/*.ts'",
        },
        "max_entries": {
            "type": "integer",
            "description": "最大返回条目数（默认 200）",
        },
    }

    async def execute(
        self,
        path: str,
        recursive: bool = False,
        max_depth: int = 3,
        glob_pattern: str = "",
        max_entries: int = 200,
        **kwargs: Any,
    ) -> ToolResult:
        p = Path(path)
        if not p.exists():
            return ToolResult.fail(f"目录不存在 '{path}'", error_code="not_found", path=path)
        if not p.is_dir():
            return ToolResult.fail(f"路径不是目录 '{path}'", error_code="not_directory", path=path)

        try:
            if glob_pattern:
                pattern = f"**/{glob_pattern}" if recursive else glob_pattern
                entries = list(p.glob(pattern))
            elif recursive:
                pattern = "**/*"
                entries = []
                for entry in p.glob(pattern):
                    rel = entry.relative_to(p)
                    depth = len(rel.parts)
                    if depth <= max_depth:
                        entries.append(entry)
            else:
                entries = list(p.iterdir())
        except PermissionError:
            return ToolResult.fail(f"无权限访问目录 '{path}'", error_code="permission_denied", path=path)
        except Exception as e:
            return ToolResult.fail(f"列出目录出错：{e}", error_code="list_error", path=path)

        entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))
        if len(entries) > max_entries:
            entries = entries[:max_entries]
            truncated = True
        else:
            truncated = False

        lines: list[str] = []
        for entry in entries:
            prefix = "📁" if entry.is_dir() else "📄"
            try:
                rel = entry.relative_to(p)
            except ValueError:
                rel = entry
            lines.append(f"{prefix} {rel}")

        if not lines:
            lines.append("(空目录)")

        if truncated:
            lines.append(f"...(已截断，共 {len(entries)} 条，仅显示前 {max_entries} 条)")

        return ToolResult.ok(
            "\n".join(lines),
            path=path,
            entry_count=len(entries),
            truncated=truncated,
            recursive=recursive,
        )
