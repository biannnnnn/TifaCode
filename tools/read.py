from __future__ import annotations

from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult


class ReadTool(Tool):
    name = "read"
    description = "读取文件内容。支持通过 offset/limit 指定行号范围。"
    required_parameters = ["file_path"]
    parameters = {
        "file_path": {
            "type": "string",
            "description": "要读取的文件绝对路径",
        },
        "offset": {
            "type": "integer",
            "description": "起始行号（从 1 开始），不指定则从第 1 行开始",
        },
        "limit": {
            "type": "integer",
            "description": "读取的行数，不指定则读取全部",
        },
    }

    async def execute(self, file_path: str, offset: int = 0, limit: int = 0, **kwargs: Any) -> ToolResult:
        p = Path(file_path)
        if not p.exists():
            return ToolResult.fail(f"文件不存在 '{file_path}'", error_code="file_not_found", file_path=file_path)
        if not p.is_file():
            return ToolResult.fail(f"路径不是文件 '{file_path}'", error_code="not_file", file_path=file_path)

        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            return ToolResult.fail(
                f"读取文件出错：{e}",
                error_code="read_error",
                file_path=file_path,
                exception_type=type(e).__name__,
            )

        total = len(lines)
        start = max(0, offset - 1) if offset > 0 else 0
        end = min(total, start + limit) if limit > 0 else total
        selected = lines[start:end]

        output: list[str] = []
        for i, line in enumerate(selected, start=start + 1):
            output.append(f"{i}\t{line}")
        return ToolResult.ok(
            "\n".join(output),
            file_path=file_path,
            total_lines=total,
            start_line=start + 1,
            returned_lines=len(selected),
        )
