from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tifacode.tools.base import Tool, ToolResult


@dataclass
class TodoItem:
    content: str
    status: str = "pending"  # pending, in_progress, completed
    activeForm: str = ""

    def to_line(self) -> str:
        marks = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        mark = marks.get(self.status, "[ ]")
        return f"{mark} {self.content}"


class TodoTool(Tool):
    """内存中的任务列表管理工具，不持久化到文件。"""

    name = "todo"
    description = "管理任务计划状态。支持列出、添加、更新、删除任务。"
    required_parameters = ["action"]
    parameters = {
        "action": {
            "type": "string",
            "description": "操作类型: list, add, update, delete",
            "enum": ["list", "add", "update", "delete"],
        },
        "content": {
            "type": "string",
            "description": "任务内容（add 时需要）",
        },
        "status": {
            "type": "string",
            "description": "任务状态: pending, in_progress, completed（update 时需要）",
            "enum": ["pending", "in_progress", "completed"],
        },
        "index": {
            "type": "integer",
            "description": "任务索引（update/delete 时需要，从 0 开始）",
        },
    }

    _tasks: list[TodoItem] = []

    async def execute(
        self,
        action: str,
        content: str = "",
        status: str = "",
        index: int = -1,
        **kwargs: Any,
    ) -> ToolResult:
        if action == "list":
            if not self._tasks:
                return ToolResult.ok("(无任务)", task_count=0)
            lines = [f"{i}. {t.to_line()}" for i, t in enumerate(self._tasks)]
            return ToolResult.ok("\n".join(lines), task_count=len(self._tasks))

        elif action == "add":
            if not content.strip():
                return ToolResult.fail("add 操作需要提供 content", error_code="missing_content")
            item = TodoItem(content=content.strip())
            self._tasks.append(item)
            return ToolResult.ok(f"已添加任务 [{len(self._tasks) - 1}]: {item.to_line()}", index=len(self._tasks) - 1)

        elif action == "update":
            if index < 0 or index >= len(self._tasks):
                return ToolResult.fail(f"无效索引 {index}（共 {len(self._tasks)} 个任务）", error_code="bad_index")
            if status and status not in ("pending", "in_progress", "completed"):
                return ToolResult.fail(f"无效状态 '{status}'", error_code="bad_status")
            self._tasks[index].status = status
            if content:
                self._tasks[index].content = content.strip()
            return ToolResult.ok(f"已更新任务 [{index}]: {self._tasks[index].to_line()}", index=index)

        elif action == "delete":
            if index < 0 or index >= len(self._tasks):
                return ToolResult.fail(f"无效索引 {index}（共 {len(self._tasks)} 个任务）", error_code="bad_index")
            removed = self._tasks.pop(index)
            return ToolResult.ok(f"已删除任务: {removed.to_line()}", index=index, task_count=len(self._tasks))

        return ToolResult.fail(f"未知操作 '{action}'", error_code="unknown_action")
