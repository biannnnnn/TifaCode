from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from tifacode.agent.backend import BackendAdapter, Done, Event, ReasoningDelta, TextDelta, ToolUse, create_backend
from tifacode.agent.messages import Conversation
from tifacode.config.settings import Settings
from tifacode.tools.base import ToolRegistry
from tifacode.tools.bash import BashTool
from tifacode.tools.edit import EditTool
from tifacode.tools.read import ReadTool
from tifacode.tools.write import WriteTool

logger = logging.getLogger(__name__)


class AgentCallbacks:
    """Agent 循环回调接口。CLI 层实现此接口来渲染输出。"""

    async def on_text_delta(self, text: str) -> None:
        """流式文本增量。"""

    async def on_tool_call(self, name: str, input: dict[str, Any]) -> None:
        """工具调用开始。"""

    async def on_tool_result(self, name: str, result: str) -> None:
        """工具执行完成。"""

    async def on_turn_end(self, turn: int) -> None:
        """一轮对话结束。"""

    async def on_confirm_bash(self, command: str) -> bool:
        """确认 bash 命令执行。返回 True 允许，False 拒绝。"""
        return True


def create_default_registry(settings: Settings | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    bash_timeout = settings.bash_timeout if settings is not None else 120
    registry.register(BashTool(permission_check=True, default_timeout=bash_timeout))
    return registry


async def run_agent_loop(
    conversation: Conversation,
    backend: BackendAdapter,
    registry: ToolRegistry,
    settings: Settings,
    callbacks: AgentCallbacks,
) -> None:
    """执行 Agent 主循环：LLM 调用 → 工具执行 → 循环，直到模型不再调用工具或达到最大轮次。"""
    tools = registry.get_schemas()

    for turn in range(1, settings.max_turns + 1):
        logger.info(f"第 {turn} 轮对话开始")

        content_blocks: list[dict[str, Any]] = []
        tool_uses: dict[str, ToolUse] = {}  # id -> ToolUse
        text_buffer: list[str] = []
        reasoning_buffer: list[str] = []

        api_messages = conversation.to_api_format(settings.provider)

        async for event in backend.stream(api_messages, tools):
            if isinstance(event, TextDelta):
                text_buffer.append(event.text)
                await callbacks.on_text_delta(event.text)

            elif isinstance(event, ReasoningDelta):
                reasoning_buffer.append(event.text)

            elif isinstance(event, ToolUse):
                if event.input:
                    tool_uses[event.id] = event

            elif isinstance(event, Done):
                logger.info(f"第 {turn} 轮完成: stop_reason={event.stop_reason}, usage={event.usage}")

        # 构建 assistant content
        if text_buffer:
            content_blocks.append({"type": "text", "text": "".join(text_buffer)})
        if reasoning_buffer:
            content_blocks.append({"type": "reasoning", "text": "".join(reasoning_buffer)})
        for tu in tool_uses.values():
            content_blocks.append({"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input})

        if not tool_uses:
            # 没有工具调用，对话结束
            conversation.add_assistant(content_blocks)
            await callbacks.on_turn_end(turn)
            break

        # 有工具调用：先添加 assistant 消息，然后执行工具
        conversation.add_assistant(content_blocks)

        for tu in tool_uses.values():
            await callbacks.on_tool_call(tu.name, tu.input)

            # bash 命令需确认
            if tu.name == "bash":
                command = tu.input.get("command", "")
                allowed = await callbacks.on_confirm_bash(command)
                if not allowed:
                    conversation.add_tool_result(tu.id, "用户拒绝了此命令的执行")
                    continue

            result = await registry.execute(tu.name, tu.input)
            conversation.add_tool_result(tu.id, result)
            await callbacks.on_tool_result(tu.name, result)

        await callbacks.on_turn_end(turn)

    else:
        logger.warning(f"达到最大轮次 {settings.max_turns}，强制停止")
