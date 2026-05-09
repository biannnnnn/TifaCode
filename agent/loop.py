from __future__ import annotations

import logging
from typing import Any

from tifacode.agent.backend import BackendAdapter, Done, Event, ReasoningDelta, TextDelta, ToolUse, create_backend
from tifacode.agent.compactor import compact_conversation
from tifacode.agent.messages import Conversation
from tifacode.agent.permissions import decide_tool_permission, permission_cache_key
from tifacode.agent.tool_log import record_tool_call
from tifacode.config.settings import Settings
from tifacode.tools.base import ToolRegistry
from tifacode.tools.base import ToolResult
from tifacode.tools.bash import BashTool
from tifacode.tools.diagnostics import DiagnosticsTool
from tifacode.tools.edit import EditTool
from tifacode.tools.git import GitStatusTool, GitDiffTool
from tifacode.tools.glob import GlobTool
from tifacode.tools.grep import GrepTool
from tifacode.tools.list import ListTool
from tifacode.tools.read import ReadTool
from tifacode.tools.read_many import ReadManyTool
from tifacode.tools.todo import TodoTool
from tifacode.tools.tree import TreeTool
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

    async def on_confirm_tool(self, name: str, tool_input: dict[str, Any], reason: str) -> bool:
        """确认高风险工具执行。返回 True 允许，False 拒绝。"""
        if name == "bash":
            return await self.on_confirm_bash(str(tool_input.get("command", "")))
        return True

    async def on_remember_permission(self, name: str, tool_input: dict[str, Any]) -> bool:
        """确认是否在本会话内记住同一工具调用。"""
        return False


def create_default_registry(settings: Settings | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(ListTool())
    registry.register(GrepTool())
    registry.register(GlobTool())
    registry.register(TreeTool())
    registry.register(TodoTool())
    registry.register(DiagnosticsTool())
    registry.register(GitStatusTool())
    registry.register(GitDiffTool())
    registry.register(ReadManyTool())
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
    approved_tool_calls: set[str] = set()

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

            decision = decide_tool_permission(settings, tu.name, tu.input)
            if not decision.allowed:
                result = ToolResult.fail(
                    decision.reason or "权限系统拒绝了此工具调用",
                    error_code="permission_denied",
                    permission_mode=settings.permission_mode,
                )
                result_text = result.to_text(settings.tool_output_limit)
                record_tool_call(
                    settings,
                    turn=turn,
                    tool_use_id=tu.id,
                    name=tu.name,
                    tool_input=tu.input,
                    result=result,
                    rendered_text=result_text,
                )
                conversation.add_tool_result(tu.id, result_text)
                await callbacks.on_tool_result(tu.name, result_text)
                continue

            if decision.needs_confirmation:
                cache_key = permission_cache_key(tu.name, tu.input)
                if cache_key not in approved_tool_calls:
                    allowed = await callbacks.on_confirm_tool(tu.name, tu.input, decision.reason)
                    if not allowed:
                        result = ToolResult.fail(
                            "用户拒绝了此工具调用",
                            error_code="permission_denied",
                            permission_mode=settings.permission_mode,
                        )
                        result_text = result.to_text(settings.tool_output_limit)
                        record_tool_call(
                            settings,
                            turn=turn,
                            tool_use_id=tu.id,
                            name=tu.name,
                            tool_input=tu.input,
                            result=result,
                            rendered_text=result_text,
                        )
                        conversation.add_tool_result(tu.id, result_text)
                        await callbacks.on_tool_result(tu.name, result_text)
                        continue
                    remember = await callbacks.on_remember_permission(tu.name, tu.input)
                    if remember:
                        approved_tool_calls.add(cache_key)

            result = await registry.execute(tu.name, tu.input)
            result_text = result.to_text(settings.tool_output_limit)
            record_tool_call(
                settings,
                turn=turn,
                tool_use_id=tu.id,
                name=tu.name,
                tool_input=tu.input,
                result=result,
                rendered_text=result_text,
            )
            logger.info(
                "工具执行完成: name=%s success=%s metadata=%s",
                tu.name,
                result.success,
                result.metadata,
            )
            conversation.add_tool_result(tu.id, result_text)
            await callbacks.on_tool_result(tu.name, result_text)

        await callbacks.on_turn_end(turn)

        compact_conversation(conversation, settings)

    else:
        logger.warning(f"达到最大轮次 {settings.max_turns}，强制停止")
