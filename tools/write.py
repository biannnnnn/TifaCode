from __future__ import annotations

from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult


class WriteTool(Tool):
    name = "write"
    description = "写入文件。如果文件已存在则覆盖，不存在则创建（含父目录）。"
    parameters = {
        "file_path": {
            "type": "string",
            "description": "要写入的文件绝对路径",
        },
        "content": {
            "type": "string",
            "description": "要写入的文件内容",
        },
    }

    async def execute(self, file_path: str, content: str, **kwargs: Any) -> ToolResult:
        p = Path(file_path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            size = len(content.encode("utf-8"))
            return ToolResult.ok(
                f"已写入 {p} ({len(content)} 字符, {size} 字节)",
                file_path=str(p),
                chars=len(content),
                bytes=size,
            )
        except Exception as e:
            return ToolResult.fail(
                f"写入文件出错：{e}",
                error_code="write_error",
                file_path=file_path,
                exception_type=type(e).__name__,
            )
