from __future__ import annotations

import asyncio
import os
from typing import Any

from tifacode.tools.base import Tool

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

    async def execute(self, command: str, timeout: int | None = None, **kwargs: Any) -> str:
        timeout = timeout or self._default_timeout
        dangerous = is_dangerous(command)
        if dangerous:
            return f"安全拦截：命令包含危险模式 '{dangerous}'，已拒绝执行"

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
            return "\n".join(parts) if parts else "(无输出)"
        except asyncio.TimeoutError:
            return f"错误：命令超时（{timeout} 秒）"
        except Exception as e:
            return f"命令执行出错：{e}"
