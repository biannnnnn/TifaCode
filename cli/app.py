from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from tifacode.agent.backend import create_backend
from tifacode.agent.loop import AgentCallbacks, create_default_registry, run_agent_loop
from tifacode.agent.messages import Conversation
from tifacode.config.settings import Settings
from tifacode.session.store import SessionStore

logger = logging.getLogger(__name__)


class CLICallbacks(AgentCallbacks):
    def __init__(self, live: Live, console: Console) -> None:
        self._live = live
        self._console = console
        self._current_tool_panels: list[Panel] = []
        self._accumulated: list[str] = []

    async def on_text_delta(self, text: str) -> None:
        self._accumulated.append(text)
        self._update_live()

    async def on_tool_call(self, name: str, input: dict[str, Any]) -> None:
        args = ", ".join(f"{k}={v!r}" for k, v in input.items())
        self._current_tool_panels.append(
            Panel(f"执行中...", title=f"🔧 {name}", border_style="cyan", title_align="left")
        )

    async def on_tool_result(self, name: str, result: str) -> None:
        preview = result[:800] + ("..." if len(result) > 800 else "")
        if self._current_tool_panels:
            self._current_tool_panels[-1] = Panel(
                preview, title=f"📋 {name}", border_style="dim", title_align="left"
            )

    async def on_turn_end(self, turn: int) -> None:
        self._current_tool_panels.clear()

    async def on_confirm_bash(self, command: str) -> bool:
        # 在 live 外部显示确认提示
        self._live.stop()
        try:
            resp = input(f"  ⚠ 执行命令: {command[:100]} [Y/n] ").strip().lower()
            return resp in ("", "y", "yes")
        finally:
            self._live.start()

    def _update_live(self) -> None:
        md = Markdown("".join(self._accumulated))
        renderables: list = [md]
        renderables.extend(self._current_tool_panels)
        self._live.update(Panel.group(*renderables) if len(renderables) > 1 else md)

    def reset(self) -> None:
        self._accumulated.clear()
        self._current_tool_panels.clear()


async def run_interactive(settings: Settings, session_name: str) -> None:
    console = Console()
    store = SessionStore()

    conversation: Conversation
    if session_name in store.list_sessions():
        conversation = store.load(session_name)
        console.print(f"[dim]已恢复会话 '{session_name}'[/dim]")
    else:
        conversation = Conversation()
        console.print(f"[dim]新会话 '{session_name}'[/dim]")

    backend = create_backend(settings)
    registry = create_default_registry()

    console.print(Panel("TifaCode — Coding Agent CLI", border_style="blue"))
    console.print("输入消息开始对话，/help 查看帮助，/exit 退出\n")

    while True:
        try:
            user_input = console.input("[bold green]> [/bold green]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            _handle_slash_command(user_input, console)
            if user_input in ("/exit", "/quit", "/q"):
                break
            continue

        conversation.add_user(user_input)

        with Live(Text("思考中..."), console=console, refresh_per_second=10, transient=False) as live:
            callbacks = CLICallbacks(live, console)
            try:
                await run_agent_loop(conversation, backend, registry, settings, callbacks)
            except Exception as e:
                live.stop()
                console.print(f"[red]错误: {e}[/red]")
                logger.exception("Agent loop error")
                live.start()

        console.print()  # 空行分隔
        store.save(session_name, conversation)


async def run_single_shot(settings: Settings, prompt: str, session_name: str) -> None:
    console = Console()
    store = SessionStore()

    conversation = Conversation()
    if session_name in store.list_sessions():
        conversation = store.load(session_name)
        console.print(f"[dim]已恢复会话 '{session_name}'[/dim]")

    conversation.add_user(prompt)
    backend = create_backend(settings)
    registry = create_default_registry()

    with Live(Text("思考中..."), console=console, refresh_per_second=10, transient=False) as live:
        callbacks = CLICallbacks(live, console)
        try:
            await run_agent_loop(conversation, backend, registry, settings, callbacks)
        except Exception as e:
            live.stop()
            console.print(f"[red]错误: {e}[/red]")
            logger.exception("Agent loop error")

    console.print()
    store.save(session_name, conversation)


def _handle_slash_command(cmd: str, console: Console) -> None:
    parts = cmd.split(maxsplit=1)
    name = parts[0].lower()

    if name in ("/exit", "/quit", "/q"):
        console.print("[dim]再见[/dim]")
    elif name == "/help":
        console.print(
            Panel(
                "命令:\n"
                "  /help      显示帮助\n"
                "  /clear     清空当前会话\n"
                "  /exit      退出程序\n"
                "  /sessions  列出已保存的会话\n"
                "  /model     显示当前模型",
                title="帮助",
                border_style="dim",
            )
        )
    elif name == "/clear":
        console.print("[dim]会话已清空（下次输入将开始新对话）[/dim]")
    elif name == "/sessions":
        store = SessionStore()
        sessions = store.list_sessions()
        if sessions:
            console.print("\n".join(f"  • {s}" for s in sessions))
        else:
            console.print("[dim]无已保存的会话[/dim]")
    elif name == "/model":
        from tifacode.config.settings import load_settings
        s = load_settings()
        console.print(f"  provider: {s.provider}\n  model: {s.model}")
    else:
        console.print(f"[dim]未知命令: {name}，输入 /help 查看帮助[/dim]")
