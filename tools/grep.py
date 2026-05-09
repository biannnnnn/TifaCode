from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult


class GrepTool(Tool):
    name = "grep"
    description = "在文件内容中搜索正则表达式，返回匹配行及上下文。"
    required_parameters = ["pattern", "path"]
    parameters = {
        "pattern": {
            "type": "string",
            "description": "正则表达式搜索模式",
        },
        "path": {
            "type": "string",
            "description": "搜索目录或文件的绝对路径",
        },
        "file_pattern": {
            "type": "string",
            "description": "文件名 glob 过滤，如 '*.py'",
        },
        "ignore_case": {
            "type": "boolean",
            "description": "忽略大小写（默认 false）",
        },
        "max_results": {
            "type": "integer",
            "description": "最大返回结果数（默认 100）",
        },
        "context_lines": {
            "type": "integer",
            "description": "每条匹配前后的上下文行数（默认 0）",
        },
    }

    async def execute(
        self,
        pattern: str,
        path: str,
        file_pattern: str = "",
        ignore_case: bool = False,
        max_results: int = 100,
        context_lines: int = 0,
        **kwargs: Any,
    ) -> ToolResult:
        p = Path(path)
        if not p.exists():
            return ToolResult.fail(f"路径不存在 '{path}'", error_code="not_found", path=path)

        try:
            flags = re.IGNORECASE if ignore_case else 0
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult.fail(f"无效的正则表达式：{e}", error_code="invalid_regex", pattern=pattern)

        files: list[Path] = []
        if p.is_file():
            files = [p]
        elif p.is_dir():
            glob = file_pattern or "*"
            try:
                for f in p.rglob(glob):
                    if f.is_file():
                        files.append(f)
            except PermissionError:
                return ToolResult.fail(f"无权限访问目录 '{path}'", error_code="permission_denied", path=path)
        else:
            return ToolResult.fail(f"路径类型不支持 '{path}'", error_code="bad_path", path=path)

        results: list[str] = []
        count = 0
        for f in files:
            if count >= max_results:
                break
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if count >= max_results:
                    break
                if compiled.search(line):
                    rel = f
                    try:
                        rel = f.relative_to(Path.cwd())
                    except ValueError:
                        pass
                    if context_lines > 0:
                        ctx_start = max(0, i - context_lines)
                        ctx_end = min(len(lines), i + context_lines + 1)
                        ctx_lines = []
                        for j in range(ctx_start, ctx_end):
                            marker = ">" if j == i else " "
                            ctx_lines.append(f"  {marker}{j+1}: {lines[j]}")
                        results.append(f"--- {rel}:{i+1} ---")
                        results.extend(ctx_lines)
                    else:
                        results.append(f"{rel}:{i+1}: {line.strip()}")
                    count += 1

        if not results:
            return ToolResult.ok("(未找到匹配)", pattern=pattern, path=path, match_count=0)

        return ToolResult.ok(
            "\n".join(results),
            pattern=pattern,
            path=path,
            match_count=count,
            files_searched=len(files),
        )
