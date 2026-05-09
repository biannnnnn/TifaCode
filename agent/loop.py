from __future__ import annotations

import asyncio
import logging
from typing import Any

from tifacode.agent.backend import BackendAdapter, Done, Event, ReasoningDelta, TextDelta, ToolUse, create_backend
from tifacode.agent.compactor import compact_conversation
from tifacode.agent.messages import Conversation
from tifacode.agent.permissions import PermissionDecision, decide_tool_permission, permission_cache_key
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
    """创建并注册所有工具。Tier 1 为核心工具（前 3 轮即可用），Tier 2 为扩展工具（第 4 轮起激活）。"""
    registry = ToolRegistry()
    # Tier 1: 核心工具，始终可用
    registry.register(ReadTool(), tier=1)
    registry.register(WriteTool(), tier=1)
    registry.register(EditTool(), tier=1)
    registry.register(ListTool(), tier=1)
    registry.register(GrepTool(), tier=1)
    registry.register(GlobTool(), tier=1)
    registry.register(TreeTool(), tier=1)
    # Tier 2: 扩展工具，第 4 轮起激活
    registry.register(TodoTool(), tier=2)
    registry.register(DiagnosticsTool(), tier=2)
    registry.register(GitStatusTool(), tier=2)
    registry.register(GitDiffTool(), tier=2)
    registry.register(ReadManyTool(), tier=2)
    bash_timeout = settings.bash_timeout if settings is not None else 120
    registry.register(BashTool(permission_check=True, default_timeout=bash_timeout), tier=1)
    return registry


async def _execute_tools_concurrently(
    tool_uses: list[tuple[str, ToolUse]],
    registry: ToolRegistry,
    settings: Settings,
    turn: int,
    conversation: Conversation,
    callbacks: AgentCallbacks,
) -> None:
    """并发执行一组已通过权限检查的工具调用。失败时逐一回退为顺序执行。"""
    if len(tool_uses) == 1:
        # 单工具：直接顺序执行
        tu_id, tu = tool_uses[0]
        await _execute_single_tool(tu_id, tu, registry, settings, turn, conversation, callbacks)
        return

    # 多工具：尝试并发
    async def run_one(tu_id: str, tu: ToolUse) -> tuple[str, ToolUse, ToolResult | None, Exception | None]:
        try:
            result = await registry.execute(tu.name, tu.input)
            return tu_id, tu, result, None
        except Exception as e:
            return tu_id, tu, None, e

    tasks = [run_one(tu_id, tu) for tu_id, tu in tool_uses]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    for tu_id, tu, result, exc in gathered:
        if exc is not None:
            logger.warning("并发执行 %s 失败，回退顺序执行: %s", tu.name, exc)
            result = await registry.execute(tu.name, tu.input)

        result_text = result.to_text(settings.tool_output_limit)
        record_tool_call(
            settings, turn=turn, tool_use_id=tu_id, name=tu.name,
            tool_input=tu.input, result=result, rendered_text=result_text,
        )
        logger.info(
            "工具执行完成: name=%s success=%s metadata=%s",
            tu.name, result.success, result.metadata,
        )
        conversation.add_tool_result(tu_id, result_text)
        await callbacks.on_tool_result(tu.name, result_text)


async def _execute_single_tool(
    tu_id: str,
    tu: ToolUse,
    registry: ToolRegistry,
    settings: Settings,
    turn: int,
    conversation: Conversation,
    callbacks: AgentCallbacks,
) -> None:
    result = await registry.execute(tu.name, tu.input)
    result_text = result.to_text(settings.tool_output_limit)
    record_tool_call(
        settings, turn=turn, tool_use_id=tu_id, name=tu.name,
        tool_input=tu.input, result=result, rendered_text=result_text,
    )
    logger.info(
        "工具执行完成: name=%s success=%s metadata=%s",
        tu.name, result.success, result.metadata,
    )
    conversation.add_tool_result(tu_id, result_text)
    await callbacks.on_tool_result(tu.name, result_text)


async def run_agent_loop(
    conversation: Conversation,
    backend: BackendAdapter,
    registry: ToolRegistry,
    settings: Settings,
    callbacks: AgentCallbacks,
) -> None:
    """执行 Agent 主循环：LLM 调用 → 工具执行 → 循环，直到模型不再调用工具或达到最大轮次。"""
    # 延迟激活：前 3 轮只暴露核心工具，节省 Token
    registry.set_active_tier(1)
    approved_tool_calls: set[str] = set()

    for turn in range(1, settings.max_turns + 1):
        logger.info(f"第 {turn} 轮对话开始 (active_tier={registry.active_tier})")

        # 第 4 轮起激活全部工具
        if turn == 4 and registry.active_tier < 2:
            registry.set_active_tier(2)
            logger.info("已激活 Tier 2 扩展工具")

        tools = registry.get_schemas()

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
            conversation.add_assistant(content_blocks)
            await callbacks.on_turn_end(turn)
            break

        conversation.add_assistant(content_blocks)

        # 权限预检：分离 允许 / 需确认 / 已拒绝
        ready: list[tuple[str, ToolUse]] = []  # 可直接并发执行的
        pending_confirm: list[tuple[str, ToolUse, PermissionDecision]] = []  # 需用户确认的

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
                    settings, turn=turn, tool_use_id=tu.id, name=tu.name,
                    tool_input=tu.input, result=result, rendered_text=result_text,
                )
                conversation.add_tool_result(tu.id, result_text)
                await callbacks.on_tool_result(tu.name, result_text)
                continue

            if decision.needs_confirmation:
                cache_key = permission_cache_key(tu.name, tu.input)
                if cache_key in approved_tool_calls:
                    ready.append((tu.id, tu))
                else:
                    pending_confirm.append((tu.id, tu, decision))
            else:
                ready.append((tu.id, tu))

        # 处理需确认的工具
        for tu_id, tu, decision in pending_confirm:
            cache_key = permission_cache_key(tu.name, tu.input)
            allowed = await callbacks.on_confirm_tool(tu.name, tu.input, decision.reason)
            if not allowed:
                result = ToolResult.fail(
                    "用户拒绝了此工具调用",
                    error_code="permission_denied",
                    permission_mode=settings.permission_mode,
                )
                result_text = result.to_text(settings.tool_output_limit)
                record_tool_call(
                    settings, turn=turn, tool_use_id=tu_id, name=tu.name,
                    tool_input=tu.input, result=result, rendered_text=result_text,
                )
                conversation.add_tool_result(tu_id, result_text)
                await callbacks.on_tool_result(tu.name, result_text)
                continue
            remember = await callbacks.on_remember_permission(tu.name, tu.input)
            if remember:
                approved_tool_calls.add(cache_key)
            # 确认后的工具也加入并发队列（单独执行，不并入并发以避免交互顺序混乱）
            await _execute_single_tool(tu_id, tu, registry, settings, turn, conversation, callbacks)

        # 并发执行已就绪的工具
        if ready:
            await _execute_tools_concurrently(
                ready, registry, settings, turn, conversation, callbacks,
            )

        await callbacks.on_turn_end(turn)

        compact_conversation(conversation, settings)

    else:
        logger.warning(f"达到最大轮次 {settings.max_turns}，强制停止")
