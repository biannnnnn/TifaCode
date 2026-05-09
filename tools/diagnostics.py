from __future__ import annotations

import asyncio
from typing import Any

from tifacode.tools.base import Tool, ToolResult


CHECK_COMMANDS: dict[str, str] = {
    "lint": "ruff check . 2>&1 || true",
    "typecheck": "mypy . 2>&1 || true",
    "test": "python -m pytest --tb=short 2>&1 || true",
}


class DiagnosticsTool(Tool):
    name = "diagnostics"
    description = "运行检查命令（lint、typecheck、test），返回结果摘要。"
    required_parameters = ["check"]
    parameters = {
        "check": {
            "type": "string",
            "description": "检查类型: lint, typecheck, test, all",
            "enum": ["lint", "typecheck", "test", "all"],
        },
        "timeout": {
            "type": "integer",
            "description": "超时秒数（默认 120）",
        },
    }

    async def execute(self, check: str = "lint", timeout: int = 120, **kwargs: Any) -> ToolResult:
        if check == "all":
            checks = ["lint", "typecheck", "test"]
        elif check in CHECK_COMMANDS:
            checks = [check]
        else:
            return ToolResult.fail(f"未知检查类型 '{check}'", error_code="unknown_check")

        results: list[str] = []
        for c in checks:
            cmd = CHECK_COMMANDS[c]
            results.append(f"--- {c} ---")
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                out = stdout.decode("utf-8", errors="replace").strip()
                err = stderr.decode("utf-8", errors="replace").strip()
                if out:
                    # 限制输出行数
                    out_lines = out.splitlines()
                    if len(out_lines) > 50:
                        out = "\n".join(out_lines[:50]) + f"\n...(已截断，共 {len(out_lines)} 行)"
                    results.append(out)
                if err:
                    err_lines = err.splitlines()
                    if len(err_lines) > 20:
                        err = "\n".join(err_lines[:20]) + f"\n...(已截断，共 {len(err_lines)} 行)"
                    results.append(f"[stderr]\n{err}")
                results.append(f"[exit code: {proc.returncode}]")
            except asyncio.TimeoutError:
                results.append(f"[超时 {timeout}s]")
            except Exception as e:
                results.append(f"[错误: {e}]")

        return ToolResult.ok("\n".join(results), checks_run=checks)
