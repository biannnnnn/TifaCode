from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tifacode.tools.base import Tool, ToolResult

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".eggs", "*.egg-info",
}


def _render_tree(root: Path, max_depth: int, max_entries: int) -> str:
    root = root.resolve()
    lines: list[str] = [str(root)]
    count = [0]

    def walk(dir_path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth or count[0] >= max_entries:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except (PermissionError, OSError):
            return
        for i, entry in enumerate(entries):
            if count[0] >= max_entries:
                return
            if entry.is_dir() and entry.name in IGNORE_DIRS:
                continue
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            count[0] += 1
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                walk(entry, prefix + extension, depth + 1)

    walk(root, "", 1)
    if count[0] >= max_entries:
        lines.append(f"...(已截断，显示 {count[0]} 项)")
    return "\n".join(lines)


class TreeTool(Tool):
    name = "tree"
    description = "生成项目目录结构摘要，自动忽略 .git、node_modules 等常见目录。"
    required_parameters = []
    parameters = {
        "path": {
            "type": "string",
            "description": "起始目录绝对路径（默认当前工作目录）",
        },
        "max_depth": {
            "type": "integer",
            "description": "最大递归深度（默认 4）",
        },
        "max_entries": {
            "type": "integer",
            "description": "最大显示条目数（默认 300）",
        },
    }

    async def execute(
        self,
        path: str = "",
        max_depth: int = 4,
        max_entries: int = 300,
        **kwargs: Any,
    ) -> ToolResult:
        root = Path(path) if path else Path.cwd()
        if not root.exists():
            return ToolResult.fail(f"目录不存在 '{root}'", error_code="not_found", path=str(root))
        if not root.is_dir():
            return ToolResult.fail(f"路径不是目录 '{root}'", error_code="not_directory", path=str(root))

        try:
            output = _render_tree(root, max_depth, max_entries)
        except Exception as e:
            return ToolResult.fail(f"生成目录树出错：{e}", error_code="tree_error", path=str(root))

        return ToolResult.ok(output, path=str(root), max_depth=max_depth)
