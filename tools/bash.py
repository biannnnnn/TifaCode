from __future__ import annotations

import asyncio
import os
from typing import Any

from tifacode.tools.base import Tool, ToolResult

DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf --no-preserve-root",
    "sudo rm",
    "mkfs.",
    "dd if=",
    ":(){ :|:& };:",
    "chmod 777 /",
    "chmod -R 777 /",
    "> /dev/sda",
    "mv / /dev/null",
]


def is_dangerous(command: str) -> str | None:
    """检查命令是否包含危险操作，返回危险模式描述或 None。"""
    lower = command.lower().strip()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in lower:
            return pattern
    return None


class BashTool(Tool):
    name = "bash"
    description = "执行 Shell 命令。命令有 120 秒超时限制。危险命令（如 rm -rf /）将被拒绝。"
    required_parameters = ["command"]
    parameters = {
        "command": {
            "type": "string",
            "description": "要执行的 Shell 命令",
        },
        "timeout": {
            "type": "integer",
            "description": "超时秒数（默认 120）",
        },
    }

    def __init__(self, permission_check: bool = True, default_timeout: int = 120) -> None:
        self._permission_check = permission_check
        self._default_timeout = default_timeout

    async def execute(self, command: str, timeout: int | None = None, **kwargs: Any) -> ToolResult:
        timeout = timeout or self._default_timeout
        dangerous = is_dangerous(command)
        if dangerous:
            return ToolResult.fail(
                f"安全拦截：命令包含危险模式 '{dangerous}'，已拒绝执行",
                error_code="dangerous_command",
                command=command,
                dangerous_pattern=dangerous,
            )

        cwd = os.getcwd()
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            parts = []
            if out:
                parts.append(out)
            if err:
                parts.append(f"[stderr]\n{err}")
            if proc.returncode != 0:
                parts.append(f"[exit code: {proc.returncode}]")
            output = "\n".join(parts) if parts else "(无输出)"
            if proc.returncode == 0:
                return ToolResult.ok(output, command=command, exit_code=proc.returncode, cwd=cwd)
            return ToolResult.fail(
                f"命令执行失败，退出码 {proc.returncode}",
                output=output,
                error_code="command_failed",
                command=command,
                exit_code=proc.returncode,
                cwd=cwd,
            )
        except asyncio.TimeoutError:
            return ToolResult.fail(
                f"命令超时（{timeout} 秒）",
                error_code="timeout",
                command=command,
                timeout=timeout,
                cwd=cwd,
            )
        except Exception as e:
            return ToolResult.fail(
                f"命令执行出错：{e}",
                error_code="command_error",
                command=command,
                cwd=cwd,
                exception_type=type(e).__name__,
            )
