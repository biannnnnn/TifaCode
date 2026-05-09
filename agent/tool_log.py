from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from tifacode.config.settings import Settings
from tifacode.tools.base import ToolResult

logger = logging.getLogger(__name__)


def _shorten(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        if limit > 0 and len(value) > limit:
            return f"{value[:limit]}...[truncated {len(value) - limit} chars]"
        return value
    if isinstance(value, dict):
        return {k: _shorten(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten(v, limit) for v in value]
    return value


def record_tool_call(
    settings: Settings,
    *,
    turn: int,
    tool_use_id: str,
    name: str,
    tool_input: dict[str, Any],
    result: ToolResult,
    rendered_text: str,
) -> None:
    if not settings.tool_log_enabled:
        return

    path = settings.resolved_tool_log_file
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "turn": turn,
        "tool_use_id": tool_use_id,
        "tool": name,
        "input": _shorten(tool_input, settings.tool_log_input_limit),
        "success": result.success,
        "error": result.error,
        "error_code": result.error_code,
        "metadata": result.metadata,
        "output_chars": len(result.output),
        "rendered_chars": len(rendered_text),
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("工具调用日志写入失败: %s", path, exc_info=True)
