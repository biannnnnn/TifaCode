from __future__ import annotations

from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult


class GlobTool(Tool):
    name = "glob"
    description = "文件模式匹配，返回匹配的文件路径列表。"
    required_parameters = ["pattern"]
    parameters = {
        "pattern": {
            "type": "string",
            "description": "glob 模式，如 'src/**/*.py' 或 '*.md'",
        },
        "base_dir": {
            "type": "string",
            "description": "搜索基准目录（默认为当前工作目录）",
        },
        "max_results": {
            "type": "integer",
            "description": "最大返回结果数（默认 200）",
        },
    }

    async def execute(
        self,
        pattern: str,
        base_dir: str = "",
        max_results: int = 200,
        **kwargs: Any,
    ) -> ToolResult:
        root = Path(base_dir) if base_dir else Path.cwd()
        if not root.exists():
            return ToolResult.fail(f"目录不存在 '{root}'", error_code="not_found", base_dir=str(root))
        if not root.is_dir():
            return ToolResult.fail(f"路径不是目录 '{root}'", error_code="not_directory", base_dir=str(root))

        try:
            entries = list(root.glob(pattern))
        except Exception as e:
            return ToolResult.fail(f"glob 匹配出错：{e}", error_code="glob_error", pattern=pattern)

        entries.sort()
        if len(entries) > max_results:
            entries = entries[:max_results]

        lines: list[str] = []
        for entry in entries:
            try:
                rel = entry.relative_to(Path.cwd())
            except ValueError:
                rel = entry
            lines.append(str(rel))

        if not lines:
            return ToolResult.ok("(无匹配文件)", pattern=pattern, base_dir=str(root), match_count=0)

        if len(lines) >= max_results:
            lines.append(f"...(已截断，仅显示前 {max_results} 条)")

        return ToolResult.ok(
            "\n".join(lines),
            pattern=pattern,
            base_dir=str(root),
            match_count=len(entries),
        )
