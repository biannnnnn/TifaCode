from __future__ import annotations

from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult


class EditTool(Tool):
    name = "edit"
    description = "精确字符串替换编辑文件。将 old_string 替换为 new_string，若 old_string 不唯一且未设置 replace_all 则报错。"
    required_parameters = ["file_path", "old_string", "new_string"]
    parameters = {
        "file_path": {
            "type": "string",
            "description": "要编辑的文件绝对路径",
        },
        "old_string": {
            "type": "string",
            "description": "要被替换的文本，必须精确匹配",
        },
        "new_string": {
            "type": "string",
            "description": "替换后的文本",
        },
        "replace_all": {
            "type": "boolean",
            "description": "是否替换所有匹配项（默认 false）",
        },
    }

    async def execute(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False, **kwargs: Any
    ) -> ToolResult:
        p = Path(file_path)
        if not p.exists():
            return ToolResult.fail(f"文件不存在 '{file_path}'", error_code="file_not_found", file_path=file_path)

        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult.fail(
                f"读取文件出错：{e}",
                error_code="read_error",
                file_path=file_path,
                exception_type=type(e).__name__,
            )

        count = content.count(old_string)
        if count == 0:
            return ToolResult.fail("在文件中未找到匹配文本", error_code="match_not_found", file_path=file_path)
        if count > 1 and not replace_all:
            return ToolResult.fail(
                f"找到 {count} 处匹配，请设置 replace_all=true 替换全部，或提供更精确的上下文",
                error_code="ambiguous_match",
                file_path=file_path,
                matches=count,
            )

        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
        try:
            p.write_text(new_content, encoding="utf-8")
            replaced = count if replace_all else 1
            return ToolResult.ok(f"已替换 {replaced} 处匹配", file_path=file_path, replaced=replaced)
        except Exception as e:
            return ToolResult.fail(
                f"写入文件出错：{e}",
                error_code="write_error",
                file_path=file_path,
                exception_type=type(e).__name__,
            )
