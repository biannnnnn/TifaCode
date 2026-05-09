from __future__ import annotations

import asyncio
from typing import Any

from tifacode.tools.base import Tool, ToolResult


async def _run_git(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    return proc.returncode or 0, out, err


class GitStatusTool(Tool):
    name = "git_status"
    description = "显示 Git 工作区状态（git status --short）。"
    required_parameters = []
    parameters = {
        "path": {
            "type": "string",
            "description": "仓库路径（默认当前目录）",
        },
    }

    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        try:
            code, out, err = await _run_git(["status", "--short", "--branch"])
        except asyncio.TimeoutError:
            return ToolResult.fail("git status 超时", error_code="timeout")
        except Exception as e:
            return ToolResult.fail(f"git status 出错：{e}", error_code="git_error")

        if code != 0 and err:
            return ToolResult.fail(f"git status 失败: {err}", output=out, error_code="git_error")

        if not out:
            out = "(工作区干净，无变更)"
        return ToolResult.ok(out, exit_code=code)


class GitDiffTool(Tool):
    name = "git_diff"
    description = "显示 Git 差异（git diff）。显示未暂存的改动。"
    required_parameters = []
    parameters = {
        "staged": {
            "type": "boolean",
            "description": "是否显示已暂存的差异（git diff --staged，默认 false）",
        },
        "max_output": {
            "type": "integer",
            "description": "最大输出行数（默认 200）",
        },
    }

    async def execute(self, staged: bool = False, max_output: int = 200, **kwargs: Any) -> ToolResult:
        args = ["diff"]
        if staged:
            args.append("--staged")

        try:
            code, out, err = await _run_git(args)
        except asyncio.TimeoutError:
            return ToolResult.fail("git diff 超时", error_code="timeout")
        except Exception as e:
            return ToolResult.fail(f"git diff 出错：{e}", error_code="git_error")

        if code != 0 and err:
            return ToolResult.fail(f"git diff 失败: {err}", output=out, error_code="git_error")

        if not out:
            return ToolResult.ok("(无差异)")

        lines = out.splitlines()
        if len(lines) > max_output:
            out = "\n".join(lines[:max_output]) + f"\n...(已截断，共 {len(lines)} 行)"
        return ToolResult.ok(out, lines=len(lines))
