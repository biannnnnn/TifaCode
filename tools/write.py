from __future__ import annotations

from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult
from tifacode.tools.filetracker import get_file_tracker


class WriteTool(Tool):
    name = "write"
    description = "写入文件。若文件已存在则校验 mtime（需先 read），不存在则直接创建。"
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

        # 若文件已存在，校验 mtime
        if p.exists():
            tracker = get_file_tracker()
            is_stale, last_mtime, cur_mtime = tracker.check_stale(file_path)
            if is_stale:
                return ToolResult.fail(
                    f"文件自上次读取后已被外部修改（read mtime={last_mtime:.3f}, current mtime={cur_mtime:.3f}）。"
                    f"请先 read 该文件获取最新内容，再重新写入。",
                    error_code="stale_file",
                    file_path=file_path,
                    last_mtime=last_mtime,
                    current_mtime=cur_mtime,
                )
            if not is_stale and last_mtime == 0.0:
                # 文件存在但未被 read 过——提醒但允许（新文件或首次写入）
                pass

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            # 写入后更新追踪
            get_file_tracker().record_read(file_path)
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
