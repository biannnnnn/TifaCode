from __future__ import annotations

from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult


class ReadManyTool(Tool):
    name = "read_many"
    description = "批量读取多个文件内容，返回合并结果。"
    required_parameters = ["file_paths"]
    parameters = {
        "file_paths": {
            "type": "array",
            "description": "要读取的文件绝对路径列表",
        },
        "max_total_lines": {
            "type": "integer",
            "description": "总计最大返回行数（默认 500）",
        },
    }

    async def execute(self, file_paths: list[str], max_total_lines: int = 500, **kwargs: Any) -> ToolResult:
        if not file_paths:
            return ToolResult.fail("file_paths 不能为空", error_code="empty_paths")

        paths = file_paths if isinstance(file_paths, list) else [str(file_paths)]
        results: list[str] = []
        total_lines = 0
        errors: list[str] = []

        for fp in paths:
            if total_lines >= max_total_lines:
                results.append(f"...(已达上限 {max_total_lines} 行，跳过剩余文件)")
                break

            p = Path(fp)
            if not p.exists():
                errors.append(f"文件不存在: {fp}")
                continue
            if not p.is_file():
                errors.append(f"不是文件: {fp}")
                continue

            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                errors.append(f"读取失败 {fp}: {e}")
                continue

            lines = content.splitlines()
            if total_lines + len(lines) > max_total_lines:
                remaining = max_total_lines - total_lines
                lines = lines[:remaining]
                content = "\n".join(lines) + "\n...(已截断)"

            try:
                rel = p.relative_to(Path.cwd())
            except ValueError:
                rel = p

            results.append(f"=== {rel} ===")
            results.append(content)
            results.append("")
            total_lines += len(lines)

        if errors:
            results.insert(0, "## 错误 ##")
            results.insert(1, "\n".join(errors))
            results.insert(2, "")

        if not results:
            return ToolResult.fail("无文件被成功读取", error_code="no_files_read")

        return ToolResult.ok(
            "\n".join(results),
            files_read=len(paths) - len(errors),
            total_lines=total_lines,
            error_count=len(errors),
        )
